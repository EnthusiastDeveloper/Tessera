"""Repository CRUD tests for `ExternalCalendarConnection`. See design doc §3.5."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.db.repositories import ExternalCalendarConnectionRepository
from tests.fixtures.db_entities import make_external_calendar_connection


def test_create_and_get_round_trip(db_session: Session) -> None:
    repo = ExternalCalendarConnectionRepository(db_session)
    connection = make_external_calendar_connection(provider="outlook")
    created = repo.create(connection)
    db_session.commit()
    db_session.expire_all()

    fetched = repo.get(connection.id)
    assert fetched == created


def test_list_enabled_only_filters(db_session: Session) -> None:
    repo = ExternalCalendarConnectionRepository(db_session)
    enabled = repo.create(make_external_calendar_connection(enabled=True))
    repo.create(make_external_calendar_connection(enabled=False))
    db_session.commit()

    assert {c.id for c in repo.list(enabled_only=True)} == {enabled.id}
    assert len(repo.list()) == 2


def test_update_persists_changes(db_session: Session) -> None:
    repo = ExternalCalendarConnectionRepository(db_session)
    created = repo.create(make_external_calendar_connection(enabled=True))
    db_session.commit()

    updated = repo.update(created.model_copy(update={"enabled": False}))
    db_session.commit()

    assert updated.enabled is False


def test_delete_removes_row(db_session: Session) -> None:
    repo = ExternalCalendarConnectionRepository(db_session)
    created = repo.create(make_external_calendar_connection())
    db_session.commit()

    repo.delete(created.id)
    db_session.commit()

    assert repo.get(created.id) is None
