"""Error-envelope contract tests: one per distinct code (architecture-plan §3's table).
Every response is asserted to carry the consistent `{code, message}` shape at the
documented HTTP status - this is a shape-consistency check across the exposed API
surface, distinct from the business-logic tests that already exercise each code's
triggering condition at the service layer.

`cycle_detected` has no HTTP-reachable trigger in the current API surface - dependencies
are only ever set at creation, and a brand-new node cannot itself close a cycle through
creation alone (see `tests/integration/task_templates/test_service.py`'s
`test_cycle_detected_is_rejected`, which proves the mechanism directly against the
service-layer helper `create_template` shares). Not a gap introduced by this stage - no
dependency-*editing* endpoint exists to reach it through, and building one is out of this
stage's "no new business logic" scope.
"""

from __future__ import annotations

import httpx
from fastapi.testclient import TestClient

from app.auth.setup_token import setup_token_store

VALID_PASSWORD = "correcthorsebatterystaple"


def _login(client: TestClient) -> None:
    token = setup_token_store._token  # test-only introspection, see test_auth_routes.py
    assert token is not None
    client.post("/api/v1/auth/setup", json={"token": token, "password": VALID_PASSWORD})
    client.post("/api/v1/auth/login", json={"username": "admin", "password": VALID_PASSWORD})


def _assert_envelope(response: httpx.Response, *, status: int, code: str) -> None:
    assert response.status_code == status, response.text
    body = response.json()
    assert body["code"] == code
    assert isinstance(body["message"], str) and body["message"]


class TestCreationConflict:
    def test_returns_409_with_the_conflict_code(self, app_client: TestClient) -> None:
        _login(app_client)
        first = {
            "name": "Team sync",
            "type": "fixed",
            "fixed_time_of_day": "18:00",
            "recurrence": {"pattern": "one_time", "anchor": "calendar"},
            "priority": "medium",
            "estimated_duration_minutes": 60,
        }
        app_client.post("/api/v1/task-templates", json=first)

        colliding = dict(first, name="Another meeting")
        response = app_client.post("/api/v1/task-templates", json=colliding)
        _assert_envelope(response, status=409, code="creation_conflict")


class TestInfeasibleDuration:
    def test_returns_422_with_the_infeasible_duration_code(self, app_client: TestClient) -> None:
        _login(app_client)
        payload = {
            "name": "Impossible task",
            "type": "flexible",
            "recurrence": {"pattern": "one_time", "anchor": "calendar"},
            "priority": "medium",
            "estimated_duration_minutes": 24 * 60,  # longer than any day's active-hours window
            "deadline_offset_minutes": 60,
        }
        response = app_client.post("/api/v1/task-templates", json=payload)
        _assert_envelope(response, status=422, code="infeasible_duration")


class TestInvalidRecurrenceAnchor:
    def test_returns_422_with_the_invalid_recurrence_anchor_code(self, app_client: TestClient) -> None:
        _login(app_client)
        payload = {
            "name": "Bad anchor",
            "type": "fixed",
            "fixed_time_of_day": "09:00",
            "recurrence": {"pattern": "daily", "interval": 1, "anchor": "completion"},
            "priority": "medium",
            "estimated_duration_minutes": 30,
        }
        response = app_client.post("/api/v1/task-templates", json=payload)
        _assert_envelope(response, status=422, code="invalid_recurrence_anchor")


class TestNotFound:
    def test_returns_404_with_the_not_found_code(self, app_client: TestClient) -> None:
        _login(app_client)
        response = app_client.delete("/api/v1/task-templates/does-not-exist")
        _assert_envelope(response, status=404, code="not_found")


class TestScopeRequired:
    def test_returns_422_with_the_scope_required_code(self, app_client: TestClient) -> None:
        _login(app_client)
        payload = {
            "name": "Daily standup",
            "type": "fixed",
            "fixed_time_of_day": "09:00",
            "recurrence": {"pattern": "daily", "interval": 1, "anchor": "calendar"},
            "priority": "medium",
            "estimated_duration_minutes": 15,
        }
        instance = app_client.post("/api/v1/task-templates", json=payload).json()["instance"]
        response = app_client.delete(f"/api/v1/task-instances/{instance['id']}")
        _assert_envelope(response, status=422, code="scope_required")


class TestGenericValidationError:
    def test_malformed_body_returns_the_validation_error_code_with_details(self, app_client: TestClient) -> None:
        _login(app_client)
        response = app_client.post("/api/v1/task-templates", json={"name": "Missing required fields"})
        assert response.status_code == 422
        body = response.json()
        assert body["code"] == "validation_error"
        assert "details" in body


class TestSessionExpired:
    def test_returns_401_with_the_session_expired_code(self, app_client: TestClient) -> None:
        """Distinct from a generic 401 - see design doc §3.6 - so the client redirects to
        login rather than surfacing a generic error."""
        _login(app_client)
        still_valid_cookie = app_client.cookies.get("tessera_session")
        app_client.post("/api/v1/auth/logout")
        app_client.cookies.set("tessera_session", still_valid_cookie)

        response = app_client.get("/api/v1/auth/me")
        _assert_envelope(response, status=401, code="session_expired")


class TestSyncConflictShape:
    """`sync_conflict`'s Notification shape, not an HTTP error code - listed alongside the
    others in implementation-plan §8's own "Tests required" bullet.
    """

    def test_sync_conflict_notification_has_the_documented_shape(self, app_client: TestClient) -> None:
        _login(app_client)

        # Seed the instance directly via the DB fixtures rather than through
        # POST /task-templates - the poll pipeline itself is covered end-to-end in
        # tests/integration/calendar_sync/, this test's job is only the wire shape once
        # a notification reaches the API. Going through the real creation endpoint here
        # used to install a genuinely `fixed`/`scheduled` instance under this fixture's
        # default UTC settings timezone; a hardcoded same-day `fixed_time_of_day` landed
        # in the past whenever the suite happened to run after that clock time, which
        # this `app_client` fixture's real APScheduler adapter (see its module docstring)
        # then fired almost immediately (`misfire_grace_time=None`) as a genuine `overdue`
        # notification racing this test's own `GET` a few lines down - an intermittent
        # extra row, not a real defect in the sync_conflict shape under test.
        from app.db.base import generate_id, utcnow
        from app.db.repositories import NotificationRepository, TaskInstanceRepository, TaskTemplateRepository
        from app.db.schemas import Notification
        from app.db.session import session_scope
        from tests.fixtures.db_entities import make_task_instance, make_task_template

        with session_scope() as db:
            template = TaskTemplateRepository(db).create(make_task_template(name="Team sync"))
            instance = TaskInstanceRepository(db).create(make_task_instance(template_id=template.id, name="Team sync"))
            NotificationRepository(db).create(
                Notification(
                    id=generate_id(),
                    type="sync_conflict",
                    related_instance_id=instance.id,
                    message="collides with an external event",
                    created_at=utcnow(),
                )
            )

        response = app_client.get("/api/v1/notifications")
        assert response.status_code == 200, response.text
        notifications = response.json()
        matching = [n for n in notifications if n["related_instance_id"] == instance.id]
        assert len(matching) == 1
        notification = matching[0]
        assert notification["type"] == "sync_conflict"
        assert notification["message"]
        assert notification["resolved_at"] is None
        assert notification["dismissed_at"] is None
