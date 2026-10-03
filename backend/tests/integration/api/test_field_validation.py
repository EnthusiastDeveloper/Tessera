"""IRR-2 M11: request bodies are bounded (design doc §3.13). Each rejection is a
`422 validation_error` naming the offending field; the boundary values themselves pass.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.auth.setup_token import setup_token_store
from tests.fixtures.scheduling import app_today

VALID_PASSWORD = "correcthorsebatterystaple"


def _login(client: TestClient) -> None:
    token = setup_token_store._token  # test-only introspection, see test_auth_routes.py
    assert token is not None
    client.post("/api/v1/auth/setup", json={"token": token, "password": VALID_PASSWORD})
    client.post("/api/v1/auth/login", json={"username": "admin", "password": VALID_PASSWORD})


def _template(**overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "name": "Water the plants",
        "type": "flexible",
        "recurrence": {"pattern": "daily", "interval": 1, "anchor": "calendar"},
        "priority": "medium",
        "start_date": app_today().isoformat(),
        "estimated_duration_minutes": 30,
        "deadline_offset_minutes": 1440,
    }
    body.update(overrides)
    return body


def _fails_on(client: TestClient, response_field: str, response: Any) -> None:
    assert response.status_code == 422, response.text
    assert response.json()["code"] == "validation_error"
    assert response_field in {part for error in response.json()["details"] for part in error["loc"]}


class TestCreateTemplate:
    @pytest.mark.parametrize(
        ("field", "value"),
        [
            ("name", ""),
            ("name", "   "),
            ("name", "x" * 201),
            ("description", "x" * 2001),
            ("location", "x" * 201),
            ("estimated_duration_minutes", 0),
            ("estimated_duration_minutes", -5),
            ("estimated_duration_minutes", 1441),
            ("deadline_offset_minutes", 0),
            ("deadline_offset_minutes", 365 * 24 * 60 + 1),
            ("reminder_offsets_minutes", [-1]),
            ("reminder_offsets_minutes", [30 * 24 * 60 + 1]),
            ("reminder_offsets_minutes", list(range(11))),
            ("fixed_time_of_day", "25:00"),
            ("fixed_time_of_day", "9:00"),
            ("fixed_time_of_day", "18:60"),
        ],
    )
    def test_out_of_bounds_values_are_rejected(self, app_client: TestClient, field: str, value: Any) -> None:
        _login(app_client)
        _fails_on(app_client, field, app_client.post("/api/v1/task-templates", json=_template(**{field: value})))

    @pytest.mark.parametrize(
        ("recurrence", "field"),
        [
            ({"pattern": "daily", "interval": 0, "anchor": "calendar"}, "interval"),
            ({"pattern": "daily", "interval": 366, "anchor": "calendar"}, "interval"),
            ({"pattern": "weekly", "day_of_week": 7, "anchor": "calendar"}, "day_of_week"),
            ({"pattern": "weekly", "day_of_week": -1, "anchor": "calendar"}, "day_of_week"),
            ({"pattern": "monthly", "day_of_month": 0, "anchor": "calendar"}, "day_of_month"),
            ({"pattern": "monthly", "day_of_month": 32, "anchor": "calendar"}, "day_of_month"),
            ({"pattern": "custom", "interval": 3, "anchor": "calendar"}, "pattern"),
        ],
    )
    def test_out_of_bounds_recurrence_is_rejected(self, app_client: TestClient, recurrence: dict[str, Any], field: str) -> None:
        _login(app_client)
        _fails_on(app_client, field, app_client.post("/api/v1/task-templates", json=_template(recurrence=recurrence)))

    def test_the_boundary_values_themselves_are_accepted(self, app_client: TestClient) -> None:
        _login(app_client)
        response = app_client.post(
            "/api/v1/task-templates",
            json=_template(
                name="x" * 200,
                description="x" * 2000,
                location="x" * 200,
                estimated_duration_minutes=60,
                deadline_offset_minutes=365 * 24 * 60,
                reminder_offsets_minutes=[0, 30 * 24 * 60, *range(1, 9)],
                recurrence={"pattern": "monthly", "interval": 365, "day_of_month": 31, "anchor": "calendar"},
            ),
        )
        assert response.status_code == 201, response.text

    def test_a_name_is_stored_trimmed(self, app_client: TestClient) -> None:
        _login(app_client)
        response = app_client.post("/api/v1/task-templates", json=_template(name="  Water the plants  "))
        assert response.status_code == 201, response.text
        assert response.json()["template"]["name"] == "Water the plants"


class TestPatchTemplateAndInstance:
    def test_patch_template_applies_the_same_bounds(self, app_client: TestClient) -> None:
        _login(app_client)
        created = app_client.post("/api/v1/task-templates", json=_template()).json()
        template_id = created["template"]["id"]
        instance_id = created["instance"]["id"]
        url = f"/api/v1/task-templates/{template_id}?scope=this_and_future&from_instance={instance_id}"
        _fails_on(app_client, "name", app_client.patch(url, json={"name": ""}))
        _fails_on(app_client, "estimated_duration_minutes", app_client.patch(url, json={"estimated_duration_minutes": 0}))

    def test_patch_instance_applies_the_same_bounds(self, app_client: TestClient) -> None:
        _login(app_client)
        instance_id = app_client.post("/api/v1/task-templates", json=_template()).json()["instance"]["id"]
        url = f"/api/v1/task-instances/{instance_id}"
        _fails_on(app_client, "name", app_client.patch(url, json={"name": "   "}))
        _fails_on(app_client, "estimated_duration_minutes", app_client.patch(url, json={"estimated_duration_minutes": -1}))


class TestSettings:
    def _week(self, value: Any) -> dict[str, Any]:
        return {day: value for day in ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")}

    def test_active_hours_must_be_clock_times(self, app_client: TestClient) -> None:
        _login(app_client)
        for bad in ({"start": "9:00", "end": "17:00"}, {"start": "09:00", "end": "24:00"}):
            response = app_client.patch("/api/v1/settings", json={"active_hours": self._week(bad)})
            assert response.status_code == 422, response.text
            assert response.json()["code"] == "validation_error"

    def test_budget_is_between_zero_and_a_day(self, app_client: TestClient) -> None:
        _login(app_client)
        for bad in (-1, 1441):
            response = app_client.patch("/api/v1/settings", json={"daily_time_budget_minutes": self._week(bad)})
            assert response.status_code == 422, response.text
        ok = app_client.patch("/api/v1/settings", json={"daily_time_budget_minutes": self._week(0)})
        assert ok.status_code == 200, ok.text

    def test_a_blackout_range_cannot_end_before_it_starts_and_a_one_day_range_is_fine(self, app_client: TestClient) -> None:
        _login(app_client)
        backwards = app_client.patch("/api/v1/settings", json={"blackout_dates": [{"start": "2030-05-02", "end": "2030-05-01"}]})
        assert backwards.status_code == 422, backwards.text
        assert backwards.json()["code"] == "invalid_field"
        same_day = app_client.patch(
            "/api/v1/settings", json={"blackout_dates": [{"start": "2030-05-01", "end": "2030-05-01", "label": "x"}]}
        )
        assert same_day.status_code == 200, same_day.text
        too_long = app_client.patch(
            "/api/v1/settings",
            json={"blackout_dates": [{"start": "2030-05-01", "end": "2030-05-01", "label": "x" * 101}]},
        )
        assert too_long.status_code == 422, too_long.text
