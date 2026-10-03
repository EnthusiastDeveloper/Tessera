"""HTTP-level tests for "Optimize Schedule" (design doc §6.11, Rev 14; architecture-plan §3):
the endpoints, their error codes, and the server-side edit lock. The job is run by hand against
the app's own database the way the scheduler would; the placement rules themselves are covered
by `tests/integration/scheduling/test_schedule_optimization.py`.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.auth.setup_token import setup_token_store
from app.db.repositories import TaskInstanceRepository
from app.db.session import session_scope
from app.jobs import handlers
from app.jobs.interface import NoOpJobScheduler, schedule_optimization_job_key, set_job_scheduler
from tests.fixtures.jobs import RecordingJobScheduler
from tests.fixtures.scheduling import app_today

VALID_PASSWORD = "correcthorsebatterystaple"
BASE = "/api/v1/schedule-optimizations"


@pytest.fixture
def client(app_client: TestClient) -> TestClient:
    token = setup_token_store._token  # test-only introspection, see test_auth_routes.py
    assert token is not None
    app_client.post("/api/v1/auth/setup", json={"token": token, "password": VALID_PASSWORD})
    app_client.post("/api/v1/auth/login", json={"username": "admin", "password": VALID_PASSWORD})
    return app_client


@pytest.fixture
def recorder() -> RecordingJobScheduler:
    scheduler = RecordingJobScheduler()
    set_job_scheduler(scheduler)  # the app_client fixture restores a no-op scheduler afterwards
    return scheduler


def _task(client: TestClient, name: str = "Water the plants") -> dict[str, Any]:
    response = client.post(
        "/api/v1/task-templates",
        json={
            "name": name,
            "type": "flexible",
            "recurrence": {"pattern": "one_time", "anchor": "calendar"},
            "priority": "medium",
            "start_date": app_today().isoformat(),
            "estimated_duration_minutes": 30,
            "deadline_offset_minutes": 60 * 24 * 5,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["instance"]  # type: ignore[no-any-return]


def _run_job(optimization_id: str) -> None:
    """What the scheduler does when the job fires."""
    with session_scope() as db:
        handlers.run_schedule_optimization(db, NoOpJobScheduler(), optimization_id=optimization_id)


class TestStarting:
    def test_posting_starts_a_background_run_and_reports_the_limits_in_force(
        self, client: TestClient, recorder: RecordingJobScheduler
    ) -> None:
        response = client.post(BASE)
        assert response.status_code == 202, response.text
        body = response.json()
        assert body["status"] == "running" and body["undo_available"] is False
        assert (body["slow_after_seconds"], body["timeout_seconds"]) == (10, 30)
        assert schedule_optimization_job_key(body["id"]) in recorder.scheduled_keys()

        latest = client.get(f"{BASE}/latest").json()
        assert latest["id"] == body["id"] and latest["status"] == "running"

    def test_a_second_request_while_one_runs_is_refused(self, client: TestClient, recorder: RecordingJobScheduler) -> None:
        client.post(BASE)
        again = client.post(BASE)
        assert again.status_code == 409
        assert again.json()["code"] == "optimization_in_progress"

    def test_latest_is_null_before_any_run(self, client: TestClient) -> None:
        assert client.get(f"{BASE}/latest").json() is None

    def test_every_route_needs_a_session(self, client: TestClient) -> None:
        client.cookies.clear()  # the account exists, but this caller is not signed in
        for response in (
            client.post(BASE),
            client.get(f"{BASE}/latest"),
            client.get(f"{BASE}/opportunity"),
            client.post(f"{BASE}/x/approve"),
            client.post(f"{BASE}/x/decline"),
            client.post(f"{BASE}/x/undo"),
        ):
            assert response.status_code == 401


class TestTheServerSideEditLock:
    @pytest.fixture
    def running(self, client: TestClient, recorder: RecordingJobScheduler) -> str:
        instance = _task(client)
        body = client.post(BASE).json()
        client.instance_id = instance["id"]  # type: ignore[attr-defined]
        return body["id"]  # type: ignore[no-any-return]

    def test_every_schedule_changing_write_is_refused_while_it_runs(self, client: TestClient, running: str) -> None:
        instance_id = client.instance_id  # type: ignore[attr-defined]
        attempts = [
            client.post(
                "/api/v1/task-templates",
                json={
                    "name": "New",
                    "type": "flexible",
                    "recurrence": {"pattern": "one_time", "anchor": "calendar"},
                    "priority": "low",
                    "start_date": app_today().isoformat(),
                    "estimated_duration_minutes": 30,
                    "deadline_offset_minutes": 1440,
                },
            ),
            client.patch(f"/api/v1/task-instances/{instance_id}", json={"name": "Renamed"}),
            client.post(f"/api/v1/task-instances/{instance_id}/complete"),
            client.post(f"/api/v1/task-instances/{instance_id}/dismiss"),
            client.delete(f"/api/v1/task-instances/{instance_id}"),
            client.patch("/api/v1/settings", json={"first_day_of_week": "sunday"}),
        ]
        assert [a.status_code for a in attempts] == [409] * len(attempts)
        assert {a.json()["code"] for a in attempts} == {"optimization_in_progress"}

    def test_reads_still_work_while_it_runs(self, client: TestClient, running: str) -> None:
        assert client.get("/api/v1/task-instances").status_code == 200
        assert client.get("/api/v1/settings").status_code == 200
        assert client.get("/api/v1/notifications").status_code == 200
        assert client.get(f"{BASE}/opportunity").status_code == 200  # asking is a read

    def test_edits_work_again_as_soon_as_it_finishes(self, client: TestClient, running: str) -> None:
        instance_id = client.instance_id  # type: ignore[attr-defined]
        _run_job(running)
        assert client.patch(f"/api/v1/task-instances/{instance_id}", json={"name": "Renamed"}).status_code == 200

    def test_a_held_plan_does_not_lock_anything(self, client: TestClient, recorder: RecordingJobScheduler) -> None:
        # Awaiting approval is the user thinking; nothing is locked (design doc §6.11).
        instance = _task(client)
        started = client.post(BASE).json()
        _run_job(started["id"])
        assert client.get(f"{BASE}/latest").json()["status"] in ("nothing_to_do", "applied", "awaiting_approval")
        assert client.patch(f"/api/v1/task-instances/{instance['id']}", json={"name": "Free"}).status_code == 200


class TestRunningIt:
    def test_nothing_to_improve_is_reported_with_its_reason_and_no_undo(
        self, client: TestClient, recorder: RecordingJobScheduler
    ) -> None:
        _task(client)
        # Asking whether it is worth it says no, and is not itself an optimization.
        assert client.get(f"{BASE}/opportunity").json()["worthwhile"] is False
        assert client.get(f"{BASE}/latest").json() is None
        started = client.post(BASE).json()
        _run_job(started["id"])

        latest = client.get(f"{BASE}/latest").json()
        assert latest["status"] == "nothing_to_do" and latest["reason"] == "identical"
        assert latest["undo_available"] is False and latest["undo_until"] is None

    def test_an_improvement_applies_at_once_and_can_be_undone(self, client: TestClient, recorder: RecordingJobScheduler) -> None:
        instance = _task(client)
        # A task the schedule failed to place (what corner-painting leaves behind).
        with session_scope() as db:
            repo = TaskInstanceRepository(db)
            current = repo.get(instance["id"])
            assert current is not None
            repo.update(current.model_copy(update={"status": "pending", "scheduled_time": None}))

        assert client.get(f"{BASE}/opportunity").json() == {
            "gain": 1, "newly_scheduled": 1, "lost": 0, "over_budget": 0, "moved": 0,
            "needs_approval": False, "worthwhile": True,
        }  # fmt: skip
        started = client.post(BASE).json()
        _run_job(started["id"])

        latest = client.get(f"{BASE}/latest").json()
        assert latest["status"] == "applied" and latest["undo_available"] is True
        assert client.get(f"{BASE}/opportunity").json()["worthwhile"] is False  # it did what it could
        assert latest["summary"]["counts"]["newly_scheduled"] == 1
        assert latest["summary"]["newly_scheduled"][0]["name"] == "Water the plants"
        assert client.get("/api/v1/task-instances").json()[0]["status"] == "scheduled"

        undone = client.post(f"{BASE}/{latest['id']}/undo")
        assert undone.status_code == 200 and undone.json()["status"] == "undone"
        assert undone.json()["undo_available"] is False
        assert client.get("/api/v1/task-instances").json()[0]["status"] == "pending"

    def test_undo_vanishes_once_the_task_is_touched(self, client: TestClient, recorder: RecordingJobScheduler) -> None:
        instance = _task(client)
        with session_scope() as db:
            repo = TaskInstanceRepository(db)
            current = repo.get(instance["id"])
            assert current is not None
            repo.update(current.model_copy(update={"status": "pending", "scheduled_time": None}))
        started = client.post(BASE).json()
        _run_job(started["id"])
        assert client.get(f"{BASE}/latest").json()["undo_available"] is True

        client.post(f"/api/v1/task-instances/{instance['id']}/complete")

        latest = client.get(f"{BASE}/latest").json()
        assert latest["undo_available"] is False  # the button is simply not offered
        refused = client.post(f"{BASE}/{latest['id']}/undo")  # the click that raced the change
        assert refused.status_code == 409 and refused.json()["code"] == "undo_unavailable"
        assert refused.json()["details"]["reasons"][0]["reason"] == "instance_changed"


class TestErrors:
    def test_approving_or_declining_what_is_not_waiting_is_refused(
        self, client: TestClient, recorder: RecordingJobScheduler
    ) -> None:
        started = client.post(BASE).json()
        _run_job(started["id"])  # nothing to do
        for action in ("approve", "decline"):
            response = client.post(f"{BASE}/{started['id']}/{action}")
            assert response.status_code == 409
            assert response.json()["code"] == "invalid_optimization_state"

    def test_undoing_what_was_never_applied_is_refused(self, client: TestClient, recorder: RecordingJobScheduler) -> None:
        started = client.post(BASE).json()
        _run_job(started["id"])
        response = client.post(f"{BASE}/{started['id']}/undo")
        assert response.status_code == 409 and response.json()["code"] == "undo_unavailable"

    def test_an_unknown_id_is_a_404(self, client: TestClient) -> None:
        for action in ("approve", "decline", "undo"):
            assert client.post(f"{BASE}/nope/{action}").status_code == 404
