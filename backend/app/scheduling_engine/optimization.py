"""The plan behind "Optimize Schedule". See design doc §6.11 (Rev 14).

Placement is an incremental fit (§6.2); this module answers what a *global* pass would
change. It runs the ordinary placement algorithm over every candidate with their own
present slots taken away, then compares the outcome with today's schedule and classifies
it: nothing to do, safe to apply at once, or needing the user's approval. Pure, like the
rest of the engine - it writes nothing and moves nothing, the service layer does.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Literal

from app.scheduling_engine.calendar_rules import day_name, day_range
from app.scheduling_engine.grid import DEFAULT_GRID_MINUTES, add_elapsed
from app.scheduling_engine.placement import committed_minutes_for_day, schedule_pending_flexible_tasks
from app.scheduling_engine.types import (
    ActiveHoursMap,
    BlackoutDate,
    BudgetEnforcement,
    FlexibleTaskCandidate,
    Obstacle,
)

type OptimizationResult = Literal["nothing_to_do", "applied", "needs_approval"]
type NothingToDoReason = Literal["identical", "would_place_fewer"]


@dataclass(frozen=True)
class CurrentSlot:
    """Where a `scheduled` candidate sits today."""

    start: datetime
    duration_minutes: int


@dataclass(frozen=True)
class Move:
    task_id: str
    from_start: datetime
    to_start: datetime
    newly_over_budget: bool = False


@dataclass(frozen=True)
class NewPlacement:
    task_id: str
    to_start: datetime
    newly_over_budget: bool = False


@dataclass(frozen=True)
class Loss:
    task_id: str
    from_start: datetime


@dataclass(frozen=True)
class OptimizationPlan:
    """Every candidate's outcome. `unchanged` and `still_unplaced` are ids only - the user is
    told how many, not which. `newly_over_budget_unchanged` lists tasks that keep their slot
    but now sit on a day over its budget because the tasks around them moved."""

    moved: tuple[Move, ...]
    newly_scheduled: tuple[NewPlacement, ...]
    lost: tuple[Loss, ...]
    unchanged: tuple[str, ...]
    still_unplaced: tuple[str, ...]
    newly_over_budget_unchanged: tuple[str, ...]
    placed_before: int
    placed_after: int

    @property
    def over_budget_ids(self) -> tuple[str, ...]:
        """Everything that is newly on a day over its budget, wherever it ended up."""
        return (
            *(m.task_id for m in self.moved if m.newly_over_budget),
            *(p.task_id for p in self.newly_scheduled if p.newly_over_budget),
            *self.newly_over_budget_unchanged,
        )

    @property
    def has_degradation(self) -> bool:
        """Something the user had that they would no longer have (§6.11)."""
        return bool(self.lost or self.over_budget_ids)

    @property
    def changes_anything(self) -> bool:
        return bool(self.moved or self.newly_scheduled or self.lost or self.newly_over_budget_unchanged)

    def signature(self) -> tuple[object, ...]:
        """What approval is for: if a recomputed plan has a different signature the user was
        shown something that is no longer what would happen."""
        return (
            tuple(sorted((m.task_id, m.from_start, m.to_start, m.newly_over_budget) for m in self.moved)),
            tuple(sorted((p.task_id, p.to_start, p.newly_over_budget) for p in self.newly_scheduled)),
            tuple(sorted((x.task_id, x.from_start) for x in self.lost)),
            tuple(sorted(self.newly_over_budget_unchanged)),
        )

    def classify(self) -> tuple[OptimizationResult, NothingToDoReason | None]:
        """§6.11's three results, with the reason when there is nothing to do."""
        if self.placed_after < self.placed_before:
            return "nothing_to_do", "would_place_fewer"
        if not self.changes_anything:
            return "nothing_to_do", "identical"
        if self.has_degradation:
            return "needs_approval", None
        return "applied", None


