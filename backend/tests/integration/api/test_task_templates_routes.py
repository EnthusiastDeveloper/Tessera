"""HTTP-level task-template tests. Thin by design - the business logic these routes call
is already covered at the service layer (tests/integration/task_templates/test_service.py);
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


def _flexible_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "name": "Deep clean garage",
        "type": "flexible",
        "recurrence": {"pattern": "one_time", "anchor": "calendar"},
        "priority": "medium",
        "estimated_duration_minutes": 60,
        "deadline_offset_minutes": 60 * 24 * 5,
    }
    payload.update(overrides)
    return payload


class TestGetTemplate:
    def test_requires_authentication(self, app_client: TestClient) -> None:
        assert app_client.get("/api/v1/task-templates/anything").status_code == 401

    def test_returns_the_template(self, app_client: TestClient) -> None:
        _login(app_client)
        created = app_client.post("/api/v1/task-templates", json=_flexible_payload()).json()
        response = app_client.get(f"/api/v1/task-templates/{created['template']['id']}")
        assert response.status_code == 200, response.text
        assert response.json()["id"] == created["template"]["id"]
        assert response.json()["name"] == "Deep clean garage"

    def test_missing_template_returns_404(self, app_client: TestClient) -> None:
        _login(app_client)
        response = app_client.get("/api/v1/task-templates/does-not-exist")
        assert response.status_code == 404
        assert response.json()["code"] == "not_found"


class TestCreateTemplate:
    def test_requires_authentication(self, app_client: TestClient) -> None:
        assert app_client.post("/api/v1/task-templates", json=_flexible_payload()).status_code == 401

    def test_creates_a_template_and_its_initial_instance(self, app_client: TestClient) -> None:
        _login(app_client)
        response = app_client.post("/api/v1/task-templates", json=_flexible_payload())
        assert response.status_code == 201, response.text
        body = response.json()
        assert body["template"]["name"] == "Deep clean garage"
        assert body["instance"]["template_id"] == body["template"]["id"]

    def test_infeasible_duration_maps_to_422_with_the_right_code(self, app_client: TestClient) -> None:
        _login(app_client)
        response = app_client.post("/api/v1/task-templates", json=_flexible_payload(estimated_duration_minutes=999_999))
        assert response.status_code == 422
        assert response.json()["code"] == "infeasible_duration"


class TestPatchTemplate:
    def test_requires_a_scope_query_param(self, app_client: TestClient) -> None:
        _login(app_client)
        created = app_client.post("/api/v1/task-templates", json=_flexible_payload()).json()
        response = app_client.patch(f"/api/v1/task-templates/{created['template']['id']}", json={"name": "New name"})
        assert response.status_code == 422  # missing required `scope` query param

    def test_this_and_future_scope_updates_the_template(self, app_client: TestClient) -> None:
        _login(app_client)
        created = app_client.post("/api/v1/task-templates", json=_flexible_payload()).json()
        response = app_client.patch(
            f"/api/v1/task-templates/{created['template']['id']}?scope=this_and_future", json={"name": "Renamed"}
        )
        assert response.status_code == 200, response.text
        assert response.json()["name"] == "Renamed"


class TestArchiveTemplate:
    def test_soft_deletes(self, app_client: TestClient) -> None:
        _login(app_client)
        created = app_client.post("/api/v1/task-templates", json=_flexible_payload()).json()
        response = app_client.delete(f"/api/v1/task-templates/{created['template']['id']}")
        assert response.status_code == 200, response.text
        assert response.json()["template"]["archived"] is True
