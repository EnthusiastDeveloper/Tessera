"""Core placement algorithm. See design doc §6.2.

`find_first_free_slot` is Pass 1: a budget-respecting scan for the first
grid-aligned, obstacle-clear slot. `schedule_pending_flexible_tasks` drives the
full algorithm over a candidate list: stable sort by (deadline ASC, priority
DESC), Pass 1 per candidate, and - only in "soft" budget-enforcement mode - a
Pass 2 fallback that ignores the daily budget and picks the least-damaging day
via a three-key tie-break (overage, then remaining slack, then earliest date).

Placement is an incremental fit, not a reflow: existing placements (obstacles
passed in) are never moved, and each candidate placed in this pass becomes an
obstacle for the next one. This function is pure - it never mutates its inputs,
touches no clock, and creates no notifications; the service layer maps
`budget_overridden` and `unschedulable_task_ids` to the real side effects.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, datetime, time, timedelta, tzinfo

from app.scheduling_engine.calendar_rules import day_name, day_range, is_blacked_out, merge_active_hours
from app.scheduling_engine.grid import DEFAULT_GRID_MINUTES, ceil_to_grid
from app.scheduling_engine.types import (
    ActiveHoursMap,
    ActiveHoursWindow,
    BlackoutDate,
    BudgetEnforcement,
    FlexibleTaskCandidate,
    Obstacle,
    Placement,
    SchedulingResult,
)


def find_first_free_slot(
    *,
    duration_minutes: int,
    not_before: datetime,
    not_after: datetime,
    allowed_hours: ActiveHoursMap,
    excluded_dates: Sequence[BlackoutDate],
    daily_time_budget_minutes: Mapping[str, int | None] | None,
    obstacles: Sequence[Obstacle],
    grid_minutes: int = DEFAULT_GRID_MINUTES,
) -> datetime | None:
    """Pass 1 (§6.2): first grid-aligned start fitting `duration_minutes` in [not_before, not_after].

    Scans days in order. A day is skipped entirely (not partially considered) if
    it's blacked out, has no active-hours window, or - when
    `daily_time_budget_minutes` is provided - already-committed obstacle time on
    that day plus this task's duration would exceed that day's cap.

    `daily_time_budget_minutes=None` disables the budget check entirely for every
    day (used internally by Pass 2's physical-feasibility probe); a per-day value
    of `None` *inside* the mapping means that specific day has no cap.

    Inputs must be tz-aware (§14.1); all datetimes are assumed to share one
    tzinfo, ordinarily a `zoneinfo.ZoneInfo` so per-day wall-clock combination
    resolves DST correctly.
    """
    duration = timedelta(minutes=duration_minutes)
    for day in day_range(not_before.date(), not_after.date()):
        if is_blacked_out(day, excluded_dates):
            continue
        window = allowed_hours.get(day_name(day))
        if window is None:
            continue
        if daily_time_budget_minutes is not None:
            budget = daily_time_budget_minutes.get(day_name(day))
            if budget is not None:
                committed = _committed_minutes_for_day(day, obstacles, not_before.tzinfo)
                if committed + duration_minutes > budget:
                    continue
        slot = _first_slot_in_window(
            day=day,
            window=window,
            duration=duration,
            not_before=not_before,
            not_after=not_after,
            obstacles=obstacles,
            grid_minutes=grid_minutes,
        )
        if slot is not None:
            return slot
    return None


def schedule_pending_flexible_tasks(
    candidates: Sequence[FlexibleTaskCandidate],
    *,
    now: datetime,
    active_hours: ActiveHoursMap,
    blackout_dates: Sequence[BlackoutDate],
    daily_time_budget_minutes: Mapping[str, int | None],
    budget_enforcement: BudgetEnforcement,
    obstacles: Sequence[Obstacle],
    grid_minutes: int = DEFAULT_GRID_MINUTES,
) -> SchedulingResult:
    """Place every candidate, in (deadline ASC, priority DESC) order (§6.2).

    No topological sort: the `blocked` status gate already guarantees every
    candidate's dependencies are `completed` before it becomes a candidate, so no
    candidate can depend on another candidate (§6.1). `active_hours` is the
    global settings map; each candidate's own `active_hours_override` is merged
    over it per-task, matching §6.2's `effective_hours(day)`.
    """
    ordered = sorted(candidates, key=lambda task: (task.deadline, -task.priority))
    working_obstacles = list(obstacles)
    placements: list[Placement] = []
    unschedulable: list[str] = []

    for task in ordered:
        earliest_start = max(now, max(task.dependency_completed_at, default=now))
        effective_hours = merge_active_hours(active_hours, task.active_hours_override)

        slot = find_first_free_slot(
            duration_minutes=task.estimated_duration_minutes,
            not_before=earliest_start,
            not_after=task.deadline,
            allowed_hours=effective_hours,
            excluded_dates=blackout_dates,
            daily_time_budget_minutes=daily_time_budget_minutes,
            obstacles=working_obstacles,
            grid_minutes=grid_minutes,
        )
        budget_overridden = False

        if slot is None and budget_enforcement == "soft":
            slot, budget_overridden = _pass_two(
                task=task,
                earliest_start=earliest_start,
                effective_hours=effective_hours,
                blackout_dates=blackout_dates,
                daily_time_budget_minutes=daily_time_budget_minutes,
                obstacles=working_obstacles,
                grid_minutes=grid_minutes,
            )

        if slot is not None:
            placements.append(Placement(task_id=task.id, scheduled_start=slot, budget_overridden=budget_overridden))
            working_obstacles.append(Obstacle(start=slot, end=slot + timedelta(minutes=task.estimated_duration_minutes)))
        else:
            unschedulable.append(task.id)

    return SchedulingResult(placements=tuple(placements), unschedulable_task_ids=tuple(unschedulable))


def _pass_two(
    *,
    task: FlexibleTaskCandidate,
    earliest_start: datetime,
    effective_hours: ActiveHoursMap,
    blackout_dates: Sequence[BlackoutDate],
    daily_time_budget_minutes: Mapping[str, int | None],
    obstacles: Sequence[Obstacle],
    grid_minutes: int,
) -> tuple[datetime | None, bool]:
    """Pass 2 (§6.2): budget-ignoring fallback, three-key tie-break.

    Only reached from `schedule_pending_flexible_tasks` when Pass 1 fails and
    `budget_enforcement == "soft"`. Considers every day in [earliest_start,
    deadline] with a *physically* free slot (budget aside) and picks the one
    minimizing, in order: (1) overage against that day's budget, (2) negated
    remaining free capacity in the window after this task would land (i.e.
    maximize slack), (3) earliest date.
    """
    duration = timedelta(minutes=task.estimated_duration_minutes)
    tz = earliest_start.tzinfo

    best_slot: datetime | None = None
    best_key: tuple[float, float, date] | None = None

    for day in day_range(earliest_start.date(), task.deadline.date()):
        if is_blacked_out(day, blackout_dates):
            continue
        window = effective_hours.get(day_name(day))
        if window is None:
            continue
        slot = _first_slot_in_window(
            day=day,
            window=window,
            duration=duration,
            not_before=earliest_start,
            not_after=task.deadline,
            obstacles=obstacles,
            grid_minutes=grid_minutes,
        )
        if slot is None:
            continue

        cap = daily_time_budget_minutes.get(day_name(day))
        committed = _committed_minutes_for_day(day, obstacles, tz)
        overage = max(0.0, committed + task.estimated_duration_minutes - cap) if cap is not None else 0.0
        remaining_after = _free_capacity_in_window(day, window, obstacles, tz) - task.estimated_duration_minutes
        key = (overage, float(-remaining_after), day)

        if best_key is None or key < best_key:
            best_key = key
            best_slot = slot

    return best_slot, best_slot is not None


def _first_slot_in_window(
    *,
    day: date,
    window: ActiveHoursWindow,
    duration: timedelta,
    not_before: datetime,
    not_after: datetime,
    obstacles: Sequence[Obstacle],
    grid_minutes: int,
) -> datetime | None:
    """The earliest grid-aligned start on `day` that fits `duration` clear of obstacles.

    The chosen start `t` satisfies `t >= gap_start`, `t + duration <= gap_end`,
    `t + duration <= not_after` (the deadline), and `t + duration <=` the window's
    end - exactly §6.2's placement-grid rule.
    """
    tz = not_before.tzinfo
    window_start = datetime.combine(day, window.start, tzinfo=tz)
    window_end = datetime.combine(day, window.end, tzinfo=tz)
    search_from = max(window_start, not_before)
    limit = min(window_end, not_after)

    cursor = ceil_to_grid(search_from, grid_minutes)
    if cursor + duration > limit:
        return None

    relevant = sorted(
        (obstacle for obstacle in obstacles if obstacle.end > search_from and obstacle.start < window_end),
        key=lambda obstacle: obstacle.start,
    )
    for obstacle in relevant:
        if cursor + duration <= obstacle.start:
            return cursor
        if obstacle.end > cursor:
            cursor = ceil_to_grid(obstacle.end, grid_minutes)
        if cursor + duration > limit:
            return None

    return cursor if cursor + duration <= limit else None


def _committed_minutes_for_day(day: date, obstacles: Sequence[Obstacle], tz: tzinfo | None) -> int:
    """Total obstacle-occupied minutes anywhere in the calendar day `day` (§6.2 budget accounting).

    Whole-day, not window-scoped: fixed tasks and external events count against a
    day's budget even if they fall outside the active-hours window (§3.7).
    """
    day_start = datetime.combine(day, time.min, tzinfo=tz)
    day_end = day_start + timedelta(days=1)
    clipped = [
        (max(obstacle.start, day_start), min(obstacle.end, day_end))
        for obstacle in obstacles
        if obstacle.start < day_end and obstacle.end > day_start
    ]
    return _summed_minutes(clipped)


def _free_capacity_in_window(day: date, window: ActiveHoursWindow, obstacles: Sequence[Obstacle], tz: tzinfo | None) -> int:
    """Free minutes remaining inside `day`'s active-hours window, obstacles merged (§6.2 Pass 2 slack key)."""
    window_start = datetime.combine(day, window.start, tzinfo=tz)
    window_end = datetime.combine(day, window.end, tzinfo=tz)
    window_minutes = int((window_end - window_start).total_seconds() // 60)
    clipped = [
        (max(obstacle.start, window_start), min(obstacle.end, window_end))
        for obstacle in obstacles
        if obstacle.start < window_end and obstacle.end > window_start
    ]
    return max(0, window_minutes - _summed_minutes(clipped))


def _summed_minutes(intervals: list[tuple[datetime, datetime]]) -> int:
    """Sum interval durations in minutes, merging overlaps first so double-booked obstacles aren't double-counted."""
    if not intervals:
        return 0
    ordered = sorted(intervals, key=lambda interval: interval[0])
    merged = [ordered[0]]
    for start, end in ordered[1:]:
        last_start, last_end = merged[-1]
        if start <= last_end:
            merged[-1] = (last_start, max(last_end, end))
        else:
            merged.append((start, end))
    return sum(int((end - start).total_seconds() // 60) for start, end in merged)
