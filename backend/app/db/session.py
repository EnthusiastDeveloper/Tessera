"""SQLAlchemy engine and session factory. See architecture-plan §1 (SQLite/SQLAlchemy).

Engine/session-factory construction is lazy (`lru_cache`, not a module-level global) so
importing this module never touches the filesystem - tests build their own in-memory
engine via `build_engine()` instead of going through the configured `DATABASE_PATH`.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache
from typing import Any

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings


def sqlite_url(database_path: str) -> str:
    """Build a SQLite connection URL from `DATABASE_PATH`, creating its parent directory if needed.

    Also used directly by `alembic/env.py`, which needs the same URL construction outside
    of a running app process.
    """
    parent = os.path.dirname(database_path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    return f"sqlite:///{database_path}"


def jobs_database_path(database_path: str) -> str:
    """Where Stage 6's APScheduler job store lives - a **separate** SQLite file next to
    the app's own, not the same one. architecture-plan flags "one SQLite file with the
    app's own data, inside a single process - should be fine (WAL mode), but verify
    explicitly" as an open risk; verifying it here (empirically, not by inspection) found
    that the assumption does *not* hold for this codebase's own job-wiring design.
    architecture-plan §4.1 requires every mutation to co-locate its DB write and job call
    in one synchronous method - so a job-store write routinely happens on a second
    connection while the request's own transaction is still open on the first. WAL mode
    only relaxes reader-vs-writer contention, not writer-vs-writer, and a `busy_timeout`
    cannot fix a genuine circular wait (the request's transaction won't commit until the
    handler returns; the job-store write won't return until it can acquire the write
    lock the still-open transaction holds) - it only turns an instant failure into one
    that hangs for the full timeout. Two independent SQLite files means two independent
    lock domains, which is what actually removes the contention, verified by direct
    reproduction during Stage 6 (see the PR description for the standalone repro).
    """
    root, ext = os.path.splitext(database_path)
    return f"{root}.jobs{ext or '.db'}"


def _configure_sqlite_pragmas(engine: Engine) -> None:
    """SQLite disables FK enforcement per connection by default - turn it on. Also enables
    WAL (write-ahead-log) journal mode and a generous `busy_timeout`, so that transient
    (not structural - see `jobs_database_path`) writer contention waits instead of
    erroring immediately. (`:memory:` test databases can't use WAL and SQLite silently
    falls back for them - harmless.)

    Without the FK pragma, the dependency join table's `ondelete="CASCADE"` (design doc
    §3.3) and every other FK constraint in the schema would silently no-op.
    """

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragma(dbapi_connection: Any, connection_record: Any) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.close()


def build_engine(database_url: str) -> Engine:
    """Create an engine with SQLite foreign-key enforcement and WAL mode turned on."""
    engine = create_engine(database_url, connect_args={"check_same_thread": False})
    _configure_sqlite_pragmas(engine)
    return engine


@lru_cache
def get_engine() -> Engine:
    """Process-wide engine for the configured `DATABASE_PATH` - the app's own ORM data
    only. Stage 6's `APSchedulerJobScheduler` uses a separate engine/file - see
    `jobs_database_path`.
    """
    return build_engine(sqlite_url(get_settings().database_path))


@lru_cache
def get_jobs_engine() -> Engine:
    """Process-wide engine for Stage 6's APScheduler job store - see `jobs_database_path`
    for why this is deliberately not `get_engine()`.
    """
    return build_engine(sqlite_url(jobs_database_path(get_settings().database_path)))


@lru_cache
def get_session_factory() -> sessionmaker[Session]:
    """Process-wide session factory, bound to the configured `DATABASE_PATH`."""
    return sessionmaker(bind=get_engine(), autoflush=False, expire_on_commit=False)


@contextmanager
def session_scope() -> Iterator[Session]:
    """A session that commits on clean exit, rolls back on exception, and always closes.

    The one place this transaction-boundary logic lives - the FastAPI `get_db`
    dependency below and one-off work outside a request (e.g. main.py's startup lifespan)
    both go through this rather than each reimplementing commit/rollback/close.
    """
    session = get_session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_db() -> Iterator[Session]:
    """FastAPI dependency: a request-scoped session with `session_scope()`'s semantics."""
    with session_scope() as session:
        yield session
