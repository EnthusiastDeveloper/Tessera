"""HTTP-level notification tests. Thin by design - list/dismiss logic is already covered
at the service layer (tests/integration/notifications/test_service.py); this file only
proves the wiring: auth guard and response shape.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.auth.setup_token import setup_token_store

VALID_PASSWORD = "correcthorsebatterystaple"


def _login(client: TestClient) -> None:
    token = setup_token_store._token  # test-only introspection, see test_auth_routes.py
    assert token is not None
    client.post("/api/v1/auth/setup", json={"token": token, "password": VALID_PASSWORD})
    client.post("/api/v1/auth/login", json={"username": "admin", "password": VALID_PASSWORD})


def _create_unschedulable_notification(client: TestClient) -> str:
    """A flexible template whose deadline is too tight to fit its own duration - the
    fastest real path to a persisted `unschedulable` Notification (§6.2/§5).
    """
    payload = {
        "name": "Impossible task",
        "type": "flexible",
        "recurrence": {"pattern": "one_time", "anchor": "calendar"},
        "priority": "medium",
        "estimated_duration_minutes": 60,
        "deadline_offset_minutes": 1,
    }
    created = client.post("/api/v1/task-templates", json=payload).json()
    return created["instance"]["id"]  # type: ignore[no-any-return]


class TestListNotifications:
    def test_requires_authentication(self, app_client: TestClient) -> None:
        assert app_client.get("/api/v1/notifications").status_code == 401

    def test_lists_an_active_unschedulable_notification(self, app_client: TestClient) -> None:
        _login(app_client)
        instance_id = _create_unschedulable_notification(app_client)
        response = app_client.get("/api/v1/notifications")
        assert response.status_code == 200, response.text
        body = response.json()
        assert any(n["type"] == "unschedulable" and n["related_instance_id"] == instance_id for n in body)


class TestDismissNotification:
    def test_requires_authentication(self, app_client: TestClient) -> None:
        assert app_client.post("/api/v1/notifications/anything/dismiss").status_code == 401

    def test_dismiss_removes_it_from_the_active_list(self, app_client: TestClient) -> None:
        _login(app_client)
        _create_unschedulable_notification(app_client)
        notification_id = app_client.get("/api/v1/notifications").json()[0]["id"]

        response = app_client.post(f"/api/v1/notifications/{notification_id}/dismiss")
        assert response.status_code == 200, response.text
        assert response.json()["dismissed_at"] is not None

        assert app_client.get("/api/v1/notifications").json() == []

    def test_unknown_id_is_404(self, app_client: TestClient) -> None:
        _login(app_client)
        response = app_client.post("/api/v1/notifications/does-not-exist/dismiss")
        assert response.status_code == 404
