"""TaskTemplate service: create, archive, "this and future" edit. See design doc §3.2,
§3.8, §3.10; architecture-plan §4.1 (job co-location - real job calls are stubs here,
Stage 6 wires the real adapter behind the same interface without touching call sites).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import cast
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.db.base import generate_id, utcnow
from app.db.repositories import TaskInstanceRepository, TaskTemplateRepository
from app.db.schemas import (
    ActiveHoursWindow,
    DayName,
    Priority,
    Recurrence,
    StatusHistoryEntry,
    TaskInstance,
    TaskInstanceStatus,
    TaskTemplate,
    TaskType,
    UserSettings,
)
from app.jobs.interface import (
    DEPENDENCY_AT_RISK_THRESHOLD,
    JobScheduler,
    dependency_at_risk_job_key,
    occurrence_boundary_job_key,
)
from app.scheduling.adapter import build_active_hours_map, has_fixed_conflict
from app.scheduling.generation import (
    GeneratedInstanceFields,
    VirtualOccurrence,
    generate_next_instance,
    project_fixed_time,
    project_virtual_occurrences,
)
from app.scheduling.orchestration import (
    TERMINAL_STATUSES,
    archive_template_and_cancel_jobs,
    fixed_slot_change_conflicts,
    place_or_defer,
    require_settings,
    resolve_cleared_sync_conflicts,
    return_to_pending,
    schedule_next_occurrence_boundary,
    schedule_reminder_and_overdue_jobs,
)
from app.scheduling_engine.dependencies import cycle_check
from app.scheduling_engine.feasibility import validate_feasible_duration


class TemplateValidationError(Exception):
    """`code` maps to the API error envelope (architecture-plan §3)."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class TaskTemplateDraft:
    """Everything `create_template` needs beyond what it generates itself (id/timestamps/version)."""

    name: str
    type: TaskType
    recurrence: Recurrence
    priority: Priority
    estimated_duration_minutes: int
    description: str | None = None
    location: str | None = None
    fixed_time_of_day: str | None = None
    deadline_offset_minutes: int | None = None
    reminder_offsets_minutes: tuple[int, ...] = ()
    active_hours_override: dict[DayName, ActiveHoursWindow | None] | None = None
    dependencies: tuple[str, ...] = ()


@dataclass(frozen=True)
class CreatedTemplate:
    template: TaskTemplate
    instance: TaskInstance


def get_template(db: Session, template_id: str) -> TaskTemplate:
    """`GET /task-templates/{id}` (architecture-plan §3's resource shape). Returns an
    archived template too - §3.8 keeps the row specifically so historical/`template_id`
    references stay valid, and a caller reopening a stale "this and future" reference
    needs to see `archived: true`, not a 404.
    """
    template = TaskTemplateRepository(db).get(template_id)
    if template is None:
        raise TemplateValidationError("not_found", f"TaskTemplate {template_id} not found")
    return template


def list_virtual_occurrences(db: Session, *, now: datetime) -> list[VirtualOccurrence]:
    """`GET /task-templates/projections` (design doc §9.2, added Stage 9d) - the Timeline's
    "ghost" preview of upcoming recurring occurrences beyond each template's current live
    instance. Fetches every non-archived template and, per template, its most-recently
    generated instance (`list_by_template` is already most-recent-first - see
    `app.jobs.reconciliation`/`app.jobs.handlers` for the identical `instances[0]`
    pattern), then delegates the actual anchor-aware projection math to
    `app.scheduling.generation.project_virtual_occurrences` so it agrees with §9.1's real
    generator by construction rather than by a second, separately-written implementation.
    """
    settings = require_settings(db)
    templates = TaskTemplateRepository(db).list(include_archived=False)
    instance_repo = TaskInstanceRepository(db)
    latest_by_template = {
        template.id: (instances[0] if (instances := instance_repo.list_by_template(template.id)) else None)
        for template in templates
    }
    return project_virtual_occurrences(
        templates, latest_instance_by_template=latest_by_template, now=now, timezone=settings.timezone
    )


