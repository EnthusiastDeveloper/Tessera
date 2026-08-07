"""Placement invariant sanity checks. See design doc §6.2.

However candidates, obstacles, budgets, and blackout dates combine, three
invariants must always hold for every returned placement: no overlap with any
obstacle (pre-existing or placed earlier in the same pass), no placement outside
that day's effective active-hours window, and never on a blackout day.
"""

from datetime import timedelta

from app.scheduling_engine.calendar_rules import day_name, is_blacked_out
from app.scheduling_engine.placement import schedule_pending_flexible_tasks
from app.scheduling_engine.types import BlackoutDate, FlexibleTaskCandidate, Obstacle
from tests.fixtures.scheduling import every_day, no_budget, ny, ny_date

DURATION_MINUTES = 45


def test_placements_respect_obstacles_active_hours_and_blackout_dates() -> None:
    active_hours = every_day("09:00", "17:00")
    blackout_dates = [BlackoutDate(start=ny_date(2026, 3, 4), end=ny_date(2026, 3, 4))]  # Wednesday off
    obstacles = [
        Obstacle(ny(2026, 3, 2, 10, 0), ny(2026, 3, 2, 11, 0)),
        Obstacle(ny(2026, 3, 3, 9, 0), ny(2026, 3, 3, 12, 0)),
        Obstacle(ny(2026, 3, 5, 13, 0), ny(2026, 3, 5, 17, 0)),
    ]
    candidates = [
        FlexibleTaskCandidate(
            id=f"task-{i}",
            deadline=ny(2026, 3, 9, 17, 0),
            priority=(i % 4) + 1,
            estimated_duration_minutes=DURATION_MINUTES,
        )
        for i in range(10)
    ]

    result = schedule_pending_flexible_tasks(
        candidates=candidates,
        now=ny(2026, 3, 2, 8, 0),
        active_hours=active_hours,
        blackout_dates=blackout_dates,
        daily_time_budget_minutes=no_budget(),
        budget_enforcement="soft",
        obstacles=obstacles,
    )

    # The scenario is deliberately generous (8-hour daily windows, one week to
    # place ten 45-minute tasks) - if nothing got placed, the invariants below
    # would pass vacuously and prove nothing.
    assert len(result.placements) == len(candidates)

    placed_intervals = [(p.scheduled_start, p.scheduled_start + timedelta(minutes=DURATION_MINUTES)) for p in result.placements]

    for index, placement in enumerate(result.placements):
        start, end = placed_intervals[index]

        assert not is_blacked_out(start.date(), blackout_dates), f"{placement.task_id} placed on a blackout day"

        window = active_hours[day_name(start.date())]
        assert window is not None, f"{placement.task_id} placed on an excluded day"
        assert start.time() >= window.start, f"{placement.task_id} starts before the active-hours window"
        assert end.time() <= window.end, f"{placement.task_id} ends after the active-hours window"

        other_intervals = [(obstacle.start, obstacle.end) for obstacle in obstacles]
        other_intervals += [interval for other_index, interval in enumerate(placed_intervals) if other_index != index]
        for other_start, other_end in other_intervals:
            overlaps = start < other_end and other_start < end
            assert not overlaps, f"{placement.task_id} at [{start}, {end}) overlaps [{other_start}, {other_end})"
