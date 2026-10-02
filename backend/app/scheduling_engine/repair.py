"""Which placements stopped being valid when the scheduling rules got stricter. See
design doc §6.10 (Rev 11).

Placement is an incremental fit (§6.2): a valid placement is never moved. This module
answers the one question that rule leaves open - which existing placements are no longer
valid - using the same window, blackout and budget arithmetic `placement.py` places
with, so a repaired task can never be judged by rules the placer doesn't apply. Pure, like
the rest of the engine: it moves nothing, the service layer does.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, tzinfo

from app.scheduling_engine.calendar_rules import day_name, merge_active_hours
from app.scheduling_engine.placement import committed_minutes_for_day, eligible_window_for_day
from app.scheduling_engine.types import ActiveHoursMap, BlackoutDate, BudgetEnforcement, Obstacle


@dataclass(frozen=True)
class PlacedFlexibleTask:
    """A `scheduled` flexible instance's slot, in the user's local time."""

    id: str
    start: datetime
    end: datetime
    deadline: datetime
    priority: int
    active_hours_override: ActiveHoursMap | None = None


def placements_that_no_longer_fit(
    placed: Sequence[PlacedFlexibleTask],
    *,
    active_hours: ActiveHoursMap,
    blackout_dates: Sequence[BlackoutDate],
    daily_time_budget_minutes: Mapping[str, int | None],
    budget_enforcement: BudgetEnforcement,
    other_obstacles: Sequence[Obstacle],
) -> tuple[str, ...]:
    """The ids in `placed` that §6.10 says must be placed again, in the order to handle them.

    A placement no longer fits if its slot isn't entirely inside its day's effective
    active-hours window (the task's override merged over `active_hours`), or the day is
    excluded or blacked out. With `budget_enforcement == "strict"`, a day whose committed
    minutes - `other_obstacles` (fixed tasks, started work, external events) plus the
    placements still on it, counted as §6.2 counts them - exceed its budget sheds
    placements in the reverse of §6.2's placement order (latest deadline first, then
    lowest priority) until it is within budget. A soft budget is not a rule a placement
    can break (§6.2 Pass 2 may exceed it), so it never sheds anything.
    """
    outside: list[str] = []
    remaining: list[PlacedFlexibleTask] = []
    for task in placed:
        if _fits_its_window(task, active_hours=active_hours, blackout_dates=blackout_dates):
            remaining.append(task)
        else:
            outside.append(task.id)

    if budget_enforcement != "strict":
        return tuple(outside)

    by_day: dict[date, list[PlacedFlexibleTask]] = defaultdict(list)
    for task in remaining:
        by_day[task.start.date()].append(task)

    over_budget: list[str] = []
    for day in sorted(by_day):
        budget = daily_time_budget_minutes.get(day_name(day))
        if budget is None:
            continue
        # Kept in placement order, so shedding from the end sheds what §6.2 would place last.
        kept = sorted(by_day[day], key=lambda task: (task.deadline, -task.priority))
        tz = kept[0].start.tzinfo
        while kept and _committed(day, other_obstacles, kept, tz) > budget:
            over_budget.append(kept.pop().id)
    return (*outside, *over_budget)


def _fits_its_window(task: PlacedFlexibleTask, *, active_hours: ActiveHoursMap, blackout_dates: Sequence[BlackoutDate]) -> bool:
    day = task.start.date()
    window = eligible_window_for_day(day, merge_active_hours(active_hours, task.active_hours_override), blackout_dates)
    if window is None:
        return False
    tz = task.start.tzinfo
    return datetime.combine(day, window.start, tzinfo=tz) <= task.start and task.end <= datetime.combine(
        day, window.end, tzinfo=tz
    )


def _committed(day: date, other_obstacles: Sequence[Obstacle], kept: Sequence[PlacedFlexibleTask], tz: tzinfo | None) -> int:
    obstacles = [*other_obstacles, *(Obstacle(start=task.start, end=task.end) for task in kept)]
    return committed_minutes_for_day(day, sorted(obstacles, key=lambda obstacle: obstacle.start), tz)


__all__ = ["PlacedFlexibleTask", "placements_that_no_longer_fit"]
