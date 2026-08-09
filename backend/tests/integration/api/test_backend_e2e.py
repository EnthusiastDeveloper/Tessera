"""Backend E2E (API-level, no browser) - implementation-plan §8's named scenarios,
exercised as real HTTP round trips against the live app rather than direct service calls.
Individual pieces are already covered in more depth elsewhere (test_task_instances_routes.py,
test_task_templates_routes.py, etc.) - this file's job is proving each named flow works
start-to-finish through the actual API surface, in one place, matching the stage's own list.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.auth.setup_token import setup_token_store
from app.db.base import utcnow
from app.db.repositories import TaskInstanceRepository
from app.db.session import session_scope

VALID_PASSWORD = "correcthorsebatterystaple"


def _login(client: TestClient) -> None:
    token = setup_token_store._token
    assert token is not None
    client.post("/api/v1/auth/setup", json={"token": token, "password": VALID_PASSWORD})
    client.post("/api/v1/auth/login", json={"username": "admin", "password": VALID_PASSWORD})


class TestLogin:
    def test_full_login_lifecycle(self, app_client: TestClient) -> None:
        # No account yet - the guard rejects with setup_required, not a generic 401.
        pre_setup = app_client.get("/api/v1/task-instances")
        assert pre_setup.status_code == 403
        assert pre_setup.json()["code"] == "setup_required"

        token = setup_token_store._token
        assert token is not None
        setup_response = app_client.post("/api/v1/auth/setup", json={"token": token, "password": VALID_PASSWORD})
        assert setup_response.status_code == 201, setup_response.text

        login_response = app_client.post("/api/v1/auth/login", json={"username": "admin", "password": VALID_PASSWORD})
        assert login_response.status_code == 200, login_response.text

        # Session cookie now grants access.
        assert app_client.get("/api/v1/task-instances").status_code == 200

        logout_response = app_client.post("/api/v1/auth/logout")
        assert logout_response.status_code == 204
        assert app_client.get("/api/v1/task-instances").status_code == 401


class TestCreateWithConflict:
    def test_a_colliding_fixed_task_is_rejected_and_creates_nothing(self, app_client: TestClient) -> None:
        _login(app_client)
        first = {
            "name": "Team sync",
            "type": "fixed",
            "fixed_time_of_day": "18:00",
            "recurrence": {"pattern": "one_time", "anchor": "calendar"},
            "priority": "medium",
            "estimated_duration_minutes": 60,
        }
        created = app_client.post("/api/v1/task-templates", json=first)
        assert created.status_code == 201, created.text

        colliding = dict(first, name="Another meeting")
        response = app_client.post("/api/v1/task-templates", json=colliding)
        assert response.status_code == 409
        assert response.json()["code"] == "creation_conflict"

        instances = app_client.get("/api/v1/task-instances").json()
        assert [i["name"] for i in instances] == ["Team sync"]  # only the first survived


class TestCreateFlexibleAndSchedule:
    def test_a_flexible_task_is_placed_on_creation(self, app_client: TestClient) -> None:
        _login(app_client)
        payload = {
            "name": "Write report",
            "type": "flexible",
            "recurrence": {"pattern": "one_time", "anchor": "calendar"},
            "priority": "medium",
            "estimated_duration_minutes": 30,
            "deadline_offset_minutes": 60 * 24 * 5,
        }
        response = app_client.post("/api/v1/task-templates", json=payload)
        assert response.status_code == 201, response.text
        instance = response.json()["instance"]
        assert instance["status"] in ("scheduled", "pending")  # pending only if genuinely no slot exists
        if instance["status"] == "scheduled":
            assert instance["scheduled_time"] is not None


class TestCompleteTask:
    def test_completing_a_task_marks_it_done(self, app_client: TestClient) -> None:
        _login(app_client)
        payload = {
            "name": "Team sync",
            "type": "fixed",
            "fixed_time_of_day": "18:00",
            "recurrence": {"pattern": "one_time", "anchor": "calendar"},
            "priority": "medium",
            "estimated_duration_minutes": 60,
        }
        instance = app_client.post("/api/v1/task-templates", json=payload).json()["instance"]

        response = app_client.post(f"/api/v1/task-instances/{instance['id']}/complete")
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["status"] == "completed"
        assert body["completed_at"] is not None


class TestExtendAMissedDeadline:
    def test_extending_a_missed_deadline_returns_it_to_the_scheduling_pool(self, app_client: TestClient) -> None:
        _login(app_client)
        payload = {
            "name": "Deep clean garage",
            "type": "flexible",
            "recurrence": {"pattern": "one_time", "anchor": "calendar"},
            "priority": "medium",
            "estimated_duration_minutes": 30,
            "deadline_offset_minutes": 60 * 24 * 5,
        }
        instance = app_client.post("/api/v1/task-templates", json=payload).json()["instance"]

        # Simulate the deadline having already elapsed while pending (§6.7) - the same
        # "write inconsistent state directly via repositories" pattern the reconciliation
        # suite uses, since driving a real clock forward isn't practical here.
        with session_scope() as db:
            repo = TaskInstanceRepository(db)
            current = repo.get(instance["id"])
            assert current is not None
            repo.update(current.model_copy(update={"status": "missed", "deadline": utcnow()}))

        new_deadline = "2099-01-01T00:00:00Z"
        response = app_client.post(f"/api/v1/task-instances/{instance['id']}/extend-deadline", json={"deadline": new_deadline})
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["status"] in ("scheduled", "pending")
        assert body["deadline"] == new_deadline
        assert body["detached"] is True  # §6.7 Rev 7: extend-deadline is a "this occurrence" edit


class TestEditARecurringTaskBothScopesAndVerifyDetach:
    def test_this_occurrence_detaches_and_this_and_future_then_skips_it(self, app_client: TestClient) -> None:
        payload = {
            "name": "Daily standup",
            "type": "fixed",
            "fixed_time_of_day": "09:00",
            "recurrence": {"pattern": "daily", "interval": 1, "anchor": "calendar"},
            "priority": "medium",
            "estimated_duration_minutes": 15,
        }
        _login(app_client)
        created = app_client.post("/api/v1/task-templates", json=payload).json()
        template_id = created["template"]["id"]
        instance_id = created["instance"]["id"]

        # "This occurrence": PATCH the live instance directly - sets detached=true (§3.10).
        this_occurrence = app_client.patch(f"/api/v1/task-instances/{instance_id}", json={"name": "Standup (renamed once)"})
        assert this_occurrence.status_code == 200, this_occurrence.text
        assert this_occurrence.json()["detached"] is True
        assert this_occurrence.json()["name"] == "Standup (renamed once)"

        # "This and future": PATCH the template - a detached live instance is skipped
        # entirely by propagation (§3.10 "Detach is sticky and total").
        this_and_future = app_client.patch(f"/api/v1/task-templates/{template_id}?scope=this_and_future", json={"name": "Sync"})
        assert this_and_future.status_code == 200, this_and_future.text
        assert this_and_future.json()["name"] == "Sync"

        untouched_instance = app_client.get("/api/v1/task-instances", params={"status": "scheduled"}).json()
        matching = [i for i in untouched_instance if i["id"] == instance_id]
        assert len(matching) == 1
        assert matching[0]["name"] == "Standup (renamed once)"  # the template edit did not propagate
