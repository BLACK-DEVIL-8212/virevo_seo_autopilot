"""Centralized event manager for real-time process monitoring.

Handles event emission, storage, and pub/sub for SSE streaming.
"""
from __future__ import annotations
import json
import threading
import queue
import time
from datetime import datetime
from typing import Dict, List, Optional, Callable
from collections import defaultdict

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from .config import Config
from .database.database import retry_on_lock, new_session
from .database.models import ProcessEvent, BackgroundJob, Base

_IS_SQLITE = "sqlite" in Config.DATABASE_URL

_engine = create_engine(
    Config.DATABASE_URL,
    future=True,
    echo=False,
    connect_args={
        "check_same_thread": False,
        "timeout": 30.0,
    } if _IS_SQLITE else {},
)
_Session = sessionmaker(bind=_engine, autoflush=False, autocommit=False, future=True)

if _IS_SQLITE:
    @event.listens_for(_engine, "connect")
    def _set_sqlite_pragmas(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=30000")
        cursor.close()

Base.metadata.create_all(bind=_engine)

# Global event storage queue and thread
_event_queue: queue.Queue = queue.Queue(maxsize=10000)
_event_storage_thread: Optional[threading.Thread] = None
_event_storage_running = threading.Event()


def _start_storage_thread():
    """Start the background thread that stores events to database."""
    global _event_storage_thread
    if _event_storage_thread is None or not _event_storage_thread.is_alive():
        _event_storage_running.set()
        _event_storage_thread = threading.Thread(target=_process_event_queue, daemon=True)
        _event_storage_thread.start()


def _process_event_queue():
    """Process events from the queue and store them in the database."""
    while _event_storage_running.is_set():
        try:
            event_data = _event_queue.get(timeout=1)
            _store_event_immediate(event_data)
        except queue.Empty:
            continue
        except Exception as e:
            import traceback
            print(f"Error processing event: {e}")
            traceback.print_exc()


def _store_event_immediate(event_data: dict):
    """Store event to database with retry logic."""
    max_retries = 3
    for attempt in range(max_retries):
        sess = _Session()
        try:
            event = ProcessEvent(
                job_id=event_data["job_id"],
                website_id=event_data.get("website_id"),
                agent_name=event_data.get("agent_name", ""),
                event_type=event_data["event_type"],
                severity=event_data.get("severity", "info"),
                message=event_data.get("message", ""),
                url=event_data.get("url", ""),
                metadata_json=event_data.get("metadata", {}),
            )
            sess.add(event)
            sess.commit()
            return
        except Exception as e:
            sess.rollback()
            if "locked" in str(e).lower() and attempt < max_retries - 1:
                time.sleep(0.1 * (attempt + 1))
                continue
            if attempt == max_retries - 1:
                import traceback
                print(f"Failed to store event after {max_retries} attempts: {e}")
        finally:
            sess.close()


class EventManager:
    """Central event system for AI process monitoring."""

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._subscribers: Dict[str, List[queue.Queue]] = defaultdict(list)
        self._global_subscribers: List[queue.Queue] = []
        self._initialized = True
        _start_storage_thread()

    def emit(self, job_id: str, event_type: str, message: str = "",
             agent_name: str = "", severity: str = "info",
             url: str = "", metadata: dict = None, website_id: int = None):
        """Emit an event - stores in DB and notifies subscribers."""
        event_data = {
            "job_id": job_id,
            "event_type": event_type,
            "message": message,
            "agent_name": agent_name,
            "severity": severity,
            "url": url,
            "metadata": metadata or {},
            "website_id": website_id,
            "timestamp": datetime.utcnow().isoformat(),
        }

        # Store in database
        self._store_event(event_data)

        # Notify subscribers
        self._notify(job_id, event_data)

    def _store_event(self, event_data: dict):
        """Queue event for storage in database."""
        try:
            _event_queue.put(event_data, timeout=5)
        except queue.Full:
            logger.warning("Event queue full, dropping event: %s", event_data.get("event_type", ""))

    def subscribe(self, job_id: str, q: queue.Queue):
        """Subscribe to events for a specific job."""
        self._subscribers[job_id].append(q)

    def subscribe_global(self, q: queue.Queue):
        """Subscribe to all events."""
        self._global_subscribers.append(q)

    def unsubscribe(self, job_id: str, q: queue.Queue):
        """Remove a subscriber."""
        if job_id in self._subscribers:
            try:
                self._subscribers[job_id].remove(q)
            except ValueError:
                pass

    def unsubscribe_global(self, q: queue.Queue):
        """Remove a global subscriber."""
        try:
            self._global_subscribers.remove(q)
        except ValueError:
            pass

    def _notify(self, job_id: str, event_data: dict):
        """Send event to all relevant subscribers."""
        # Notify job-specific subscribers
        for q in self._subscribers.get(job_id, []):
            try:
                q.put_nowait(event_data)
            except queue.Full:
                pass

        # Notify global subscribers
        for q in self._global_subscribers:
            try:
                q.put_nowait(event_data)
            except queue.Full:
                pass

    def get_events(self, job_id: str, limit: int = 500) -> List[dict]:
        """Get historical events for a job."""
        sess = _Session()
        try:
            events = (sess.query(ProcessEvent)
                     .filter_by(job_id=job_id)
                     .order_by(ProcessEvent.created_at.asc())
                     .limit(limit)
                     .all())
            return [{
                "id": e.id,
                "job_id": e.job_id,
                "agent_name": e.agent_name,
                "event_type": e.event_type,
                "severity": e.severity,
                "message": e.message,
                "url": e.url,
                "metadata": e.metadata_json,
                "timestamp": e.created_at.isoformat(),
            } for e in events]
        finally:
            sess.close()

    def get_job_stats(self, job_id: str) -> dict:
        """Get aggregated stats for a job.

        Counts events for real-time monitoring during a crawl, but when an
        authoritative ``crawl_result`` event has been emitted (after the crawl
        finishes), the counters from that event override the event-counted
        values so the UI and Background Job always agree (Task 3).
        """
        sess = _Session()
        try:
            events = sess.query(ProcessEvent).filter_by(job_id=job_id).all()
            stats = {
                "total_events": len(events),
                "pages_crawled": 0,
                "pages_discovered": 0,
                "pages_queued": 0,
                "pages_failed": 0,
                "pages_skipped": 0,
                "pages_blocked": 0,
                "issues_found": 0,
                "errors": 0,
                "by_severity": defaultdict(int),
                "by_agent": defaultdict(int),
                "current_url": "",
                "current_agent": "",
            }
            for e in events:
                stats["by_severity"][e.severity] += 1
                if e.agent_name:
                    stats["by_agent"][e.agent_name] += 1
                if e.event_type == "page_crawled":
                    stats["pages_crawled"] += 1
                elif e.event_type == "url_discovered":
                    stats["pages_discovered"] += 1
                elif e.event_type == "page_queued":
                    stats["pages_queued"] = stats.get("pages_queued", 0) + 1
                elif e.event_type == "page_crawl_failed":
                    stats["pages_failed"] = stats.get("pages_failed", 0) + 1
                elif e.event_type == "page_crawl_skipped":
                    stats["pages_skipped"] = stats.get("pages_skipped", 0) + 1
                elif e.event_type == "page_blocked":
                    stats["pages_blocked"] = stats.get("pages_blocked", 0) + 1
                elif e.event_type == "seo_issue_found":
                    stats["issues_found"] += 1
                elif e.event_type in ("page_crawl_failed", "error"):
                    stats["errors"] += 1
                if e.event_type in ("crawl_started", "page_crawl_started"):
                    stats["current_url"] = e.url
                if e.agent_name:
                    stats["current_agent"] = e.agent_name

            # Override with authoritative crawl_result event if present (Task 3)
            result_meta = None
            for e in events:
                if e.event_type == "crawl_result" and e.metadata_json:
                    result_meta = e.metadata_json
                    break
            if result_meta:
                for key in ("pages_crawled", "pages_discovered", "pages_queued",
                            "pages_failed", "pages_skipped", "pages_blocked"):
                    if key in result_meta:
                        stats[key] = result_meta[key]
                if "errors" in result_meta:
                    stats["errors"] = len(result_meta["errors"]) if isinstance(
                        result_meta["errors"], list) else result_meta["errors"]

            return stats
        finally:
            sess.close()

    def check_control_signal(self, job_id: str) -> Optional[str]:
        """Check for pause/resume/stop signals."""
        sess = _Session()
        try:
            def _do():
                job = sess.query(BackgroundJob).filter_by(job_id=job_id).first()
                if job and job._control:
                    signal = job._control
                    job._control = ""
                    sess.commit()
                    return signal
                return None
            return retry_on_lock(_do, cleanup=lambda: sess.rollback())
        finally:
            sess.close()

    def send_control_signal(self, job_id: str, signal: str):
        """Send a control signal to a job."""
        sess = _Session()
        try:
            def _do():
                job = sess.query(BackgroundJob).filter_by(job_id=job_id).first()
                if job:
                    job._control = signal
                    if signal == "pause":
                        job.status = "paused"
                    elif signal == "resume":
                        job.status = "running"
                    elif signal == "stop":
                        job.status = "stopped"
                    sess.commit()
            retry_on_lock(_do, cleanup=lambda: sess.rollback())
        finally:
            sess.close()


def get_event_manager() -> EventManager:
    """Get the singleton EventManager instance."""
    return EventManager()
