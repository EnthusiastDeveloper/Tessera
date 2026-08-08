"""Shared fixtures for data-access-layer integration tests. See architecture-plan §8."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from sqlalchemy.orm import Session, sessionmaker

from app.db.base import Base, generate_id
from app.db.repositories import UserSettingsRepository
from app.db.schemas import UserSettings
from app.db.session import build_engine
from app.settings.service import DEFAULT_ACTIVE_HOURS, DEFAULT_DAILY_TIME_BUDGET
from tests.fixtures.jobs import RecordingJobScheduler


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


@pytest.fixture
def settings(db_session: Session) -> UserSettings:
    """A default `UserSettings` row (Stage 4 shape) - every Stage 5 service function
    requires one to already exist, matching app startup's own bootstrap.
    """
    created = UserSettingsRepository(db_session).create(
        UserSettings(
            id=generate_id(),
            timezone="America/New_York",
            active_hours=dict(DEFAULT_ACTIVE_HOURS),
            blackout_dates=(),
            daily_time_budget_minutes=dict(DEFAULT_DAILY_TIME_BUDGET),
            budget_enforcement="soft",
            first_day_of_week="monday",
        )
    )
    db_session.commit()
    return created


@pytest.fixture
def jobs() -> RecordingJobScheduler:
    return RecordingJobScheduler()
