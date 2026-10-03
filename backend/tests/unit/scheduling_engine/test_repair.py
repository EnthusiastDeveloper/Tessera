"""Unit tests for app.scheduling_engine.repair (design doc §6.10, Rev 11)."""

from datetime import datetime, timedelta

from app.scheduling_engine.repair import PlacedFlexibleTask, placements_that_no_longer_fit
from app.scheduling_engine.types import BlackoutDate, Obstacle
from tests.fixtures.scheduling import every_day, no_budget, ny, ny_date, window

# Mon 2026-03-02 .. Sun 2026-03-08, New York.


def _task(
    task_id: str, start: datetime, minutes: int = 60, *, deadline_day: int = 10, priority: int = 2, **kwargs: object
) -> PlacedFlexibleTask:
    return PlacedFlexibleTask(
        id=task_id,
        start=start,
        end=start + timedelta(minutes=minutes),
        deadline=ny(2026, 3, deadline_day, 0, 0),
        priority=priority,
        **kwargs,  # type: ignore[arg-type]
    )


def _check(placed: list[PlacedFlexibleTask], **overrides: object) -> tuple[str, ...]:
    arguments: dict[str, object] = {
        "active_hours": every_day("09:00", "17:00"),
        "blackout_dates": [],
        "daily_time_budget_minutes": no_budget(),
        "budget_enforcement": "soft",
        "other_obstacles": [],
    }
    arguments.update(overrides)
    return placements_that_no_longer_fit(placed, **arguments)  # type: ignore[arg-type]


def test_a_slot_inside_its_window_still_fits() -> None:
    assert _check([_task("a", ny(2026, 3, 2, 9, 0)), _task("b", ny(2026, 3, 2, 16, 0))]) == ()


def test_a_slot_poking_past_a_narrowed_window_no_longer_fits() -> None:
    placed = [_task("early", ny(2026, 3, 2, 9, 0)), _task("late", ny(2026, 3, 2, 15, 30))]
    assert _check(placed, active_hours=every_day("09:00", "16:00")) == ("late",)


def test_a_slot_starting_before_a_later_window_opens_no_longer_fits() -> None:
    assert _check([_task("a", ny(2026, 3, 2, 9, 0))], active_hours=every_day("10:00", "17:00")) == ("a",)


def test_an_excluded_day_or_blackout_date_no_longer_fits() -> None:
    monday, tuesday = _task("mon", ny(2026, 3, 2, 10, 0)), _task("tue", ny(2026, 3, 3, 10, 0))
    no_mondays = {**every_day("09:00", "17:00"), "monday": None}
    assert _check([monday, tuesday], active_hours=no_mondays) == ("mon",)
    blackout = [BlackoutDate(start=ny_date(2026, 3, 3), end=ny_date(2026, 3, 3))]
    assert _check([monday, tuesday], blackout_dates=blackout) == ("tue",)


def test_the_tasks_own_override_is_merged_over_the_global_hours() -> None:
    evening = _task("evening", ny(2026, 3, 2, 19, 0), active_hours_override={"monday": [window("18:00", "21:00")]})
    assert _check([evening]) == ()
    narrowed = _task("evening", ny(2026, 3, 2, 19, 0), active_hours_override={"monday": [window("18:00", "19:30")]})
    assert _check([narrowed]) == ("evening",)


def test_a_soft_budget_never_sheds_anything() -> None:
    placed = [_task("a", ny(2026, 3, 2, 9, 0)), _task("b", ny(2026, 3, 2, 10, 0))]
    assert _check(placed, daily_time_budget_minutes={"monday": 30}) == ()


def test_a_strict_budget_sheds_the_latest_deadline_then_lowest_priority_first() -> None:
    placed = [
        _task("due-soon", ny(2026, 3, 2, 9, 0), deadline_day=4),
        _task("due-later-high", ny(2026, 3, 2, 10, 0), deadline_day=9, priority=4),
        _task("due-later-low", ny(2026, 3, 2, 11, 0), deadline_day=9, priority=1),
    ]
    # A 60-minute fixed task elsewhere that day counts too: 60 + 3 x 60 = 240 > 150.
    fixed = [Obstacle(start=ny(2026, 3, 2, 19, 0), end=ny(2026, 3, 2, 20, 0))]
    result = _check(placed, budget_enforcement="strict", daily_time_budget_minutes={"monday": 150}, other_obstacles=fixed)
    assert result == ("due-later-low", "due-later-high")


def test_a_day_with_no_budget_is_never_over_it() -> None:
    placed = [_task(str(hour), ny(2026, 3, 2, hour, 0)) for hour in range(9, 17)]
    assert _check(placed, budget_enforcement="strict", daily_time_budget_minutes={"monday": None}) == ()
