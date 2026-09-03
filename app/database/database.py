"""Database setup with SQLAlchemy."""
from __future__ import annotations
import time
from sqlalchemy import create_engine, event
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import declarative_base, sessionmaker, scoped_session
from flask import g
from ..config import Config

_IS_SQLITE = "sqlite" in Config.DATABASE_URL

engine = create_engine(
    Config.DATABASE_URL,
    future=True,
    echo=False,
    connect_args={
        "check_same_thread": False,
        "timeout": 30.0,
    } if _IS_SQLITE else {},
)


if _IS_SQLITE:
    @event.listens_for(engine, "connect")
    def _set_sqlite_pragmas(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=30000")
        cursor.close()

SessionLocal = scoped_session(
    sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
)

_session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)

Base = declarative_base()


def new_session():
    """Create a *standalone* (non-scoped) SQLAlchemy session.

    Unlike ``SessionLocal`` (a ``scoped_session``), sessions returned by this
    factory are **not** tracked in the thread-local scope.  Closing one of them
    therefore never expires or detaches objects that belong to a different
    session the same thread is using — e.g. the request/session or the
    orchestrator background job.  This prevents
    ``DetachedInstanceError`` when a helper function is called *from within*
    an outer session's scope.
    """
    return _session_factory()


def retry_on_lock(func, retries=5, delay=0.5, cleanup=None):
    """Retry ``func`` when SQLite raises 'database is locked'.

    SQLite serialises writes; when the background job thread writes progress
    updates concurrently with the orchestrator's session commit, the second
    writer gets ``OperationalError(locked)``.  WAL mode + a busy timeout handle
    most cases, but a small retry loop covers contention spikes.

    ``cleanup`` is called (if provided) after each failed attempt — typically
    ``sess.rollback()`` to reset a session that failed ``commit()``.
    """
    last_exc = None
    for attempt in range(retries):
        try:
            return func()
        except OperationalError as exc:
            last_exc = exc
            if "locked" not in str(exc).lower():
                raise
            if cleanup:
                cleanup()
            time.sleep(delay * (attempt + 1))
    raise last_exc


def log_audit(actor: str, action: str, target: str = "", details: dict = None):
    """Record an audit-log entry using an independent session.

    Safe to call from any thread (request handler, background job, etc.) — the
    standalone session never interferes with a parent session.
    """
    from .models import AuditLog
    sess = new_session()
    try:
        def _do():
            sess.add(AuditLog(
                actor=actor,
                action=action,
                target=target,
                details_json=details or {},
            ))
            sess.commit()
        retry_on_lock(_do, cleanup=lambda: sess.rollback())
    finally:
        sess.close()


def init_db():
    # Import all models so they register
    from . import models  # noqa: F401
    Base.metadata.create_all(bind=engine)


def filter_model_fields(model, data: dict) -> dict:
    """Filter a dictionary to only include valid mapped columns for the given SQLAlchemy model.

    Logs unexpected fields so they can be caught during development.
    Returns a new dict containing only valid column names.
    """
    valid_fields = {column.name for column in model.__table__.columns}
    filtered = {}
    unexpected = []
    for key, value in data.items():
        if key in valid_fields:
            filtered[key] = value
        else:
            unexpected.append(key)
    if unexpected:
        import logging
        logging.getLogger(__name__).warning(
            "filter_model_fields: skipped unexpected fields for %s: %s",
            model.__name__, ", ".join(sorted(unexpected))
        )
    return filtered


def get_session():
    if "db_session" not in g:
        g.db_session = SessionLocal()
    return g.db_session


def close_session(exc=None):
    session = g.pop("db_session", None)
    if session is not None:
        try:
            session.close()
        except Exception:
            pass
    SessionLocal.remove()