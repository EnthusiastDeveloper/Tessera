"""Repository CRUD tests for `ExternalEvent`. See design doc §3.11 (upsert), §3.12 (retention/soft delete)."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.db.base import utcnow
from app.db.repositories import ExternalCalendarConnectionRepository, ExternalEventRepository
from tests.fixtures.db_entities import make_external_calendar_connection, make_external_event


def _persisted_connection(db_session: Session) -> str:
    connection = ExternalCalendarConnectionRepository(db_session).create(make_external_calendar_connection())
    db_session.commit()
    return connection.id


def test_upsert_inserts_new_event(db_session: Session) -> None:
    connection_id = _persisted_connection(db_session)
    repo = ExternalEventRepository(db_session)
    event = make_external_event(connection_id=connection_id, provider_event_id="evt-123", title="Dentist")

    created = repo.upsert(event)
    db_session.commit()

    fetched = repo.get_by_provider_event_id(connection_id, "evt-123")
    assert fetched == created


def test_upsert_updates_existing_event_in_place(db_session: Session) -> None:
    """§3.11: `(connection_id, provider_event_id)` uniqueness is what makes the sync diff a plain upsert."""
    connection_id = _persisted_connection(db_session)
    repo = ExternalEventRepository(db_session)
    original = repo.upsert(make_external_event(connection_id=connection_id, provider_event_id="evt-1", title="Old"))
    db_session.commit()

    renamed = repo.upsert(make_external_event(connection_id=connection_id, provider_event_id="evt-1", title="New Title"))
    db_session.commit()

    assert renamed.id == original.id  # same row, not a duplicate
    assert renamed.title == "New Title"
    assert len(repo.list_active_for_connection(connection_id)) == 1


def test_list_active_for_connection_excludes_soft_deleted(db_session: Session) -> None:
    connection_id = _persisted_connection(db_session)
    repo = ExternalEventRepository(db_session)
    active = repo.upsert(make_external_event(connection_id=connection_id, provider_event_id="evt-active"))
    repo.upsert(make_external_event(connection_id=connection_id, provider_event_id="evt-removed", deleted_at=utcnow()))
    db_session.commit()

    assert {e.id for e in repo.list_active_for_connection(connection_id)} == {active.id}


def test_get_by_provider_event_id_returns_none_when_absent(db_session: Session) -> None:
    connection_id = _persisted_connection(db_session)
    repo = ExternalEventRepository(db_session)
    assert repo.get_by_provider_event_id(connection_id, "does-not-exist") is None
