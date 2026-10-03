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

from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone, tzinfo

from app.scheduling_engine.calendar_rules import Interval, day_name, day_range, eligible_intervals, merge_active_hours
from app.scheduling_engine.fixed_conflicts import intervals_overlap
from app.scheduling_engine.grid import DEFAULT_GRID_MINUTES, ceil_to_grid
from app.scheduling_engine.types import (
    ActiveHoursMap,
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

    Scans the eligible stretches of time in order, one candidate per calendar date a
    stretch covers (the first slot that *starts* on that date; it may run past midnight
    inside an overnight stretch). A date contributes nothing if it is blacked out or has
    no window - when `daily_time_budget_minutes` is provided, a slot is also passed over if
    the obstacle time already committed on any date it touches, plus the task's minutes on
    that date, would exceed that date's cap.

    `daily_time_budget_minutes=None` disables the budget check entirely for every
    day (used internally by Pass 2's physical-feasibility probe); a per-day value
    of `None` *inside* the mapping means that specific day has no cap.

    Inputs must be tz-aware (§14.1); all datetimes are assumed to share one
    tzinfo, ordinarily a `zoneinfo.ZoneInfo` so per-day wall-clock combination
    resolves DST correctly.
    """
    duration = timedelta(minutes=duration_minutes)
    sorted_obstacles = sorted(obstacles, key=lambda obstacle: obstacle.start)
    within_budget = (
        None
        if daily_time_budget_minutes is None
        else lambda slot: not _budget_overage(slot, duration, daily_time_budget_minutes, sorted_obstacles)
    )
    for candidate in _candidates(
        duration=duration,
        not_before=not_before,
        not_after=not_after,
        allowed_hours=allowed_hours,
        excluded_dates=excluded_dates,
        obstacles=sorted_obstacles,
        grid_minutes=grid_minutes,
        accept=within_budget,
    ):
        return candidate.slot
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
        earliest_start = max(now, max(task.dependency_completed_at, default=now), task.not_before or now)
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
    minimizing, in order: (1) overage against the budgets of the dates the slot touches,
    (2) negated remaining free capacity in that date's part of the stretch after this
    task would land (i.e. maximize slack), (3) earliest date.
    """
    duration = timedelta(minutes=task.estimated_duration_minutes)
    sorted_obstacles = sorted(obstacles, key=lambda obstacle: obstacle.start)

    best_slot: datetime | None = None
    best_key: tuple[float, float, date] | None = None

    for candidate in _candidates(
        duration=duration,
        not_before=earliest_start,
        not_after=task.deadline,
        allowed_hours=effective_hours,
        excluded_dates=blackout_dates,
        obstacles=sorted_obstacles,
        grid_minutes=grid_minutes,
    ):
        overage = _budget_overage(candidate.slot, duration, daily_time_budget_minutes, sorted_obstacles)
        remaining_after = _free_capacity(candidate.segment, sorted_obstacles) - task.estimated_duration_minutes
        key = (float(overage), float(-remaining_after), candidate.day)

        if best_key is None or key < best_key:
            best_key = key
            best_slot = candidate.slot

    return best_slot, best_slot is not None


@dataclass(frozen=True)
class _Candidate:
    """The first slot that starts on `day` inside one eligible stretch.

    `segment` is the stretch clipped to `day` - the day's part of the window(s) the slot
    sits in, which Pass 2 measures slack against.
    """

    day: date
    slot: datetime
    segment: Interval


def _candidates(
    *,
    duration: timedelta,
    not_before: datetime,
    not_after: datetime,
    allowed_hours: ActiveHoursMap,
    excluded_dates: Sequence[BlackoutDate],
    obstacles: Sequence[Obstacle],
    grid_minutes: int,
    accept: Callable[[datetime], bool] | None = None,
) -> Iterator[_Candidate]:
    """Per calendar date, in order, the first obstacle-clear grid slot inside the eligible time (§6.2).

    Shared by Pass 1 and Pass 2 so the two can't silently diverge on which dates and
    stretches are in play. `obstacles` must already be sorted by `start`.

    With `accept` (Pass 1's budget test), a date yields its first slot that `accept` allows.
    Where nothing can run past midnight a date's slots all fare alike, so the first one
    decides; where it can, a later slot may spend fewer minutes on the next date's budget
    than an earlier one, so the search carries on grid point by grid point.
    """
    tz = not_before.tzinfo
    intervals = eligible_intervals(not_before.date(), not_after.date(), allowed_hours, excluded_dates, tz)
    for interval_start, interval_end in intervals:
        limit = min(interval_end, not_after)
        first = max(interval_start, not_before)
        if first >= limit:
            continue
        for day in day_range(first.date(), limit.date()):
            day_start = datetime.combine(day, time.min, tzinfo=tz)
            next_day_start = datetime.combine(day + timedelta(days=1), time.min, tzinfo=tz)
            search_from = max(first, day_start)
            while True:
                slot = _first_slot(
                    search_from=search_from,
                    start_before=next_day_start,
                    stretch_end=interval_end,
                    limit=limit,
                    duration=duration,
                    obstacles=obstacles,
                    grid_minutes=grid_minutes,
                )
                if slot is None:
                    break
                if accept is None or accept(slot):
                    yield _Candidate(
                        day=day,
                        slot=slot,
                        segment=(max(interval_start, day_start), min(interval_end, next_day_start)),
                    )
                    break
                if limit <= next_day_start:
                    break
                search_from = slot + timedelta(minutes=grid_minutes)


def _first_slot(
    *,
    search_from: datetime,
    start_before: datetime,
    stretch_end: datetime,
    limit: datetime,
    duration: timedelta,
    obstacles: Sequence[Obstacle],
    grid_minutes: int,
) -> datetime | None:
    """The earliest grid-aligned start in [search_from, start_before) that fits `duration` clear of obstacles.

    The chosen start `t` satisfies `t >= gap_start`, `t + duration <= gap_end` and
    `t + duration <= limit` (the stretch's end or the deadline, whichever is first) -
    exactly §6.2's placement-grid rule. `obstacles` must already be sorted by `start`.
    """
    cursor = ceil_to_grid(search_from, grid_minutes)
    if cursor >= start_before or cursor + duration > limit:
        return None

    relevant = [obstacle for obstacle in obstacles if intervals_overlap(search_from, stretch_end, obstacle.start, obstacle.end)]
    for obstacle in relevant:
        if cursor + duration <= obstacle.start:
            break
        if obstacle.end > cursor:
            cursor = ceil_to_grid(obstacle.end, grid_minutes)
        if cursor >= start_before or cursor + duration > limit:
            return None

    return cursor if cursor < start_before and cursor + duration <= limit else None


def _budget_overage(slot: datetime, duration: timedelta, budget: Mapping[str, int | None], obstacles: Sequence[Obstacle]) -> int:
    """Minutes by which placing `duration` at `slot` would exceed the budget of the dates it touches (§6.2).

    Obstacles are counted by calendar date, so a task that runs past midnight is counted
    on each date for the minutes it spends there. A date with no cap contributes nothing.
    """
    tz = slot.tzinfo
    end = slot + duration
    overage = 0
    for day in day_range(slot.date(), end.date()):
        day_start = datetime.combine(day, time.min, tzinfo=tz)
        next_day_start = day_start + timedelta(days=1)
        minutes_here = _elapsed_minutes(max(slot, day_start), min(end, next_day_start))
        cap = budget.get(day_name(day))
        if minutes_here > 0 and cap is not None:
            overage += max(0, committed_minutes_for_day(day, obstacles, tz) + minutes_here - cap)
    return overage


def committed_minutes_for_day(day: date, obstacles: Sequence[Obstacle], tz: tzinfo | None) -> int:
    """Total obstacle-occupied minutes anywhere in the calendar day `day` (§6.2 budget accounting).

    Whole-day, not window-scoped: fixed tasks and external events count against a
    day's budget even if they fall outside the active-hours window (§3.7).
    """
    day_start = datetime.combine(day, time.min, tzinfo=tz)
    day_end = day_start + timedelta(days=1)
    return _summed_minutes(_clip_obstacles(obstacles, day_start, day_end))


def _free_capacity(segment: Interval, obstacles: Sequence[Obstacle]) -> int:
    """Free minutes left in `segment` once obstacles are merged out (§6.2 Pass 2 slack key)."""
    start, end = segment
    return max(0, _elapsed_minutes(start, end) - _summed_minutes(_clip_obstacles(obstacles, start, end)))


def _clip_obstacles(obstacles: Sequence[Obstacle], bound_start: datetime, bound_end: datetime) -> list[tuple[datetime, datetime]]:
    """Clip each obstacle overlapping [bound_start, bound_end) to that range.

    Shared by `committed_minutes_for_day` (whole-day bound) and
    `_free_capacity_in_window` (active-hours-window bound). `obstacles` must
    already be sorted by `start`; clipping via `max`/`min` against a fixed bound
    is monotonic in each obstacle's own start, so the result stays sorted too and
    `_summed_minutes` doesn't need to re-sort.
    """
    return [
        (max(obstacle.start, bound_start), min(obstacle.end, bound_end))
        for obstacle in obstacles
        if intervals_overlap(bound_start, bound_end, obstacle.start, obstacle.end)
    ]


def _summed_minutes(intervals: list[tuple[datetime, datetime]]) -> int:
    """Sum interval durations in minutes, merging overlaps first so double-booked obstacles aren't double-counted.

    `intervals` must already be sorted by start (guaranteed by `_clip_obstacles`).
    """
    if not intervals:
        return 0
    merged = [intervals[0]]
    for start, end in intervals[1:]:
        last_start, last_end = merged[-1]
        if start <= last_end:
            merged[-1] = (last_start, max(last_end, end))
        else:
            merged.append((start, end))
    return sum(_elapsed_minutes(start, end) for start, end in merged)


def _elapsed_minutes(start: datetime, end: datetime) -> int:
    """Minutes between two aware instants, correct across DST transitions (design doc §14.1).

    Plain subtraction of two aware datetimes silently takes a naive wall-clock
    shortcut whenever they share the same tzinfo *object* - which `zoneinfo.ZoneInfo`
    does by default (it caches one instance per IANA key), so this isn't a rare
    case, it's the normal one. That shortcut ignores any DST transition between
    the two instants. Converting both to a fixed offset (UTC) first sidesteps it
    and always reflects real elapsed time, matching 14.1's "handled by the
    library, not custom code" rule.
    """
    return int((end.astimezone(timezone.utc) - start.astimezone(timezone.utc)).total_seconds() // 60)
