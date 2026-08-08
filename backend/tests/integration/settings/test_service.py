"""Integration tests for app.settings.service against a real (in-memory) SQLite DB.

See design doc §3.7, implementation-plan Stage 4. Uses the `db_session` fixture from
`tests/integration/conftest.py`.
"""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from app.settings import service


class TestGetOrCreateDefault:
    def test_creates_a_default_row_on_first_call(self, db_session: Session) -> None:
        created = service.get_or_create_default(db_session, default_timezone="America/Chicago")
        assert created.timezone == "America/Chicago"
        assert created.budget_enforcement == "soft"
        assert created.first_day_of_week == "monday"
        assert created.blackout_dates == ()
        assert created.active_hours == service.DEFAULT_ACTIVE_HOURS
        assert created.daily_time_budget_minutes == service.DEFAULT_DAILY_TIME_BUDGET

    def test_second_call_returns_the_existing_row_unchanged(self, db_session: Session) -> None:
        first = service.get_or_create_default(db_session, default_timezone="America/Chicago")
        second = service.get_or_create_default(db_session, default_timezone="Europe/London")
        assert second == first  # the second call's default_timezone must NOT overwrite it


class TestUpdateSettings:
    def test_partial_update_touches_only_the_given_field(self, db_session: Session) -> None:
        service.get_or_create_default(db_session, default_timezone="UTC")
        updated = service.update_settings(db_session, patch={"timezone": "Asia/Tokyo"})
        assert updated.timezone == "Asia/Tokyo"
        assert updated.budget_enforcement == "soft"
        assert updated.first_day_of_week == "monday"
        assert updated.active_hours == service.DEFAULT_ACTIVE_HOURS

    def test_rejects_invalid_timezone(self, db_session: Session) -> None:
        service.get_or_create_default(db_session, default_timezone="UTC")
        with pytest.raises(service.SettingsValidationError) as exc_info:
            service.update_settings(db_session, patch={"timezone": "Not/A/Zone"})
        assert exc_info.value.code == "invalid_timezone"

    def test_rejects_active_hours_missing_a_day(self, db_session: Session) -> None:
        service.get_or_create_default(db_session, default_timezone="UTC")
        incomplete = {k: v for k, v in service.DEFAULT_ACTIVE_HOURS.items() if k != "sunday"}
        with pytest.raises(service.SettingsValidationError) as exc_info:
            service.update_settings(db_session, patch={"active_hours": incomplete})
        assert exc_info.value.code == "invalid_day_map"

    def test_rejects_active_hours_with_an_unexpected_key(self, db_session: Session) -> None:
        service.get_or_create_default(db_session, default_timezone="UTC")
        bad = {**service.DEFAULT_ACTIVE_HOURS, "someday": None}
        with pytest.raises(service.SettingsValidationError) as exc_info:
            service.update_settings(db_session, patch={"active_hours": bad})
        assert exc_info.value.code == "invalid_day_map"

    def test_rejects_daily_time_budget_missing_a_day(self, db_session: Session) -> None:
        service.get_or_create_default(db_session, default_timezone="UTC")
        incomplete = {k: v for k, v in service.DEFAULT_DAILY_TIME_BUDGET.items() if k != "monday"}
        with pytest.raises(service.SettingsValidationError) as exc_info:
            service.update_settings(db_session, patch={"daily_time_budget_minutes": incomplete})
        assert exc_info.value.code == "invalid_day_map"

    def test_full_valid_active_hours_map_is_accepted(self, db_session: Session) -> None:
        service.get_or_create_default(db_session, default_timezone="UTC")
        new_hours = {**service.DEFAULT_ACTIVE_HOURS, "saturday": None}
        updated = service.update_settings(db_session, patch={"active_hours": new_hours})
        assert updated.active_hours["saturday"] is None
        assert updated.active_hours["monday"] == service.DEFAULT_ACTIVE_HOURS["monday"]

    def test_full_valid_daily_time_budget_map_is_accepted(self, db_session: Session) -> None:
        service.get_or_create_default(db_session, default_timezone="UTC")
        new_budget = {**service.DEFAULT_DAILY_TIME_BUDGET, "monday": 120}
        updated = service.update_settings(db_session, patch={"daily_time_budget_minutes": new_budget})
        assert updated.daily_time_budget_minutes["monday"] == 120
        assert updated.daily_time_budget_minutes["tuesday"] is None

    def test_budget_enforcement_can_be_updated(self, db_session: Session) -> None:
        service.get_or_create_default(db_session, default_timezone="UTC")
        updated = service.update_settings(db_session, patch={"budget_enforcement": "strict"})
        assert updated.budget_enforcement == "strict"

    def test_raises_when_no_settings_row_exists_yet(self, db_session: Session) -> None:
        with pytest.raises(service.SettingsValidationError) as exc_info:
            service.update_settings(db_session, patch={"timezone": "UTC"})
        assert exc_info.value.code == "settings_not_initialized"
