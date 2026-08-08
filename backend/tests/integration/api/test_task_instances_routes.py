"""HTTP-level task-instance tests. Thin by design - the business logic these routes call
is already covered at the service layer (tests/integration/task_instances/test_service.py);
this file only proves the wiring: auth guard, request/response shape, and error-code mapping.
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


def _create_fixed(client: TestClient) -> dict[str, object]:
    payload = {
        "name": "Team sync",
        "type": "fixed",
        "fixed_time_of_day": "18:00",
        "recurrence": {"pattern": "one_time", "anchor": "calendar"},
        "priority": "medium",
        "estimated_duration_minutes": 60,
    }
    return client.post("/api/v1/task-templates", json=payload).json()["instance"]  # type: ignore[no-any-return]


class TestPatchInstance:
    def test_requires_authentication(self, app_client: TestClient) -> None:
        assert app_client.patch("/api/v1/task-instances/anything", json={"name": "x"}).status_code == 401

    def test_this_occurrence_edit_sets_detached(self, app_client: TestClient) -> None:
        _login(app_client)
        instance = _create_fixed(app_client)
        response = app_client.patch(f"/api/v1/task-instances/{instance['id']}", json={"name": "Renamed occurrence"})
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["name"] == "Renamed occurrence"
        assert body["detached"] is True

    def test_deadline_edit_on_a_fixed_instance_is_rejected(self, app_client: TestClient) -> None:
        """`scheduled_time` isn't even a field on `PatchInstanceRequest` (retiming a fixed
        instance goes through `/reschedule` instead, see that route's own docstring) - the
        one `invalid_field` case actually reachable through this schema is `deadline` on a
        non-flexible instance (§3.10's service-layer check).
        """
        _login(app_client)
        instance = _create_fixed(app_client)
        response = app_client.patch(f"/api/v1/task-instances/{instance['id']}", json={"deadline": "2026-01-01T00:00:00Z"})
        assert response.status_code == 422
        assert response.json()["code"] == "invalid_field"


class TestReschedule:
    def test_moves_a_fixed_instance(self, app_client: TestClient) -> None:
        _login(app_client)
        instance = _create_fixed(app_client)
        response = app_client.post(
            f"/api/v1/task-instances/{instance['id']}/reschedule", json={"scheduled_time": "2026-06-01T18:00:00Z"}
        )
        assert response.status_code == 200, response.text
        assert response.json()["scheduled_time"] == "2026-06-01T18:00:00Z"


class TestComplete:
    def test_marks_completed(self, app_client: TestClient) -> None:
        _login(app_client)
        instance = _create_fixed(app_client)
        response = app_client.post(f"/api/v1/task-instances/{instance['id']}/complete")
        assert response.status_code == 200, response.text
        assert response.json()["status"] == "completed"

    def test_completing_twice_is_rejected(self, app_client: TestClient) -> None:
        _login(app_client)
        instance = _create_fixed(app_client)
        app_client.post(f"/api/v1/task-instances/{instance['id']}/complete")
        response = app_client.post(f"/api/v1/task-instances/{instance['id']}/complete")
        assert response.status_code == 422
        assert response.json()["code"] == "invalid_field"


class TestDelete:
    def test_deletes_and_returns_unblocked_ids(self, app_client: TestClient) -> None:
        _login(app_client)
        instance = _create_fixed(app_client)
        response = app_client.delete(f"/api/v1/task-instances/{instance['id']}")
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["deleted_instance_id"] == instance["id"]
        assert body["unblocked_instance_ids"] == []
