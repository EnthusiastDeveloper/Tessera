"""SQLAlchemy engine and session factory. See architecture-plan §1 (SQLite/SQLAlchemy).

Engine/session-factory construction is lazy (`lru_cache`, not a module-level global) so
importing this module never touches the filesystem - tests build their own in-memory
engine via `build_engine()` instead of going through the configured `DATABASE_PATH`.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
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


def _enable_foreign_keys(engine: Engine) -> None:
    """SQLite disables FK enforcement per connection by default - turn it on.

    Without this, the dependency join table's `ondelete="CASCADE"` (design doc §3.3) and
    every other FK constraint in the schema would silently no-op.
    """

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragma(dbapi_connection: Any, connection_record: Any) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


def build_engine(database_url: str) -> Engine:
    """Create an engine with SQLite foreign-key enforcement turned on."""
    engine = create_engine(database_url, connect_args={"check_same_thread": False})
    _enable_foreign_keys(engine)
    return engine


@lru_cache
def get_session_factory() -> sessionmaker[Session]:
    """Process-wide session factory, bound to the configured `DATABASE_PATH`."""
    engine = build_engine(sqlite_url(get_settings().database_path))
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db() -> Iterator[Session]:
    """FastAPI dependency: yield a request-scoped session, always closed afterward."""
    session = get_session_factory()()
    try:
        yield session
    finally:
        session.close()
