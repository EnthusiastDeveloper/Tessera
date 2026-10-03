"""HTTP-level settings tests. See implementation-plan Stage 4 "Tests required"."""

from __future__ import annotations

import time
from datetime import timedelta

from fastapi.testclient import TestClient

from app.auth.setup_token import setup_token_store
from app.settings.service import DAY_NAMES
from tests.fixtures.scheduling import app_today

VALID_PASSWORD = "correcthorsebatterystaple"


def _complete_setup(client: TestClient) -> None:
    token = setup_token_store._token  # test-only introspection, see test_auth_routes.py
    assert token is not None
    client.post("/api/v1/auth/setup", json={"token": token, "password": VALID_PASSWORD})


def _login(client: TestClient) -> None:
    _complete_setup(client)
    client.post("/api/v1/auth/login", json={"username": "admin", "password": VALID_PASSWORD})


class TestGetSettings:
    def test_default_row_exists_from_startup_with_utc_timezone(self, app_client: TestClient) -> None:
        """No TZ env var is set in the test environment (see app_client's monkeypatch
        setup) - the lifespan-created default row should have fallen back to UTC.
        """
        _login(app_client)
        response = app_client.get("/api/v1/settings")
        assert response.status_code == 200
        body = response.json()
        assert body["timezone"] == "UTC"
        assert body["budget_enforcement"] == "soft"
        assert body["first_day_of_week"] == "monday"
        assert body["blackout_dates"] == []
        assert body["active_hours"]["monday"] == [{"start": "09:00", "end": "17:00"}]
        assert body["daily_time_budget_minutes"]["monday"] is None


class TestPatchSettings:
    def test_valid_partial_patch_succeeds_and_touches_only_that_field(self, app_client: TestClient) -> None:
        _login(app_client)
        response = app_client.patch("/api/v1/settings", json={"timezone": "America/New_York"})
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["timezone"] == "America/New_York"
        assert body["budget_enforcement"] == "soft"  # untouched
        assert body["first_day_of_week"] == "monday"  # untouched

    def test_bad_timezone_is_rejected(self, app_client: TestClient) -> None:
        _login(app_client)
        response = app_client.patch("/api/v1/settings", json={"timezone": "Not/A/Real/Zone"})
        assert response.status_code == 422
        assert response.json()["code"] == "invalid_timezone"

    def test_bad_budget_enforcement_enum_is_rejected(self, app_client: TestClient) -> None:
        _login(app_client)
        response = app_client.patch("/api/v1/settings", json={"budget_enforcement": "not-a-real-value"})
        assert response.status_code == 422

    def test_bad_first_day_of_week_enum_is_rejected(self, app_client: TestClient) -> None:
        _login(app_client)
        response = app_client.patch("/api/v1/settings", json={"first_day_of_week": "not-a-day"})
        assert response.status_code == 422

    def test_active_hours_missing_a_day_is_rejected(self, app_client: TestClient) -> None:
        _login(app_client)
        incomplete = {"monday": [{"start": "09:00", "end": "17:00"}]}  # only 1 of 7 days
        response = app_client.patch("/api/v1/settings", json={"active_hours": incomplete})
        assert response.status_code == 422
        assert response.json()["code"] == "invalid_day_map"

    def test_full_active_hours_map_with_a_null_day_is_accepted(self, app_client: TestClient) -> None:
        _login(app_client)
        get_response = app_client.get("/api/v1/settings")
        hours = dict(get_response.json()["active_hours"])
        hours["sunday"] = None
        response = app_client.patch("/api/v1/settings", json={"active_hours": hours})
        assert response.status_code == 200, response.text
        assert response.json()["active_hours"]["sunday"] is None
        assert response.json()["active_hours"]["monday"] == [{"start": "09:00", "end": "17:00"}]

    def test_patch_persists_across_requests(self, app_client: TestClient) -> None:
        _login(app_client)
        app_client.patch("/api/v1/settings", json={"first_day_of_week": "sunday"})
        response = app_client.get("/api/v1/settings")
        assert response.json()["first_day_of_week"] == "sunday"

    def test_blackout_dates_round_trip(self, app_client: TestClient) -> None:
        _login(app_client)
        blackout = [{"start": "2026-12-24", "end": "2026-12-26", "label": "Holidays"}]
        response = app_client.patch("/api/v1/settings", json={"blackout_dates": blackout})
        assert response.status_code == 200, response.text
        assert response.json()["blackout_dates"] == blackout


class TestScheduleRepair:
    """Design doc §6.10 (Rev 11): a stricter save starts a background repair the client
    can follow. The real job scheduler runs it, so this polls like the overlay does."""

    def test_no_repair_has_ever_run(self, app_client: TestClient) -> None:
        _login(app_client)
        response = app_client.get("/api/v1/settings/schedule-repair")
        assert response.status_code == 200
        assert response.json() is None

    def test_narrowing_the_window_repairs_a_stranded_task_in_the_background(self, app_client: TestClient) -> None:
        _login(app_client)
        tomorrow = app_today() + timedelta(days=1)
        created = app_client.post(
            "/api/v1/task-templates",
            json={
                "name": "Stranded",
                "type": "flexible",
                "recurrence": {"pattern": "one_time", "anchor": "calendar"},
                "priority": "medium",
                "start_date": tomorrow.isoformat(),
                "estimated_duration_minutes": 60,
                "deadline_offset_minutes": 60 * 24 * 3,
            },
        ).json()
        assert created["instance"]["scheduled_time"].startswith(f"{tomorrow.isoformat()}T09:00")

        narrowed = {day: [{"start": "10:00", "end": "17:00"}] for day in DAY_NAMES}
        assert app_client.patch("/api/v1/settings", json={"active_hours": narrowed}).status_code == 200

        deadline = time.monotonic() + 10
        repair = app_client.get("/api/v1/settings/schedule-repair").json()
        while repair["status"] != "finished" and time.monotonic() < deadline:
            time.sleep(0.05)
            repair = app_client.get("/api/v1/settings/schedule-repair").json()

        assert repair["status"] == "finished"
        assert (repair["done"], repair["total"], repair["moved"], repair["unschedulable"]) == (1, 1, 1, 0)
        moved = app_client.get("/api/v1/task-instances", params={"template_id": created["template"]["id"]}).json()[0]
        assert moved["scheduled_time"].startswith(f"{tomorrow.isoformat()}T10:00")
