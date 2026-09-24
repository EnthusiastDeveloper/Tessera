"""HTTP-level task-instance tests. Thin by design - the business logic these routes call
is already covered at the service layer (tests/integration/task_instances/test_service.py);
this file only proves the wiring: auth guard, request/response shape, and error-code mapping.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.auth.setup_token import setup_token_store
from app.jobs.interface import set_job_scheduler
from app.task_instances import service as task_instances_service
from tests.fixtures.jobs import RecordingJobScheduler

VALID_PASSWORD = "correcthorsebatterystaple"


def _complete_setup(client: TestClient) -> None:
    token = setup_token_store._token  # test-only introspection, see test_auth_routes.py
    assert token is not None
    client.post("/api/v1/auth/setup", json={"token": token, "password": VALID_PASSWORD})


def _login(client: TestClient) -> None:
    _complete_setup(client)
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


def _create_recurring_fixed(client: TestClient) -> dict[str, object]:
    payload = {
        "name": "Daily standup",
        "type": "fixed",
        "fixed_time_of_day": "09:00",
        "recurrence": {"pattern": "daily", "interval": 1, "anchor": "calendar"},
        "priority": "medium",
        "estimated_duration_minutes": 15,
    }
    return client.post("/api/v1/task-templates", json=payload).json()["instance"]  # type: ignore[no-any-return]


class TestListInstances:
    def test_requires_authentication(self, app_client: TestClient) -> None:
        _complete_setup(app_client)
        assert app_client.get("/api/v1/task-instances").status_code == 401

    def test_lists_created_instances(self, app_client: TestClient) -> None:
        _login(app_client)
        instance = _create_fixed(app_client)
        response = app_client.get("/api/v1/task-instances")
        assert response.status_code == 200, response.text
        assert instance["id"] in {i["id"] for i in response.json()}

    def test_filters_by_status(self, app_client: TestClient) -> None:
        _login(app_client)
        _create_fixed(app_client)
        response = app_client.get("/api/v1/task-instances", params={"status": "completed"})
        assert response.status_code == 200, response.text
        assert response.json() == []

    def test_backlog_view(self, app_client: TestClient) -> None:
        _login(app_client)
        response = app_client.get("/api/v1/task-instances", params={"view": "backlog"})
        assert response.status_code == 200, response.text
        assert response.json() == []


class TestPatchInstance:
    def test_requires_authentication(self, app_client: TestClient) -> None:
        _complete_setup(app_client)
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

    def test_expected_mismatch_is_a_409_conflict_naming_the_field(self, app_client: TestClient) -> None:
        """architecture-plan §5.1/§3's error table: `conflict` is `409` and the body must
        name the conflicting field and its current server-side value.
        """
        _login(app_client)
        instance = _create_fixed(app_client)
        app_client.patch(f"/api/v1/task-instances/{instance['id']}", json={"name": "Changed by someone else"})

        response = app_client.patch(
            f"/api/v1/task-instances/{instance['id']}",
            json={"name": "My edit", "expected": {"name": "Team sync"}},
        )
        assert response.status_code == 409, response.text
        body = response.json()
        assert body["code"] == "conflict"
        assert body["details"]["conflicting_fields"] == {"name": "Changed by someone else"}

    def test_expected_match_applies_the_patch(self, app_client: TestClient) -> None:
        _login(app_client)
        instance = _create_fixed(app_client)
        response = app_client.patch(
            f"/api/v1/task-instances/{instance['id']}",
            json={"name": "Renamed", "expected": {"name": "Team sync"}},
        )
        assert response.status_code == 200, response.text
        assert response.json()["name"] == "Renamed"


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


class TestStart:
    def test_requires_authentication(self, app_client: TestClient) -> None:
        _complete_setup(app_client)
        assert app_client.post("/api/v1/task-instances/anything/start").status_code == 401

    def test_starts_a_scheduled_instance(self, app_client: TestClient) -> None:
        _login(app_client)
        instance = _create_fixed(app_client)
        response = app_client.post(f"/api/v1/task-instances/{instance['id']}/start")
        assert response.status_code == 200, response.text
        assert response.json()["status"] == "in_progress"

    def test_starting_twice_is_rejected(self, app_client: TestClient) -> None:
        _login(app_client)
        instance = _create_fixed(app_client)
        app_client.post(f"/api/v1/task-instances/{instance['id']}/start")
        response = app_client.post(f"/api/v1/task-instances/{instance['id']}/start")
        assert response.status_code == 422
        assert response.json()["code"] == "invalid_field"


class TestDismiss:
    def test_requires_authentication(self, app_client: TestClient) -> None:
        _complete_setup(app_client)
        assert app_client.post("/api/v1/task-instances/anything/dismiss").status_code == 401

    def test_dismisses(self, app_client: TestClient) -> None:
        _login(app_client)
        instance = _create_fixed(app_client)
        response = app_client.post(f"/api/v1/task-instances/{instance['id']}/dismiss")
        assert response.status_code == 200, response.text
        assert response.json()["status"] == "dismissed"

    def test_dismissing_twice_is_rejected(self, app_client: TestClient) -> None:
        _login(app_client)
        instance = _create_fixed(app_client)
        app_client.post(f"/api/v1/task-instances/{instance['id']}/dismiss")
        response = app_client.post(f"/api/v1/task-instances/{instance['id']}/dismiss")
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

    def test_scope_is_required_for_a_recurring_template(self, app_client: TestClient) -> None:
        _login(app_client)
        instance = _create_recurring_fixed(app_client)
        response = app_client.delete(f"/api/v1/task-instances/{instance['id']}")
        assert response.status_code == 422
        assert response.json()["code"] == "scope_required"

    def test_this_and_future_scope_deletes(self, app_client: TestClient) -> None:
        _login(app_client)
        instance = _create_recurring_fixed(app_client)
        response = app_client.delete(f"/api/v1/task-instances/{instance['id']}?scope=this_and_future")
        assert response.status_code == 200, response.text
        assert response.json()["deleted_instance_id"] == instance["id"]

    def test_invalid_scope_value_is_a_validation_error(self, app_client: TestClient) -> None:
        _login(app_client)
        instance = _create_recurring_fixed(app_client)
        response = app_client.delete(f"/api/v1/task-instances/{instance['id']}?scope=not-a-real-scope")
        assert response.status_code == 422


class TestJobChangesFollowTheTransaction:
    """Issue #23: job-store changes made mid-request must not survive a rollback."""

    def test_a_complete_that_fails_partway_leaves_the_instances_jobs_in_place(
        self, app_client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _login(app_client)
        instance = _create_fixed(app_client)
        recorder = RecordingJobScheduler()
        set_job_scheduler(recorder)  # the app_client fixture restores a no-op scheduler afterwards

        def _fail(*args: object, **kwargs: object) -> None:
            raise RuntimeError("simulated failure after the job cancel")

        monkeypatch.setattr(task_instances_service, "_unblock_dependents", _fail)
        with pytest.raises(RuntimeError):
            app_client.post(f"/api/v1/task-instances/{instance['id']}/complete")

        assert recorder.cancelled_instances == [], "the cancel must be discarded with the rolled-back transaction"
        listed = app_client.get("/api/v1/task-instances").json()
        assert [row["status"] for row in listed if row["id"] == instance["id"]] == ["scheduled"]

    def test_a_successful_complete_does_cancel_the_jobs(self, app_client: TestClient) -> None:
        _login(app_client)
        instance = _create_fixed(app_client)
        recorder = RecordingJobScheduler()
        set_job_scheduler(recorder)

        assert app_client.post(f"/api/v1/task-instances/{instance['id']}/complete").status_code == 200
        assert recorder.cancelled_instances == [instance["id"]]
