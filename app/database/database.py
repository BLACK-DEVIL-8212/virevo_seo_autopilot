"""Database setup with SQLAlchemy.

Provides database connection management, session handling, and utility functions
for the AI SEO Autopilot platform. Supports SQLite (with WAL mode) and other
SQLAlchemy-compatible databases.
"""
from __future__ import annotations
import time
import logging
from contextlib import contextmanager
from typing import Dict, Any, Optional, Callable, Generator, Type, List

from sqlalchemy import create_engine, event, inspect
from sqlalchemy.exc import OperationalError, SQLAlchemyError
from sqlalchemy.orm import sessionmaker, scoped_session, Session
from flask import g, has_request_context

from .models import Base

# Setup logging
logger = logging.getLogger(__name__)


# ============================================================================
# CONFIGURATION
# ============================================================================

class Config:
    """Configuration for database connection."""
    DATABASE_URL = "sqlite:///./seo_autopilot.db"
    SQLALCHEMY_ECHO = False
    SQLALCHEMY_POOL_SIZE = 5
    SQLALCHEMY_MAX_OVERFLOW = 10
    SQLALCHEMY_POOL_TIMEOUT = 30
    SQLALCHEMY_POOL_RECYCLE = 1800


# ============================================================================
# DATABASE ENGINE SETUP
# ============================================================================

_IS_SQLITE = "sqlite" in Config.DATABASE_URL

# Configure engine with appropriate settings
engine_kwargs = {
    "future": True,
    "echo": Config.SQLALCHEMY_ECHO,
    "pool_pre_ping": True,
}

if _IS_SQLITE:
    engine_kwargs["connect_args"] = {
        "check_same_thread": False,
        "timeout": 30.0,
    }
else:
    engine_kwargs.update({
        "pool_size": Config.SQLALCHEMY_POOL_SIZE,
        "max_overflow": Config.SQLALCHEMY_MAX_OVERFLOW,
        "pool_timeout": Config.SQLALCHEMY_POOL_TIMEOUT,
        "pool_recycle": Config.SQLALCHEMY_POOL_RECYCLE,
    })

engine = create_engine(
    Config.DATABASE_URL,
    **engine_kwargs
)


# ============================================================================
# SQLITE PRAGMA SETUP
# ============================================================================

if _IS_SQLITE:
    @event.listens_for(engine, "connect")
    def _set_sqlite_pragmas(dbapi_connection, connection_record):
        """Set SQLite pragmas for better performance and concurrency."""
        cursor = dbapi_connection.cursor()
        try:
            # Enable Write-Ahead Logging for better concurrency
            cursor.execute("PRAGMA journal_mode=WAL")
            # Set busy timeout to avoid immediate lock errors
            cursor.execute("PRAGMA busy_timeout=30000")
            # Enable foreign key constraints
            cursor.execute("PRAGMA foreign_keys=ON")
            # Enable memory-mapped I/O for performance
            cursor.execute("PRAGMA mmap_size=268435456")
            # Set cache size
            cursor.execute("PRAGMA cache_size=-2000000")
            # Enable synchronous mode (safe)
            cursor.execute("PRAGMA synchronous=NORMAL")
            # Enable temp store in memory
            cursor.execute("PRAGMA temp_store=MEMORY")
        except Exception as e:
            logger.warning(f"Failed to set SQLite pragmas: {e}")
        finally:
            cursor.close()


# ============================================================================
# SESSION FACTORIES
# ============================================================================

# Scoped session for Flask request context
SessionLocal = scoped_session(
    sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
        future=True,
        expire_on_commit=False
    )
)

# Standalone session factory for background tasks
_session_factory = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
    future=True,
    expire_on_commit=False
)

# Base class for declarative models


# ============================================================================
# SESSION MANAGEMENT
# ============================================================================

def new_session() -> Session:
    """Create a standalone (non-scoped) SQLAlchemy session.

    Unlike SessionLocal (a scoped_session), sessions returned by this
    factory are NOT tracked in the thread-local scope. Closing one of them
    therefore never expires or detaches objects that belong to a different
    session the same thread is using.

    Returns:
        SQLAlchemy Session object
    """
    return _session_factory()


@contextmanager
def session_scope() -> Generator[Session, None, None]:
    """Provide a transactional scope around a series of operations.

    This context manager handles session lifecycle automatically.
    Commits on success, rolls back on exception.

    Yields:
        SQLAlchemy Session
    """
    session = new_session()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


@contextmanager
def scoped_session_scope() -> Generator[Session, None, None]:
    """Provide a transactional scope using the scoped session.

    For use within Flask request context. Commits on success,
    rolls back on exception.

    Yields:
        SQLAlchemy Session
    """
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