def create_template(db: Session, jobs: JobScheduler, draft: TaskTemplateDraft) -> CreatedTemplate:
    """§3.1/§9.1: creating a template always spawns its initial instance in the same
    transaction. Every check below can reject the whole save (§6.1, §6.5, §6.8) and none
    of it is persisted until all of them pass.
    """
    now = utcnow()

    if draft.recurrence.anchor == "completion" and draft.type != "flexible":
        raise TemplateValidationError("invalid_recurrence_anchor", 'anchor: "completion" is only valid on flexible templates.')

    settings = require_settings(db)

    if draft.dependencies:
        _ensure_no_cycle(db, dependency_ids=draft.dependencies)

    if draft.type == "flexible":
        effective_hours = build_active_hours_map(settings, draft.active_hours_override)
        if not validate_feasible_duration(draft.estimated_duration_minutes, effective_hours):
            raise TemplateValidationError(
                "infeasible_duration",
                "estimated_duration_minutes does not fit any day's effective active-hours window.",
            )

    template = TaskTemplateRepository(db).create(
        TaskTemplate(
            id=generate_id(),
            name=draft.name,
            description=draft.description,
            location=draft.location,
            type=draft.type,
            recurrence=draft.recurrence,
            fixed_time_of_day=draft.fixed_time_of_day,
            deadline_offset_minutes=draft.deadline_offset_minutes,
            priority=draft.priority,
            estimated_duration_minutes=draft.estimated_duration_minutes,
            reminder_offsets_minutes=draft.reminder_offsets_minutes,
            active_hours_override=draft.active_hours_override,
            archived=False,
            created_at=now,
            updated_at=now,
            version=1,
        )
    )

    generated = generate_next_instance(template, predecessor=None, now=now, timezone=settings.timezone)
    blocked = bool(draft.dependencies)

    if template.type == "fixed":
        instance = _create_fixed_instance(
            db, jobs, template=template, generated=generated, blocked=blocked, dependencies=draft.dependencies, now=now
        )
    else:
        instance = _create_flexible_instance(
            db,
            jobs,
            template=template,
            generated=generated,
            blocked=blocked,
            dependencies=draft.dependencies,
            settings=settings,
            now=now,
        )

    if blocked and instance.deadline is not None:
        jobs.schedule_at(job_key=dependency_at_risk_job_key(instance.id), run_at=instance.deadline - DEPENDENCY_AT_RISK_THRESHOLD)

    if template.recurrence.pattern != "one_time" and template.recurrence.anchor == "calendar":
        schedule_next_occurrence_boundary(db, jobs, template=template, latest_instance=instance, settings=settings, now=now)

    return CreatedTemplate(template=template, instance=instance)


def _create_fixed_instance(
    db: Session,
    jobs: JobScheduler,
    *,
    template: TaskTemplate,
    generated: GeneratedInstanceFields,
    blocked: bool,
    dependencies: tuple[str, ...],
    now: datetime,
) -> TaskInstance:
    if generated.scheduled_time is None:
        raise ValueError("a fixed template's generated instance must have a scheduled_time")
    scheduled_time = generated.scheduled_time
    end = scheduled_time + timedelta(minutes=generated.estimated_duration_minutes)
    if not blocked and has_fixed_conflict(db, start=scheduled_time, end=end):
        raise TemplateValidationError(
            "creation_conflict", "This fixed time collides with an existing fixed task or external event."
        )

    instance = _persist_instance(
        db,
        template=template,
        generated=generated,
        status="blocked" if blocked else "scheduled",
        dependencies=dependencies,
        now=now,
    )
    if not blocked:
        schedule_reminder_and_overdue_jobs(jobs, instance, template.reminder_offsets_minutes)
    return instance


def _create_flexible_instance(
    db: Session,
    jobs: JobScheduler,
    *,
    template: TaskTemplate,
    generated: GeneratedInstanceFields,
    blocked: bool,
    dependencies: tuple[str, ...],
    settings: UserSettings,
    now: datetime,
) -> TaskInstance:
    instance = _persist_instance(
        db,
        template=template,
        generated=generated,
        status="blocked" if blocked else "pending",
        dependencies=dependencies,
        now=now,
    )
    if blocked:
        return instance
    return place_or_defer(db, jobs, instance=instance, template=template, settings=settings, now=now)


