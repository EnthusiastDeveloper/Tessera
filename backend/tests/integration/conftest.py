"""Shared fixtures for data-access-layer integration tests. See architecture-plan §8."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from sqlalchemy.orm import Session, sessionmaker

from app.db.base import Base
from app.db.session import build_engine


@pytest.fixture
def db_session() -> Iterator[Session]:
    """A fresh in-memory SQLite session per test, schema created straight from `Base.metadata`.

    Bypasses Alembic on purpose - migration correctness has its own test
    (`test_migrations.py`); every other test here just needs a schema that matches the
    ORM models.
    """
    engine = build_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    session = session_factory()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()
