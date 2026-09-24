"""HTTP-level task-template tests. Thin by design - the business logic these routes call
is already covered at the service layer (tests/integration/task_templates/test_service.py);
this file only proves the wiring: auth guard, request/response shape, and error-code mapping.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.auth.setup_token import setup_token_store

VALID_PASSWORD = "correcthorsebatterystaple"


def _complete_setup(client: TestClient) -> None:
    token = setup_token_store._token  # test-only introspection, see test_auth_routes.py
    assert token is not None
    client.post("/api/v1/auth/setup", json={"token": token, "password": VALID_PASSWORD})


def _login(client: TestClient) -> None:
    _complete_setup(client)
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
        _complete_setup(app_client)
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
        _complete_setup(app_client)
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

    def test_a_colliding_fixed_time_maps_to_409_creation_conflict(self, app_client: TestClient) -> None:
        _login(app_client)
        fixed = {"type": "fixed", "estimated_duration_minutes": 60, "deadline_offset_minutes": None}
        app_client.post("/api/v1/task-templates", json=_flexible_payload(name="Dinner", fixed_time_of_day="18:00", **fixed))
        call = app_client.post(
            "/api/v1/task-templates", json=_flexible_payload(name="Call", fixed_time_of_day="20:00", **fixed)
        ).json()

        response = app_client.patch(
            f"/api/v1/task-templates/{call['template']['id']}?scope=this_and_future", json={"fixed_time_of_day": "18:30"}
        )
        assert response.status_code == 409, response.text
        assert response.json()["code"] == "creation_conflict"
        # Rolled back as a whole: the template never took the new time either.
        assert app_client.get(f"/api/v1/task-templates/{call['template']['id']}").json()["fixed_time_of_day"] == "20:00"


class TestArchiveTemplate:
    def test_soft_deletes(self, app_client: TestClient) -> None:
        _login(app_client)
        created = app_client.post("/api/v1/task-templates", json=_flexible_payload()).json()
        response = app_client.delete(f"/api/v1/task-templates/{created['template']['id']}")
        assert response.status_code == 200, response.text
        assert response.json()["template"]["archived"] is True


def _weekly_fixed_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "name": "Weekly team sync",
        "type": "fixed",
        "recurrence": {"pattern": "weekly", "interval": 1, "day_of_week": 0, "anchor": "calendar"},
        "priority": "medium",
        "estimated_duration_minutes": 30,
        "fixed_time_of_day": "09:00",
    }
    payload.update(overrides)
    return payload


class TestProjections:
    """`GET /task-templates/projections` (design doc §9.2, added Stage 9d). Business logic
    (anchor branching, the horizon boundary, the completion-anchor rebase) is covered at
    the unit level (tests/unit/scheduling/test_virtual_occurrences.py) - this file only
    proves the route wires up: auth, the "/projections" vs "/{template_id}" path-matching
    order, and the response shape (no `id`, no real-instance fields).
    """

    def test_requires_authentication(self, app_client: TestClient) -> None:
        _complete_setup(app_client)
        assert app_client.get("/api/v1/task-templates/projections").status_code == 401

    def test_does_not_get_captured_by_the_template_id_path_param(self, app_client: TestClient) -> None:
        """Regression guard: `/projections` must resolve to the dedicated route, not
        `GET /{template_id}` with `template_id="projections"` (which would 404).
        """
        _login(app_client)
        response = app_client.get("/api/v1/task-templates/projections")
        assert response.status_code == 200, response.text
        assert isinstance(response.json(), list)

    def test_one_time_template_produces_no_ghosts(self, app_client: TestClient) -> None:
        _login(app_client)
        app_client.post("/api/v1/task-templates", json=_flexible_payload())
        response = app_client.get("/api/v1/task-templates/projections")
        assert response.status_code == 200, response.text
        assert response.json() == []

    def test_recurring_calendar_anchored_template_produces_ghosts_with_the_right_shape(self, app_client: TestClient) -> None:
        _login(app_client)
        created = app_client.post("/api/v1/task-templates", json=_weekly_fixed_payload()).json()
        template_id = created["template"]["id"]

        response = app_client.get("/api/v1/task-templates/projections")
        assert response.status_code == 200, response.text
        occurrences = [o for o in response.json() if o["template_id"] == template_id]
        assert len(occurrences) >= 1
        occurrence = occurrences[0]
        assert occurrence["anchor"] == "calendar"
        assert occurrence["name"] == "Weekly team sync"
        assert occurrence["type"] == "fixed"
        assert "occurs_at" in occurrence
        assert "id" not in occurrence  # §9.2: never confused with a real TaskInstance
        assert "status" not in occurrence
        assert "detached" not in occurrence

    def test_archived_template_produces_no_ghosts(self, app_client: TestClient) -> None:
        _login(app_client)
        created = app_client.post("/api/v1/task-templates", json=_weekly_fixed_payload()).json()
        template_id = created["template"]["id"]
        app_client.delete(f"/api/v1/task-templates/{template_id}")

        response = app_client.get("/api/v1/task-templates/projections")
        assert response.status_code == 200, response.text
        assert all(o["template_id"] != template_id for o in response.json())