def _persist_instance(
    db: Session,
    *,
    template: TaskTemplate,
    generated: GeneratedInstanceFields,
    status: str,
    dependencies: tuple[str, ...],
    now: datetime,
) -> TaskInstance:
    instance_status = cast(TaskInstanceStatus, status)
    return TaskInstanceRepository(db).create(
        TaskInstance(
            id=generate_id(),
            template_id=template.id,
            name=generated.name,
            description=generated.description,
            location=generated.location,
            type=generated.type,
            priority=generated.priority,
            estimated_duration_minutes=generated.estimated_duration_minutes,
            detached=False,
            scheduled_time=generated.scheduled_time,
            deadline=generated.deadline,
            status=instance_status,
            status_history=(StatusHistoryEntry(status=instance_status, at=now),),
            dependencies=dependencies,
            generated_at=now,
            created_at=now,
            updated_at=now,
            version=1,
        )
    )


#: Fields "this and future" copies verbatim onto a non-detached live instance - the same
#: content set §3.10 lists for the "this occurrence" edit scope. The two template fields
#: that map onto an instance field only *indirectly* - `fixed_time_of_day` ->
#: `scheduled_time` and `deadline_offset_minutes` -> `deadline` - are derived separately,
#: see `_retimed_scheduled_time`/`_recomputed_deadline`.
_PROPAGATABLE_FIELDS = ("name", "description", "location", "priority", "estimated_duration_minutes")

#: Fixed statuses whose `scheduled_time` a `fixed_time_of_day` change re-projects.
#: `in_progress` is deliberately excluded: the occurrence is already underway, so moving
#: its start time would rewrite what already happened rather than plan what's next.
_RETIMABLE_FIXED_STATUSES = frozenset({"scheduled", "blocked"})
#: Flexible statuses whose `deadline` a `deadline_offset_minutes` change recomputes.
#: `missed` is deliberately excluded: §6.7 makes leaving `missed` a user-driven action
#: (extend-deadline, complete or delete), never a side effect of a template-wide edit.
_REDEADLINABLE_FLEXIBLE_STATUSES = frozenset({"pending", "scheduled", "blocked", "in_progress"})


@dataclass(frozen=True)
class ArchiveResult:
    template: TaskTemplate
    incomplete_instance_ids: tuple[str, ...]


def archive_template(db: Session, jobs: JobScheduler, template_id: str) -> ArchiveResult:
    """§3.8: soft-delete - `archived=true`, keeping the row so historical instances'
    `template_id` references stay valid. Returns the ids of any non-terminal instances
    left behind, for the frontend's confirmation dialog to list.

    The actual archive + calendar-anchor occurrence-boundary job cancellation is shared
    with `app.task_instances.service.delete_instance`'s `this_and_future` scope - see
    `archive_template_and_cancel_jobs`'s docstring. `app.jobs.handlers.run_occurrence_boundary`
    also no-ops defensively on an archived template - this is the direct cancellation,
    that is the fallback for the gap before the next startup reconciliation pass (§4.2
    item 3).
    """
    repo = TaskTemplateRepository(db)
    template = repo.get(template_id)
    if template is None:
        raise TemplateValidationError("not_found", f"TaskTemplate {template_id} not found")

    incomplete = tuple(
        instance.id
        for instance in TaskInstanceRepository(db).list_by_template(template_id)
        if instance.status not in TERMINAL_STATUSES
    )
    archived = archive_template_and_cancel_jobs(db, jobs, template_id)
    return ArchiveResult(template=archived, incomplete_instance_ids=incomplete)