# ============================================================================
# RETRY MECHANISM
# ============================================================================

def retry_on_lock(
    func: Callable,
    retries: int = 5,
    delay: float = 0.5,
    max_delay: float = 5.0,
    cleanup: Optional[Callable] = None,
    backoff_factor: float = 1.5
) -> Any:
    """Retry func when SQLite raises 'database is locked'.

    SQLite serialises writes; when multiple threads write concurrently,
    the second writer gets OperationalError(locked). WAL mode + busy timeout
    handle most cases, but a retry loop covers contention spikes.

    Args:
        func: Function to execute with retry
        retries: Maximum number of retry attempts
        delay: Initial delay between retries in seconds
        max_delay: Maximum delay between retries
        cleanup: Called after each failed attempt (typically session.rollback())
        backoff_factor: Multiplier for exponential backoff

    Returns:
        Result of func

    Raises:
        OperationalError: If all retries fail
    """
    last_exc = None
    current_delay = delay
    
    for attempt in range(retries + 1):
        try:
            return func()
        except OperationalError as exc:
            last_exc = exc
            error_msg = str(exc).lower()
            
            # Only retry on lock errors
            if "locked" not in error_msg and "busy" not in error_msg:
                raise
            
            if attempt >= retries:
                break
            
            # Clean up if provided
            if cleanup:
                try:
                    cleanup()
                except Exception as e:
                    logger.warning(f"Cleanup during retry failed: {e}")
            
            # Exponential backoff with jitter
            sleep_time = min(current_delay, max_delay)
            logger.warning(
                f"Database locked, retrying {attempt + 1}/{retries} "
                f"after {sleep_time:.2f}s: {exc}"
            )
            time.sleep(sleep_time)
            current_delay *= backoff_factor
            
        except Exception as exc:
            # Don't retry on other exceptions
            raise
    
    raise last_exc


@contextmanager
def retryable_transaction(
    session: Session,
    retries: int = 3,
    delay: float = 0.3
) -> Generator[Session, None, None]:
    """Context manager for retryable transactions.

    Args:
        session: SQLAlchemy session
        retries: Maximum retry attempts
        delay: Initial delay between retries

    Yields:
        SQLAlchemy Session
    """
    def do_commit():
        session.commit()
    
    def do_rollback():
        session.rollback()
    
    try:
        yield session
        retry_on_lock(do_commit, retries=retries, delay=delay, cleanup=do_rollback)
    except Exception:
        session.rollback()
        raise


# ============================================================================
# AUDIT LOGGING
# ============================================================================

def log_audit(
    actor: str,
    action: str,
    target: str = "",
    details: Optional[Dict[str, Any]] = None,
    use_scoped: bool = False
) -> None:
    """Record an audit-log entry using an independent session.

    Safe to call from any thread (request handler, background job, etc.).
    The standalone session never interferes with a parent session.

    Args:
        actor: User or system actor
        action: Action performed
        target: Target entity
        details: Additional details
        use_scoped: Whether to use scoped session (for request context)
    """
    from .models import AuditLog
    
    details = details or {}
    
    def _do():
        if use_scoped and has_request_context():
            session = SessionLocal()
        else:
            session = new_session()
        
        try:
            audit_entry = AuditLog(
                actor=actor,
                action=action,
                target=target,
                details_json=details,
            )
            session.add(audit_entry)
            session.commit()
        except Exception as e:
            session.rollback()
            logger.error(f"Failed to log audit: {e}")
            raise
        finally:
            session.close()
    
    try:
        retry_on_lock(_do, cleanup=lambda: None)
    except Exception as e:
        # Don't let audit logging failures break the main flow
        logger.error(f"Audit log failed after retries: {e}")


# ============================================================================
# DATABASE INITIALIZATION
# ============================================================================

def init_db() -> None:
    """Initialize database with all tables.

    Imports all models so they register with Base metadata,
    then creates all tables.
    """
    try:
        # Import all models to register them
        from . import models  # noqa: F401
        
        # Create tables
        Base.metadata.create_all(bind=engine)
        logger.info("Database tables created successfully")
    except Exception as e:
        logger.error(f"Failed to initialize database: {e}")
        raise


def reset_db(drop_first: bool = False) -> None:
    """Reset database by dropping and recreating tables.

    Args:
        drop_first: If True, drop all tables before creating
    """
    try:
        from . import models  # noqa: F401
        
        if drop_first:
            Base.metadata.drop_all(bind=engine)
            logger.info("Database tables dropped")
        
        Base.metadata.create_all(bind=engine)
        logger.info("Database tables created")
    except Exception as e:
        logger.error(f"Failed to reset database: {e}")
        raise


