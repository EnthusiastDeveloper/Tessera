"""Repository CRUD tests for `UserSettings`. See design doc §3.7."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.db.repositories import UserSettingsRepository
from app.db.schemas import BlackoutDate
from tests.fixtures.db_entities import make_user_settings


def test_create_and_get_round_trip(db_session: Session) -> None:
    repo = UserSettingsRepository(db_session)
    settings = make_user_settings(blackout_dates=(BlackoutDate(start="2026-12-24", end="2026-12-26", label="Holidays"),))
    created = repo.create(settings)
    db_session.commit()
    db_session.expire_all()

    assert repo.get() == created


def test_get_returns_none_when_no_row_exists(db_session: Session) -> None:
    assert UserSettingsRepository(db_session).get() is None


def test_active_hours_per_day_null_means_excluded(db_session: Session) -> None:
    repo = UserSettingsRepository(db_session)
    settings = make_user_settings(active_hours={**make_user_settings().active_hours, "sunday": None})
    repo.create(settings)
    db_session.commit()
    db_session.expire_all()

    fetched = repo.get()
    assert fetched is not None
    assert fetched.active_hours["sunday"] is None


def test_update_persists_timezone_change(db_session: Session) -> None:
    repo = UserSettingsRepository(db_session)
    created = repo.create(make_user_settings(timezone="America/New_York"))
    db_session.commit()

    updated = repo.update(created.model_copy(update={"timezone": "Europe/London"}))
    db_session.commit()

    assert updated.timezone == "Europe/London"