def edit_template_this_and_future(db: Session, jobs: JobScheduler, template_id: str, *, patch: dict[str, object]) -> TaskTemplate:
    """§3.10 "this and future": writes the template, then - unless the currently-live
    instance is already `detached` - propagates matching fields to it in the same
    transaction, re-entering §6.2 if the propagation invalidates its placement.

    A `fixed_time_of_day` change re-projects the live fixed instance's `scheduled_time`
    onto the same local date (§14.1 wall-clock semantics). That is a retime, so §6.5's
    hard block applies: a collision rejects the whole edit with `creation_conflict`
    before anything is written or any job is touched. A `deadline_offset_minutes` change
    moves the live flexible instance's `deadline` by the same delta, keeping its nominal
    date fixed (§9.1: `deadline = nominal_date + deadline_offset_minutes`).
    """
    repo = TaskTemplateRepository(db)
    current = repo.get(template_id)
    if current is None:
        raise TemplateValidationError("not_found", f"TaskTemplate {template_id} not found")

    prospective = current.model_copy(update=patch)
    if prospective.recurrence.anchor == "completion" and prospective.type != "flexible":
        raise TemplateValidationError("invalid_recurrence_anchor", 'anchor: "completion" is only valid on flexible templates.')

    settings = require_settings(db)
    duration_or_hours_changed = "estimated_duration_minutes" in patch or "active_hours_override" in patch
    if prospective.type == "flexible" and duration_or_hours_changed:
        effective_hours = build_active_hours_map(settings, prospective.active_hours_override)
        if not validate_feasible_duration(prospective.estimated_duration_minutes, effective_hours):
            raise TemplateValidationError(
                "infeasible_duration",
                "estimated_duration_minutes does not fit any day's effective active-hours window.",
            )

    live = _find_live_instance(db, template_id)
    propagate_to = live if live is not None and not live.detached else None
    retimed_at = (
        _retimed_scheduled_time(propagate_to, previous=current, template=prospective, settings=settings)
        if propagate_to is not None
        else None
    )
    if propagate_to is not None and fixed_slot_change_conflicts(
        db,
        propagate_to,
        start=retimed_at or propagate_to.scheduled_time or utcnow(),
        duration_minutes=prospective.estimated_duration_minutes
        if "estimated_duration_minutes" in patch
        else propagate_to.estimated_duration_minutes,
    ):
        raise TemplateValidationError(
            "creation_conflict", "The new fixed time or duration collides with an existing fixed task or external event."
        )

    new_template = repo.update(prospective)

    if propagate_to is not None:
        _propagate_to_instance(
            db,
            jobs,
            instance=propagate_to,
            previous=current,
            template=new_template,
            settings=settings,
            patch=patch,
            retimed_at=retimed_at,
        )

    _rewire_occurrence_boundary(db, jobs, previous=current, template=new_template, settings=settings)

    return new_template


def _find_live_instance(db: Session, template_id: str) -> TaskInstance | None:
    """The most recently generated non-terminal instance - §3.10's "currently-live" one."""
    for instance in TaskInstanceRepository(db).list_by_template(template_id):  # most-recent-first
        if instance.status not in TERMINAL_STATUSES:
            return instance
    return None


def _propagate_to_instance(
    db: Session,
    jobs: JobScheduler,
    *,
    instance: TaskInstance,
    previous: TaskTemplate,
    template: TaskTemplate,
    settings: UserSettings,
    patch: dict[str, object],
    retimed_at: datetime | None,
) -> TaskInstance:
    """Applies a "this and future" edit to the non-detached live instance and re-wires
    every job the change affects (architecture-plan §4.1: the DB write and its job side
    effects live in one method). `retimed_at` is precomputed by the caller, which has
    already run §6.5's conflict check on it.
    """
    now = utcnow()
    instance_updates: dict[str, object] = {field: getattr(template, field) for field in _PROPAGATABLE_FIELDS if field in patch}
    if retimed_at is not None:
        instance_updates["scheduled_time"] = retimed_at
    new_deadline = _recomputed_deadline(instance, previous=previous, template=template)
    if new_deadline is not None:
        instance_updates["deadline"] = new_deadline

    repo = TaskInstanceRepository(db)
    updated = repo.update(instance.model_copy(update=instance_updates)) if instance_updates else instance

    reminders_changed = previous.reminder_offsets_minutes != template.reminder_offsets_minutes
    if updated.status == "scheduled" and (retimed_at is not None or reminders_changed):
        schedule_reminder_and_overdue_jobs(
            jobs, updated, template.reminder_offsets_minutes, dropped_offsets=previous.reminder_offsets_minutes
        )
    if retimed_at is not None and updated.status == "scheduled":
        # §3.9: moving clear of an external event resolves its sync_conflict right away,
        # the same as a manual reschedule does.
        resolve_cleared_sync_conflicts(db, now=now)
    if new_deadline is not None and updated.status == "blocked":
        jobs.schedule_at(job_key=dependency_at_risk_job_key(updated.id), run_at=new_deadline - DEPENDENCY_AT_RISK_THRESHOLD)

    if template.type != "flexible" or updated.status not in ("pending", "scheduled"):
        return updated

    placement_invalidated = "estimated_duration_minutes" in patch or "active_hours_override" in patch
    if new_deadline is not None:
        # A pending instance gets a fresh attempt against its new window (a later deadline
        # may now fit, an elapsed one goes to `missed` via §6.7's gate). A scheduled one is
        # only moved if its slot no longer ends by the new deadline - placement is an
        # incremental fit (§6.2), so a still-valid slot is never disturbed.
        placement_invalidated = placement_invalidated or updated.status == "pending" or not _fits_before(updated, new_deadline)
    if not placement_invalidated:
        return updated

    if updated.status == "scheduled":
        updated = return_to_pending(db, jobs, updated, template=template, now=now)
    return place_or_defer(db, jobs, instance=updated, template=template, settings=settings, now=now)


