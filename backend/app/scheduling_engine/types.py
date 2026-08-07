"""Engine-local input/output shapes. See design doc §3 (data model) and §6 (algorithm).

These types are defined by and for the scheduling engine itself - they are not the
persisted domain models (Stage 2). The service layer is responsible for translating
TaskTemplate/TaskInstance/UserSettings rows into these plain-Python shapes before
calling into the engine, and for translating results back. See architecture-plan §2.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, time
from typing import Literal

type BudgetEnforcement = Literal["strict", "soft"]

# Lowercase day-of-week names, Monday-first, matching design doc §3.7's map keys
# (`active_hours["saturday"]`, etc). Index is `date.weekday()` (Monday == 0).
DAY_NAMES: tuple[str, ...] = (
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
)


@dataclass(frozen=True)
class ActiveHoursWindow:
    """A wall-clock scheduling window on a single day of week. See design doc §3.7."""

    start: time
    end: time


# Per-day-of-week active-hours map. A day name absent from the mapping is not the
# same as a day name present with value None: absent means "not overridden, inherit
# the global map" (only meaningful for override maps - see merge_active_hours in
# calendar_rules.py); present-with-None always means "this day is fully excluded"
# (design doc §3.2/§3.7 - one shape, one meaning, no exceptions).
type ActiveHoursMap = Mapping[str, ActiveHoursWindow | None]


@dataclass(frozen=True)
class BlackoutDate:
    """A full-day exclusion range. See design doc §3.7."""

    start: date
    end: date
    label: str | None = None


@dataclass(frozen=True)
class Obstacle:
    """An opaque busy interval the placement algorithm must not schedule into.

    See design doc §6.2's obstacle set: every `scheduled`/`in_progress` TaskInstance
    of either type, plus filtered external calendar busy-blocks, plus (accumulated by
    the engine itself) flexible instances placed earlier in the same pass.
    """

    start: datetime
    end: datetime


@dataclass(frozen=True)
class FlexibleTaskCandidate:
    """A pending flexible TaskInstance, as the engine needs to see it. See design doc §6.2.

    `dependency_completed_at` holds the `completed_at` of every dependency of this
    task. By the time a task is a placement candidate, the `blocked` status gate
    (§6.1) already guarantees every dependency is `completed`, so this is always
    the real, populated completion timestamps - never a placeholder.
    """

    id: str
    deadline: datetime
    priority: int
    estimated_duration_minutes: int
    active_hours_override: ActiveHoursMap | None = None
    dependency_completed_at: Sequence[datetime] = field(default_factory=tuple)


@dataclass(frozen=True)
class Placement:
    """The engine's placement decision for one candidate. See design doc §6.2.

    `budget_overridden` is True when Pass 2 had to breach the daily time budget to
    place this task before its deadline - the service layer maps this to a
    `budget_exceeded` Notification (§5). The engine itself creates no notifications.
    """

    task_id: str
    scheduled_start: datetime
    budget_overridden: bool


@dataclass(frozen=True)
class SchedulingResult:
    """The full outcome of one `schedule_pending_flexible_tasks` run. See design doc §6.2."""

    placements: tuple[Placement, ...]
    unschedulable_task_ids: tuple[str, ...]
