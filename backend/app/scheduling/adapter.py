"""DB-aware scheduling orchestration: translates domain objects into `scheduling_engine`'s
plain input types, calls the pure engine, and hands back its raw result. This is the
settings-to-scheduling wiring Stage 4 explicitly deferred ("Out of scope: anything reading
these settings for actual scheduling - that wiring is Stage 5").

Deliberately mechanical - no notification creation, no status transitions, no job
scheduling. Those are business decisions the caller (`app.task_instances`/`app.task_templates`)
makes from this module's results; this module only ever answers "where would the engine
place this" or "does this fixed time conflict with anything".

**A new tier in the import-linter "Layering" contract**, sitting below the
`app.task_templates | app.task_instances | ...` sibling group and above `app.db`. Siblings
in that group are independent by contract - `app.task_templates` may not import
`app.task_instances` or vice versa - but both need this exact DB-aware placement logic (a
template's freshly-spawned instance needs placing; an unblocked instance needs
re-placing). This mirrors `app.db`'s existing role as a shared foundation the sibling
service modules all depend on, rather than either sibling owning it on the other's behalf.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, time, timedelta, tzinfo
from typing import cast
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.db.repositories import ExternalCalendarConnectionRepository, ExternalEventRepository, TaskInstanceRepository
from app.db.schemas import ActiveHoursWindow as DomainActiveHoursWindow
from app.db.schemas import DayName, TaskInstance, TaskTemplate, UserSettings
from app.db.session import acquire_write_lock
from app.scheduling_engine.calendar_rules import merge_active_hours
from app.scheduling_engine.fixed_conflicts import check_fixed_conflict as engine_check_fixed_conflict
from app.scheduling_engine.placement import schedule_pending_flexible_tasks
from app.scheduling_engine.types import ActiveHoursMap, FlexibleTaskCandidate, Obstacle, SchedulingResult
from app.scheduling_engine.types import ActiveHoursWindow as EngineActiveHoursWindow
from app.scheduling_engine.types import BlackoutDate as EngineBlackoutDate

OBSTACLE_STATUSES = ("scheduled", "in_progress")


def _parse_hhmm(value: str) -> time:
    hour, minute = value.split(":")
    return time(int(hour), int(minute))


def to_engine_active_hours(
    mapping: dict[DayName, DomainActiveHoursWindow | None] | None,
) -> ActiveHoursMap | None:
    """ "HH:MM"-string windows (design doc §3.2/§3.7's wire shape) -> the engine's `time`-based type."""
    if mapping is None:
        return None
    return {
        day: (EngineActiveHoursWindow(start=_parse_hhmm(w.start), end=_parse_hhmm(w.end)) if w else None)
        for day, w in mapping.items()
    }


def build_active_hours_map(
    settings: UserSettings, override: dict[DayName, DomainActiveHoursWindow | None] | None
) -> ActiveHoursMap:
    """The effective per-day window: `override` merged over the global settings map (§3.2, §6.2)."""
    global_map = to_engine_active_hours(settings.active_hours)
    assert global_map is not None  # UserSettings.active_hours is never itself optional
    return merge_active_hours(global_map, to_engine_active_hours(override))


def build_blackout_dates(settings: UserSettings) -> tuple[EngineBlackoutDate, ...]:
    return tuple(EngineBlackoutDate(start=b.start, end=b.end, label=b.label) for b in settings.blackout_dates)


def gather_external_obstacles(db: Session) -> tuple[Obstacle, ...]:
    """Cached `ExternalEvent` rows (§3.11) across every *enabled* connection, as opaque
    busy blocks - filtered per §7: transparent/"Free" events and all-day events never
    obstruct placement or fixed-task conflict checks, so they are excluded here rather
    than at fetch time (§7: "Filtering ... happens when the obstacle set is assembled,
    not at fetch time"). `enabled_only=True` matches `run_calendar_poll`/startup
    reconciliation, which both stop touching a disabled connection's cache entirely - its
    events would otherwise sit frozen (never diffed, soft-deleted, or retention-purged)
    and obstruct forever.

    Obstacle-specific filtering only - for the Timeline's *display* purposes (§8.1 screen
    2), all-day events are kept (not obstacle-excluded) as a distinct read-only overlay
    category; see `app.calendar_sync.service.list_display_events`, which deliberately does
    not reuse this function's predicate.
    """
    connection_repo = ExternalCalendarConnectionRepository(db)
    event_repo = ExternalEventRepository(db)
    obstacles: list[Obstacle] = []
    for connection in connection_repo.list(enabled_only=True):
        for event in event_repo.list_active_for_connection(connection.id):
            if event.is_transparent or event.is_all_day:
                continue
            obstacles.append(Obstacle(start=event.start, end=event.end))
    return tuple(obstacles)


def gather_obstacles(
    db: Session, *, exclude_instance_id: str | None = None, include_scheduled_flexible: bool = True
) -> tuple[Obstacle, ...]:
    """Every `scheduled`/`in_progress` instance, both types, plus every filtered external
    busy-block (§7) - the full §6.2 obstacle set. `include_scheduled_flexible=False`
    drops `scheduled` flexible instances, for §6.5's fixed-task check: those give way
    to a fixed task rather than block it (see `has_fixed_conflict`).

    Takes the database write lock first, so the set stays current until the caller's
    placement or conflict decision commits - see `acquire_write_lock` (issue #24).
    """
    acquire_write_lock(db)
    repo = TaskInstanceRepository(db)
    obstacles: list[Obstacle] = []
    for instance in repo.list_by_statuses(OBSTACLE_STATUSES):
        if instance.id == exclude_instance_id or instance.scheduled_time is None:
            continue
        if not include_scheduled_flexible and instance.type == "flexible" and instance.status == "scheduled":
            continue
        end = instance.scheduled_time + timedelta(minutes=instance.estimated_duration_minutes)
        obstacles.append(Obstacle(start=instance.scheduled_time, end=end))
    obstacles.extend(gather_external_obstacles(db))
    return tuple(obstacles)


#: §6.4 step 3 scopes sync-collision eviction to a `scheduled` instance only - deliberately
#: narrower than `OBSTACLE_STATUSES`, which also includes `in_progress` for placement
#: purposes (§6.2). An `in_progress` instance is never evicted or flagged here: yanking an
#: actively-worked-on task off the timeline, or auto-resolving a still-open notification
#: the moment the user starts it, are both outside what §6.4 asks for.
_COLLISION_EVICTION_STATUSES = ("scheduled",)


def find_overlapping_scheduled_instances(db: Session, *, start: datetime, end: datetime) -> tuple[TaskInstance, ...]:
    """Every `scheduled` (not `in_progress` - see `_COLLISION_EVICTION_STATUSES`) instance
    whose window overlaps `[start, end)` - §6.4 step 3's "for new/moved events colliding
    with a `scheduled` instance" lookup, the reverse direction of `gather_obstacles`.
    """
    repo = TaskInstanceRepository(db)
    overlapping: list[TaskInstance] = []
    for instance in repo.list_by_statuses(_COLLISION_EVICTION_STATUSES):
        if instance.scheduled_time is None:
            continue
        instance_end = instance.scheduled_time + timedelta(minutes=instance.estimated_duration_minutes)
        if instance.scheduled_time < end and start < instance_end:
            overlapping.append(instance)
    return tuple(overlapping)


def build_candidate(db: Session, instance: TaskInstance, template: TaskTemplate, *, tz: tzinfo) -> FlexibleTaskCandidate:
    """Precondition: `instance` is `flexible` with a set `deadline` - true of every real
    placement candidate (§3.3); fixed instances never reach this function.

    `tz` converts the persisted-UTC deadline/dependency-completion instants to the user's
    local wall-clock - see `attempt_placement`'s docstring for why that conversion has to
    happen before anything reaches the engine, not after.
    """
    if instance.deadline is None:
        raise ValueError(f"TaskInstance {instance.id} has no deadline - only flexible instances can be placed")

    repo = TaskInstanceRepository(db)
    dependency_completed_at: list[datetime] = []
    for dependency_id in instance.dependencies:
        dependency = repo.get(dependency_id)
        if dependency is not None and dependency.completed_at is not None:
            dependency_completed_at.append(dependency.completed_at.astimezone(tz))

    return FlexibleTaskCandidate(
        id=instance.id,
        deadline=instance.deadline.astimezone(tz),
        priority=instance.priority,
        estimated_duration_minutes=instance.estimated_duration_minutes,
        active_hours_override=to_engine_active_hours(template.active_hours_override),
        dependency_completed_at=tuple(dependency_completed_at),
        not_before=_completion_anchor_gate(repo, instance, template, tz=tz),
    )


def _completion_anchor_gate(
    repo: TaskInstanceRepository, instance: TaskInstance, template: TaskTemplate, *, tz: tzinfo
) -> datetime | None:
    """§9.1: a completion-anchored occurrence "is not eligible for placement before" its
    nominal date (design doc Example O). That rule is about the series' successors - a
    template's very first instance has no predecessor to be "due again" after, and keeps
    being placed as soon as it fits, as it always has.
    """
    if template.recurrence.anchor != "completion" or instance.nominal_date is None:
        return None
    if repo.list_by_template(template.id)[-1].id == instance.id:  # most-recent-first: [-1] is the first ever generated
        return None
    return instance.nominal_date.astimezone(tz)


def attempt_placement(
    db: Session, *, instance: TaskInstance, template: TaskTemplate, settings: UserSettings, now: datetime
) -> SchedulingResult:
    """Run §6.2 for a single candidate. Reused for every trigger point that places or
    re-places exactly one instance (creation, dependency unblock, this-and-future
    propagation, extend-deadline) - `schedule_pending_flexible_tasks` degrades cleanly to
    a one-element candidate list, so there is no separate "single" algorithm to maintain.

    `now` must be timezone-aware (matches every other datetime in this codebase, e.g.
    `app.db.base.utcnow()`) but need not already be in the user's timezone - it, the
    candidate's deadline/dependency-completion instants, and every obstacle are all
    converted to `settings.timezone` here before reaching the engine. Design doc §14.1/
    §6.2: grid alignment and active-hours windows are wall-clock operations, and handing
    the engine a UTC instant instead would silently misapply both.
    """
    tz = ZoneInfo(settings.timezone)
    local_obstacles = tuple(
        Obstacle(start=obstacle.start.astimezone(tz), end=obstacle.end.astimezone(tz))
        for obstacle in gather_obstacles(db, exclude_instance_id=instance.id)
    )
    return schedule_pending_flexible_tasks(
        [build_candidate(db, instance, template, tz=tz)],
        now=now.astimezone(tz),
        active_hours=build_active_hours_map(settings, template.active_hours_override),
        blackout_dates=build_blackout_dates(settings),
        daily_time_budget_minutes=cast("Mapping[str, int | None]", settings.daily_time_budget_minutes),
        budget_enforcement=settings.budget_enforcement,
        obstacles=local_obstacles,
    )


def has_fixed_conflict(db: Session, *, start: datetime, end: datetime, exclude_instance_id: str | None = None) -> bool:
    """§6.5: hard-block predicate for creating/retiming a `fixed` instance. Only
    commitments block it - other fixed instances, external busy-blocks and an
    `in_progress` flexible one. A `scheduled` flexible instance in the way is not a
    conflict: the caller moves it with `displace_flexible_from` (Rev 10).
    """
    obstacles = gather_obstacles(db, exclude_instance_id=exclude_instance_id, include_scheduled_flexible=False)
    return engine_check_fixed_conflict(start, end, obstacles)


__all__ = [
    "OBSTACLE_STATUSES",
    "attempt_placement",
    "build_active_hours_map",
    "build_blackout_dates",
    "build_candidate",
    "find_overlapping_scheduled_instances",
    "gather_external_obstacles",
    "gather_obstacles",
    "has_fixed_conflict",
    "to_engine_active_hours",
]