def get_table_names() -> List[str]:
    """Get list of all table names in the database."""
    inspector = inspect(engine)
    return inspector.get_table_names()


# ============================================================================
# UTILITY FUNCTIONS
# ============================================================================

def filter_model_fields(model: Type, data: Dict[str, Any]) -> Dict[str, Any]:
    """Filter a dictionary to only include valid mapped columns for the given model.

    Args:
        model: SQLAlchemy model class
        data: Dictionary of data to filter

    Returns:
        Filtered dictionary containing only valid column names

    Raises:
        ValueError: If no valid fields found
    """
    if not hasattr(model, '__table__'):
        raise ValueError(f"{model.__name__} is not a valid SQLAlchemy model")
    
    valid_fields = {column.name for column in model.__table__.columns}
    filtered = {}
    unexpected = []
    
    for key, value in data.items():
        if key in valid_fields:
            filtered[key] = value
        else:
            unexpected.append(key)
    
    if unexpected:
        logger.warning(
            "filter_model_fields: skipped unexpected fields for %s: %s",
            model.__name__,
            ", ".join(sorted(unexpected))
        )
    
    if not filtered:
        raise ValueError(f"No valid fields found for model {model.__name__}")
    
    return filtered


def get_model_fields(model: Type) -> List[str]:
    """Get list of column names for a model.

    Args:
        model: SQLAlchemy model class

    Returns:
        List of column names
    """
    if not hasattr(model, '__table__'):
        raise ValueError(f"{model.__name__} is not a valid SQLAlchemy model")
    
    return [column.name for column in model.__table__.columns]


def get_primary_key(model: Type) -> Optional[str]:
    """Get the primary key column name for a model.

    Args:
        model: SQLAlchemy model class

    Returns:
        Primary key column name or None
    """
    if not hasattr(model, '__table__'):
        raise ValueError(f"{model.__name__} is not a valid SQLAlchemy model")
    
    for column in model.__table__.columns:
        if column.primary_key:
            return column.name
    return None


# ============================================================================
# FLASK INTEGRATION
# ============================================================================

def get_session() -> Session:
    """Get or create a scoped session for Flask request context.

    Returns:
        SQLAlchemy Session
    """
    if not has_request_context():
        raise RuntimeError("No Flask request context available")
    
    if "db_session" not in g:
        g.db_session = SessionLocal()
    return g.db_session


def close_session(exc: Optional[Exception] = None) -> None:
    """Close the Flask request-scoped session.

    Args:
        exc: Optional exception that triggered the close
    """
    if has_request_context():
        session = g.pop("db_session", None)
        if session is not None:
            try:
                session.close()
            except Exception as e:
                logger.warning(f"Error closing session: {e}")
        
        # Remove scoped session
        try:
            SessionLocal.remove()
        except Exception:
            pass


def commit_session() -> None:
    """Commit the Flask request-scoped session with retry."""
    if not has_request_context():
        raise RuntimeError("No Flask request context available")
    
    session = g.get("db_session")
    if session is None:
        raise RuntimeError("No session in request context")
    
    def _do():
        session.commit()
    
    def _rollback():
        session.rollback()
    
    try:
        retry_on_lock(_do, cleanup=_rollback)
    except Exception:
        session.rollback()
        raise


# ============================================================================
# BULK OPERATIONS
# ============================================================================

def bulk_insert(model: Type, items: List[Dict[str, Any]], chunk_size: int = 1000) -> int:
    """Bulk insert records efficiently.

    Args:
        model: SQLAlchemy model class
        items: List of dictionaries to insert
        chunk_size: Number of items per chunk

    Returns:
        Number of records inserted
    """
    if not items:
        return 0
    
    session = new_session()
    try:
        total = 0
        for i in range(0, len(items), chunk_size):
            chunk = items[i:i + chunk_size]
            session.bulk_insert_mappings(model, chunk)
            session.commit()
            total += len(chunk)
        return total
    except Exception as e:
        session.rollback()
        raise
    finally:
        session.close()


def bulk_update(model: Type, items: List[Dict[str, Any]], key_field: str, chunk_size: int = 1000) -> int:
    """Bulk update records efficiently.

    Args:
        model: SQLAlchemy model class
        items: List of dictionaries with key_field and update fields
        key_field: Field name used as primary key for matching
        chunk_size: Number of items per chunk

    Returns:
        Number of records updated
    """
    if not items:
        return 0
    
    session = new_session()
    try:
        total = 0
        for i in range(0, len(items), chunk_size):
            chunk = items[i:i + chunk_size]
            session.bulk_update_mappings(model, chunk)
            session.commit()
            total += len(chunk)
        return total
    except Exception as e:
        session.rollback()
        raise
    finally:
        session.close()