def _retimed_scheduled_time(
    instance: TaskInstance, *, previous: TaskTemplate, template: TaskTemplate, settings: UserSettings
) -> datetime | None:
    """§14.1: the new wall-clock `fixed_time_of_day` on the instance's own local date, or
    `None` when nothing needs to move. The result may already be in the past (an earlier
    time on today's date); §6.6's overdue job then fires immediately, as it would for any
    other past-due fixed instance.
    """
    if instance.type != "fixed" or instance.status not in _RETIMABLE_FIXED_STATUSES or instance.scheduled_time is None:
        return None
    if template.fixed_time_of_day is None or template.fixed_time_of_day == previous.fixed_time_of_day:
        return None
    tz = ZoneInfo(settings.timezone)
    retimed = project_fixed_time(instance.scheduled_time.astimezone(tz).date(), template=template, tz=tz)
    return None if retimed == instance.scheduled_time else retimed


def _recomputed_deadline(instance: TaskInstance, *, previous: TaskTemplate, template: TaskTemplate) -> datetime | None:
    """§9.1: `deadline = nominal_date + deadline_offset_minutes`, so an offset change moves
    the deadline by exactly the delta and leaves the nominal date where it was. `None`
    when nothing needs to move.
    """
    if instance.type != "flexible" or instance.status not in _REDEADLINABLE_FLEXIBLE_STATUSES or instance.deadline is None:
        return None
    delta = (template.deadline_offset_minutes or 0) - (previous.deadline_offset_minutes or 0)
    if delta == 0:
        return None
    return instance.deadline + timedelta(minutes=delta)


def _fits_before(instance: TaskInstance, deadline: datetime) -> bool:
    if instance.scheduled_time is None:
        return False
    return instance.scheduled_time + timedelta(minutes=instance.estimated_duration_minutes) <= deadline


def _rewire_occurrence_boundary(
    db: Session, jobs: JobScheduler, *, previous: TaskTemplate, template: TaskTemplate, settings: UserSettings
) -> None:
    """architecture-plan §4: a calendar-anchored template's next-occurrence job fires at
    the next nominal instant, which depends on `fixed_time_of_day` and `recurrence`. When
    either changes, re-point the job at the new instant (or cancel it if the template is
    no longer calendar-anchored and recurring), so the next instance is generated when
    the new rule says rather than when the old one did.
    """
    if template.fixed_time_of_day == previous.fixed_time_of_day and template.recurrence == previous.recurrence:
        return
    if template.recurrence.pattern == "one_time" or template.recurrence.anchor != "calendar":
        jobs.cancel(job_key=occurrence_boundary_job_key(template.id))
        return
    # The most recent instance in any status - the boundary job outlives a completed or
    # dismissed predecessor, which is exactly when there is no live instance to read.
    instances = TaskInstanceRepository(db).list_by_template(template.id)  # most-recent-first
    if not instances:
        return
    schedule_next_occurrence_boundary(db, jobs, template=template, latest_instance=instances[0], settings=settings, now=utcnow())


def _ensure_no_cycle(db: Session, *, dependency_ids: tuple[str, ...], dependent_id: str = "__new__") -> None:
    """§6.1: reject a save whose dependency list would create a direct or indirect cycle.

    A brand-new instance (fresh id, no existing edges point at it yet) cannot itself close
    a cycle through creation alone - nothing can already depend on a node that didn't
    exist a moment ago. The check is still wired here, correctly, against the *real*
    existing-edge graph: a later stage that allows editing dependencies on an existing
    instance reuses this exact function, and that path *can* close a cycle.
    """
    edges = list(TaskInstanceRepository(db).list_all_dependency_edges())
    edges.extend((dependent_id, dependency_id) for dependency_id in dependency_ids)
    if cycle_check(edges):
        raise TemplateValidationError("cycle_detected", "This dependency list would create a cycle.")


__all__ = [
    "ArchiveResult",
    "CreatedTemplate",
    "TaskTemplateDraft",
    "TemplateValidationError",
    "archive_template",
    "create_template",
    "edit_template_this_and_future",
    "get_template",
    "list_virtual_occurrences",
]
