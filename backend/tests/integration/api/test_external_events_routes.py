"""HTTP-level tests for `GET /api/v1/external-events` (added Stage 9d - see design doc
§3.11, §7, §8.1 screen 2). Business logic (the transparent/all-day filter split) is
covered at the service layer (tests/integration/calendar_sync/test_service.py); this file
proves the route wires up: auth guard and response shape.

No create endpoint exists for `ExternalEvent` (POC is read-only sync, populated only by
`sync_connection`'s poll) - seeded directly via repositories in the same running app's DB,
matching the pattern `tests/integration/api/test_backend_e2e.py` already uses for
setup states unreachable through the HTTP API alone.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.auth.setup_token import setup_token_store
from app.db.repositories import ExternalCalendarConnectionRepository, ExternalEventRepository
from app.db.session import session_scope
from tests.fixtures.db_entities import make_external_calendar_connection, make_external_event

VALID_PASSWORD = "correcthorsebatterystaple"


def _complete_setup(client: TestClient) -> None:
    token = setup_token_store._token  # test-only introspection, matches other API test files
    assert token is not None
    client.post("/api/v1/auth/setup", json={"token": token, "password": VALID_PASSWORD})


def _login(client: TestClient) -> None:
    _complete_setup(client)
    client.post("/api/v1/auth/login", json={"username": "admin", "password": VALID_PASSWORD})


def _seed_connection() -> str:
    with session_scope() as db:
        connection = ExternalCalendarConnectionRepository(db).create(make_external_calendar_connection())
        return connection.id


class TestListExternalEvents:
    def test_requires_authentication(self, app_client: TestClient) -> None:
        _complete_setup(app_client)
        assert app_client.get("/api/v1/external-events").status_code == 401

    def test_returns_empty_list_when_nothing_cached(self, app_client: TestClient) -> None:
        _login(app_client)
        response = app_client.get("/api/v1/external-events")
        assert response.status_code == 200, response.text
        assert response.json() == []

    def test_excludes_transparent_but_includes_opaque_and_all_day(self, app_client: TestClient) -> None:
        _login(app_client)
        connection_id = _seed_connection()
        with session_scope() as db:
            repo = ExternalEventRepository(db)
            repo.upsert(
                make_external_event(
                    connection_id=connection_id,
                    provider_event_id="opaque-timed",
                    title="Dentist",
                    is_transparent=False,
                    is_all_day=False,
                )
            )
            repo.upsert(
                make_external_event(
                    connection_id=connection_id,
                    provider_event_id="free-event",
                    title="Optional workshop",
                    is_transparent=True,
                    is_all_day=False,
                )
            )
            repo.upsert(
                make_external_event(
                    connection_id=connection_id,
                    provider_event_id="all-day",
                    title="Conference",
                    is_transparent=False,
                    is_all_day=True,
                )
            )

        response = app_client.get("/api/v1/external-events")
        assert response.status_code == 200, response.text
        titles_and_all_day = {(e["title"], e["is_all_day"]) for e in response.json()}
        assert titles_and_all_day == {("Dentist", False), ("Conference", True)}
        assert "Optional workshop" not in {e["title"] for e in response.json()}

    def test_excludes_events_from_disabled_connections(self, app_client: TestClient) -> None:
        _login(app_client)
        with session_scope() as db:
            disabled = ExternalCalendarConnectionRepository(db).create(make_external_calendar_connection(enabled=False))
            ExternalEventRepository(db).upsert(
                make_external_event(connection_id=disabled.id, provider_event_id="evt-1", title="Should not appear")
            )

        response = app_client.get("/api/v1/external-events")
        assert response.status_code == 200, response.text
        assert response.json() == []
