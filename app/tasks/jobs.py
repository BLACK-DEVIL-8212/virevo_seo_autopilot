"""Background job system using threading.

Tracks job state in the database and runs tasks in background threads.
"""
from __future__ import annotations
import uuid
import threading
import traceback
from datetime import datetime
from typing import Callable, Optional, Dict

from flask import has_app_context, g

from ..database.database import SessionLocal, new_session, retry_on_lock
from ..database.models import BackgroundJob
from ..events import get_event_manager

_scheduler = None


def get_scheduler():
    global _scheduler
    if _scheduler is None:
        from apscheduler.schedulers.background import BackgroundScheduler
        _scheduler = BackgroundScheduler(daemon=True)
        _scheduler.start()
    return _scheduler


def _job_to_dict(job: BackgroundJob) -> dict:
    """Serialize a BackgroundJob to a plain dict so the result does not depend
    on a live SQLAlchemy session (avoids DetachedInstanceError when the session
    that produced the object is later closed)."""
    return {
        "id": job.id,
        "job_id": job.job_id,
        "job_type": job.job_type,
        "website_id": job.website_id,
        "status": job.status,
        "progress": job.progress,
        "message": job.message,
        "result_json": job.result_json or {},
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "updated_at": job.updated_at.isoformat() if job.updated_at else None,
        "_control": job._control,
    }


def _read_session():
    """Return a (session, owns) pair for read-only queries.

    When invoked from within a Flask request that already opened a session via
    ``get_session()``, the existing request-bound session is reused and
    *not* closed by us — closing it would expire/detach every object the route
    is still using (e.g. the ``Website``) and trigger
    ``DetachedInstanceError`` during template rendering.

    When invoked outside a request (e.g. from a background thread) a fresh
    session is opened and the caller is responsible for closing it.
    """
    if has_app_context() and "db_session" in g:
        return g.db_session, False
    sess = SessionLocal()
    return sess, True


def _record_start(job_id: str):
    sess = new_session()
    try:
        def _do():
            j = sess.query(BackgroundJob).filter_by(job_id=job_id).first()
            if j:
                j.status = "running"
                j.updated_at = datetime.utcnow()
                sess.commit()
        retry_on_lock(_do, cleanup=lambda: sess.rollback())
    finally:
        sess.close()


def _record_finish(job_id: str, ok: bool, result: Dict = None, message: str = ""):
    sess = new_session()
    try:
        def _do():
            j = sess.query(BackgroundJob).filter_by(job_id=job_id).first()
            if j:
                j.status = "completed" if ok else "failed"
                if ok:
                    j.progress = 100
                j.message = message
                j.result_json = result or {}
                j.updated_at = datetime.utcnow()
                sess.commit()
        retry_on_lock(_do, cleanup=lambda: sess.rollback())
    finally:
        sess.close()


def _record_progress(job_id: str, progress: int, message: str = ""):
    sess = new_session()
    try:
        def _do():
            j = sess.query(BackgroundJob).filter_by(job_id=job_id).first()
            if j:
                j.progress = min(100, max(0, int(progress)))
                if message:
                    j.message = message
                j.updated_at = datetime.utcnow()
                sess.commit()
        retry_on_lock(_do, cleanup=lambda: sess.rollback())
    finally:
        sess.close()


def enqueue(job_type: str, website_id: Optional[int], func: Callable, *args, **kwargs) -> str:
    job_id = f"JOB-{uuid.uuid4().hex[:10].upper()}"
    sess = new_session()
    try:
        j = BackgroundJob(
            job_id=job_id, job_type=job_type, website_id=website_id,
            status="queued", progress=0,
        )
        sess.add(j)
        sess.commit()
    finally:
        sess.close()

    def runner():
        try:
            _record_start(job_id)
            event_manager = get_event_manager()
            event_manager.emit(
                job_id=job_id, event_type="job_started",
                message=f"Job {job_type} started",
                severity="info",
                metadata={"job_type": job_type},
                website_id=website_id,
            )
            kwargs["job_id"] = job_id
            kwargs["on_progress"] = lambda p, m="": _record_progress(job_id, p, m)
            result = func(*args, **kwargs)

            if isinstance(result, dict) and not result.get("ok", True):
                _record_finish(job_id, False, result, result.get("message", "Job returned failure"))
                event_manager.emit(
                    job_id=job_id, event_type="job_failed",
                    message=f"Job {job_type} failed: {result.get('message', 'unknown')}",
                    severity="error",
                    website_id=website_id,
                )
            else:
                _record_finish(job_id, True, result if isinstance(result, dict) else {"raw": str(result)})
                event_manager.emit(
                    job_id=job_id, event_type="job_completed",
                    message=f"Job {job_type} completed",
                    severity="success",
                    metadata={"result": result if isinstance(result, dict) else {}},
                    website_id=website_id,
                )
        except Exception as e:
            tb = traceback.format_exc()
            _record_finish(job_id, False, {}, f"{e}\n{tb[-500:]}")
            event_manager.emit(
                job_id=job_id, event_type="job_failed",
                message=f"Job failed: {e}",
                severity="error",
                website_id=website_id,
            )

    t = threading.Thread(target=runner, daemon=True)
    t.start()
    return job_id


def get_job(job_id: str):
    sess, owns = _read_session()
    try:
        job = sess.query(BackgroundJob).filter_by(job_id=job_id).first()
        return _job_to_dict(job) if job else None
    finally:
        if owns:
            sess.close()
            SessionLocal.remove()


def list_jobs(website_id: Optional[int] = None, limit: int = 50) -> list:
    sess, owns = _read_session()
    try:
        q = sess.query(BackgroundJob).order_by(BackgroundJob.created_at.desc())
        if website_id is not None:
            q = q.filter_by(website_id=website_id)
        return [_job_to_dict(j) for j in q.limit(limit).all()]
    finally:
        if owns:
            sess.close()
            SessionLocal.remove()


def control_job(job_id: str, signal: str) -> bool:
    """Send control signal to a job. signal: 'pause', 'resume', 'stop'."""
    event_manager = get_event_manager()
    event_manager.send_control_signal(job_id, signal)
    return True
