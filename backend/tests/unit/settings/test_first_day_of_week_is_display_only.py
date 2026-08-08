"""Regression guard: `first_day_of_week` must have zero effect on scheduling output.

See design doc §3.7: "`first_day_of_week` affects display only ... It has no effect on
scheduling algorithm behavior: those fields are already keyed by day name rather than
position-in-week, so the algorithm doesn't have a concept of 'week' to reorder in the
first place." Stage 4's own "Tests required" calls for two `UserSettings` identical
except for `first_day_of_week`, fed through Stage 1's engine functions directly.

The translation from `UserSettings.active_hours` (§3.7's wire shape, "HH:MM" strings)
into the engine's `ActiveHoursMap` (`datetime.time` values, see scheduling_engine.types)
is deliberately kept local to this test, not production code - wiring settings into
actual scheduling calls is Stage 5's job (implementation-plan Stage 4 "Out of scope").
This is just enough translation to exercise a real engine function with real settings
data, per the test Stage 4 asks for.
"""

from __future__ import annotations

from app.db.base import generate_id
from app.db.schemas import UserSettings
from app.scheduling_engine.placement import find_first_free_slot
from app.scheduling_engine.types import ActiveHoursMap
from app.settings.service import DEFAULT_ACTIVE_HOURS, DEFAULT_DAILY_TIME_BUDGET
from tests.fixtures.scheduling import ny, window


def _make_settings(*, first_day_of_week: str) -> UserSettings:
    return UserSettings(
        id=generate_id(),
        timezone="America/New_York",
        active_hours=dict(DEFAULT_ACTIVE_HOURS),
        blackout_dates=(),
        daily_time_budget_minutes=dict(DEFAULT_DAILY_TIME_BUDGET),
        budget_enforcement="soft",
        first_day_of_week=first_day_of_week,  # type: ignore[arg-type]
    )


def _to_engine_active_hours(settings: UserSettings) -> ActiveHoursMap:
    return {day: (window(w.start, w.end) if w is not None else None) for day, w in settings.active_hours.items()}


def test_find_first_free_slot_is_identical_regardless_of_first_day_of_week() -> None:
    monday_first = _make_settings(first_day_of_week="monday")
    sunday_first = _make_settings(first_day_of_week="sunday")

    # Sanity check the fixture actually differs only in the field under test (id is
    # freshly generated per call, so it's excluded from this comparison on purpose).
    assert monday_first.model_copy(update={"id": sunday_first.id, "first_day_of_week": "sunday"}) == sunday_first

    not_before = ny(2026, 3, 2, 0, 0)  # a Monday
    not_after = ny(2026, 3, 16, 0, 0)

    result_monday_first = find_first_free_slot(
        duration_minutes=60,
        not_before=not_before,
        not_after=not_after,
        allowed_hours=_to_engine_active_hours(monday_first),
        excluded_dates=(),
        daily_time_budget_minutes=None,
        obstacles=(),
    )
    result_sunday_first = find_first_free_slot(
        duration_minutes=60,
        not_before=not_before,
        not_after=not_after,
        allowed_hours=_to_engine_active_hours(sunday_first),
        excluded_dates=(),
        daily_time_budget_minutes=None,
        obstacles=(),
    )

    assert result_monday_first is not None
    assert result_monday_first == result_sunday_first
    assert result_monday_first == ny(2026, 3, 2, 9, 0)  # first grid point inside the 09:00-17:00 window


def test_active_hours_translation_is_unaffected_by_first_day_of_week() -> None:
    monday_first = _make_settings(first_day_of_week="monday")
    sunday_first = _make_settings(first_day_of_week="sunday")
    assert _to_engine_active_hours(monday_first) == _to_engine_active_hours(sunday_first)