def plan_optimization(
    candidates: Sequence[FlexibleTaskCandidate],
    current: Mapping[str, CurrentSlot],
    *,
    now: datetime,
    active_hours: ActiveHoursMap,
    blackout_dates: Sequence[BlackoutDate],
    daily_time_budget_minutes: Mapping[str, int | None],
    budget_enforcement: BudgetEnforcement,
    obstacles: Sequence[Obstacle],
    grid_minutes: int = DEFAULT_GRID_MINUTES,
) -> OptimizationPlan:
    """`candidates` are every `scheduled` and `pending` flexible task; `current` holds the slot
    of each `scheduled` one. `obstacles` must **not** contain the candidates' own slots - they
    are what is being re-decided - but must hold everything that stays put (§6.11)."""
    result = schedule_pending_flexible_tasks(
        candidates,
        now=now,
        active_hours=active_hours,
        blackout_dates=blackout_dates,
        daily_time_budget_minutes=daily_time_budget_minutes,
        budget_enforcement=budget_enforcement,
        obstacles=obstacles,
        grid_minutes=grid_minutes,
    )
    duration = {task.id: task.estimated_duration_minutes for task in candidates}
    new_slots = {p.task_id: p.scheduled_start for p in result.placements}

    over_before = _over_budget_ids(
        {task_id: (slot.start, slot.duration_minutes) for task_id, slot in current.items()},
        obstacles,
        daily_time_budget_minutes,
    )
    over_after = _over_budget_ids(
        {task_id: (start, duration[task_id]) for task_id, start in new_slots.items()},
        obstacles,
        daily_time_budget_minutes,
    )

    moved: list[Move] = []
    newly_scheduled: list[NewPlacement] = []
    lost: list[Loss] = []
    unchanged: list[str] = []
    still_unplaced: list[str] = []
    over_unchanged: list[str] = []
    for task in candidates:
        was, now_at = current.get(task.id), new_slots.get(task.id)
        newly_over = task.id in over_after and task.id not in over_before
        if was is not None and now_at is not None:
            if was.start == now_at:
                unchanged.append(task.id)
                if newly_over:
                    over_unchanged.append(task.id)
            else:
                moved.append(Move(task.id, was.start, now_at, newly_over))
        elif was is not None:
            lost.append(Loss(task.id, was.start))
        elif now_at is not None:
            newly_scheduled.append(NewPlacement(task.id, now_at, newly_over))
        else:
            still_unplaced.append(task.id)

    return OptimizationPlan(
        moved=tuple(sorted(moved, key=lambda m: m.to_start)),
        newly_scheduled=tuple(sorted(newly_scheduled, key=lambda p: p.to_start)),
        lost=tuple(sorted(lost, key=lambda x: x.from_start)),
        unchanged=tuple(unchanged),
        still_unplaced=tuple(still_unplaced),
        newly_over_budget_unchanged=tuple(over_unchanged),
        placed_before=len(current),
        placed_after=len(new_slots),
    )


def _over_budget_ids(
    slots: Mapping[str, tuple[datetime, int]],
    other_obstacles: Sequence[Obstacle],
    budget: Mapping[str, int | None],
) -> set[str]:
    """The tasks that touch a calendar date whose committed minutes - every obstacle and
    every task in `slots`, counted as §6.2 counts them - exceed that date's budget."""
    if not slots:
        return set()
    obstacles = [
        *other_obstacles,
        *(Obstacle(start=start, end=add_elapsed(start, timedelta(minutes=minutes))) for start, minutes in slots.values()),
    ]
    obstacles.sort(key=lambda obstacle: obstacle.start)
    tz = next(iter(slots.values()))[0].tzinfo

    over_dates: dict[date, bool] = {}

    def date_is_over(day: date) -> bool:
        if day not in over_dates:
            cap = budget.get(day_name(day))
            over_dates[day] = cap is not None and committed_minutes_for_day(day, obstacles, tz) > cap
        return over_dates[day]

    over: set[str] = set()
    by_date: dict[str, list[date]] = defaultdict(list)
    for task_id, (start, minutes) in slots.items():
        end = add_elapsed(start, timedelta(minutes=minutes))
        for day in day_range(start.date(), end.date()):
            if end > datetime.combine(day, time.min, tzinfo=tz):
                by_date[task_id].append(day)
    for task_id, days in by_date.items():
        if any(date_is_over(day) for day in days):
            over.add(task_id)
    return over


__all__ = [
    "CurrentSlot",
    "Loss",
    "Move",
    "NewPlacement",
    "NothingToDoReason",
    "OptimizationPlan",
    "OptimizationResult",
    "plan_optimization",
]
