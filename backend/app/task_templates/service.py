"""TaskTemplate service: create, archive, "this and future" edit. See design doc §3.2,
§3.8, §3.10; architecture-plan §4.1 (job co-location - real job calls are stubs here,
Stage 6 wires the real adapter behind the same interface without touching call sites).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
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
    JobScheduler,
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
    displace_flexible_under,
    end_series,
    fixed_slot_change_conflicts,
    place_or_defer,
    require_settings,
    resolve_cleared_sync_conflicts,
    return_to_pending,
    schedule_dependency_at_risk_job,
    schedule_next_occurrence_boundary,
    schedule_reminder_and_overdue_jobs,
)
from app.scheduling.repair import find_invalid_placements
from app.scheduling_engine.dependencies import cycle_check
from app.scheduling_engine.feasibility import validate_feasible_duration


class TemplateValidationError(Exception):
    """`code` maps to the API error envelope (architecture-plan §3); `details`, when set,
    rides along in it (e.g. which occurrence a "this and future" edit failed on)."""

    def __init__(self, code: str, message: str, *, details: dict[str, object] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.details = details


@dataclass(frozen=True)
class TaskTemplateDraft:
    """Everything `create_template` needs beyond what it generates itself (id/timestamps/version)."""

    name: str
    type: TaskType
    recurrence: Recurrence
    priority: Priority
    estimated_duration_minutes: int
    start_date: date
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

    if draft.start_date < now.astimezone(ZoneInfo(settings.timezone)).date():
        raise TemplateValidationError("invalid_start_date", "The start date can't be in the past.")

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
            start_date=draft.start_date,
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
    if generated.deadline is not None and generated.deadline <= now:
        # The window is counted from the start of the occurrence's date (§9.1), so a
        # short one on a start date of today can already be over. Saving it would make it
        # `missed` on arrival.
        raise TemplateValidationError(
            "invalid_start_date",
            "This task's window has already ended - its deadline is counted from the start of its start date. "
            "Choose a later start date or a longer deadline.",
        )
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

    schedule_dependency_at_risk_job(jobs, instance)

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
    # A blocked fixed instance holds its slot while it waits (§6.5, Rev 10), so it is
    # validated - and wired - exactly like an unblocked one.
    if has_fixed_conflict(db, start=scheduled_time, end=end):
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
    schedule_reminder_and_overdue_jobs(jobs, instance, template.reminder_offsets_minutes)
    displace_flexible_under(db, jobs, instance, now=now)
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
            nominal_date=generated.nominal_date,
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
    deleted_instance_ids: tuple[str, ...]
    unblocked_instance_ids: tuple[str, ...]


def archive_template(db: Session, jobs: JobScheduler, template_id: str) -> ArchiveResult:
    """§3.8 (Rev 11): ending a series - the template is archived, not hard-deleted, so
    historical instances' `template_id` references stay valid; every open occurrence is
    deleted (see `end_series`). Returns what was deleted and unblocked.
    """
    if TaskTemplateRepository(db).get(template_id) is None:
        raise TemplateValidationError("not_found", f"TaskTemplate {template_id} not found")
    ended = end_series(db, jobs, template_id, now=utcnow())
    archived = TaskTemplateRepository(db).get(template_id)
    assert archived is not None
    return ArchiveResult(
        template=archived, deleted_instance_ids=ended.deleted_instance_ids, unblocked_instance_ids=ended.unblocked_instance_ids
    )


def edit_template_this_and_future(
    db: Session,
    jobs: JobScheduler,
    template_id: str,
    *,
    patch: dict[str, object],
    from_instance_id: str | None = None,
    include_detached: bool = False,
) -> TaskTemplate:
    """§3.10 "this and future" (rewritten Rev 10; architecture-plan §4.1): writes the
    template and, in the same transaction, the edited occurrence (`from_instance_id`) plus
    every open occurrence of the series dated after it (by `nominal_date`). A later
    `detached` occurrence is skipped unless `include_detached`; the edited one always
    takes the edit. Each reached occurrence has its `detached` flag cleared - it rejoins
    the series. Earlier and terminal occurrences are never touched.

    `from_instance_id` is required for a recurring template with open occurrences -
    without it "this" is undefined (architecture-plan §3). Omitted, the edit starts from
    the earliest open occurrence, which is unambiguous for a one-time template (it has
    only the one) and for a series with none open (the edit reaches only the template).

    Every reached occurrence is validated before anything is written: a fixed one retimed
    or lengthened into a collision rejects the whole edit with `creation_conflict`, naming
    it. A `fixed_time_of_day` change re-projects each fixed occurrence's `scheduled_time`
    onto its own local date (§14.1); a `deadline_offset_minutes` change puts each flexible
    occurrence's `deadline` at `nominal_date` + the new offset (§9.1).
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

    reached = _reached_occurrences(db, template_id, from_instance_id=from_instance_id, include_detached=include_detached)
    if from_instance_id is None and reached and current.recurrence.pattern != "one_time":
        raise TemplateValidationError(
            "invalid_field", "from_instance is required for a recurring task - it names the occurrence the edit starts from."
        )
    retimes: dict[str, datetime | None] = {}
    for occurrence in reached:
        retimed_at = _retimed_scheduled_time(occurrence, previous=current, template=prospective, settings=settings)
        retimes[occurrence.id] = retimed_at
        if fixed_slot_change_conflicts(
            db,
            occurrence,
            start=retimed_at or occurrence.scheduled_time or utcnow(),
            duration_minutes=prospective.estimated_duration_minutes
            if "estimated_duration_minutes" in patch
            else occurrence.estimated_duration_minutes,
        ):
            when = _local_label(occurrence, settings=settings)
            raise TemplateValidationError(
                "creation_conflict",
                f"The new fixed time or duration of the {when} occurrence collides with an existing fixed task or external event.",
                details={"instance_id": occurrence.id},
            )

    new_template = repo.update(prospective)

    for occurrence in reached:
        _propagate_to_instance(
            db,
            jobs,
            instance=occurrence,
            previous=current,
            template=new_template,
            settings=settings,
            patch=patch,
            retimed_at=retimes[occurrence.id],
        )

    _rewire_occurrence_boundary(db, jobs, previous=current, template=new_template, settings=settings)

    return new_template


def _reached_occurrences(
    db: Session, template_id: str, *, from_instance_id: str | None, include_detached: bool
) -> list[TaskInstance]:
    """§3.10's reach, oldest first: the edited occurrence, then every open occurrence dated
    after it - minus the `detached` ones unless `include_detached`."""
    open_occurrences = sorted(
        (i for i in TaskInstanceRepository(db).list_by_template(template_id) if i.status not in TERMINAL_STATUSES),
        key=_occurrence_date,
    )
    if from_instance_id is None:
        if not open_occurrences:
            return []
        edited = open_occurrences[0]
    else:
        found = TaskInstanceRepository(db).get(from_instance_id)
        if found is None or found.template_id != template_id:
            raise TemplateValidationError("invalid_field", "from_instance is not an occurrence of this task.")
        if found.status in TERMINAL_STATUSES:
            raise TemplateValidationError(
                "invalid_field", f"from_instance is {found.status} - a finished occurrence can't be edited."
            )
        edited = found
    later = [
        i
        for i in open_occurrences
        if i.id != edited.id and _occurrence_date(i) > _occurrence_date(edited) and (include_detached or not i.detached)
    ]
    return [edited, *later]


def _occurrence_date(instance: TaskInstance) -> datetime:
    """§3.10 orders occurrences by `nominal_date`; `generated_at` stands in on the (only
    theoretically possible) row the nominal-date backfill skipped."""
    return instance.nominal_date or instance.generated_at


def _local_label(instance: TaskInstance, *, settings: UserSettings) -> str:
    moment = instance.scheduled_time or _occurrence_date(instance)
    return moment.astimezone(ZoneInfo(settings.timezone)).strftime("%a %d %b")


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
    """Applies a "this and future" edit to one reached occurrence and re-wires every job
    the change affects (architecture-plan §4.1: the DB write and its job side effects
    live in one method). `retimed_at` is precomputed by the caller, which has already run
    §6.5's conflict check on it. The occurrence rejoins the series (`detached` cleared).
    """
    now = utcnow()
    instance_updates: dict[str, object] = {field: getattr(template, field) for field in _PROPAGATABLE_FIELDS if field in patch}
    if instance.detached:
        instance_updates["detached"] = False
    if retimed_at is not None:
        instance_updates["scheduled_time"] = retimed_at
    new_deadline = _recomputed_deadline(instance, previous=previous, template=template)
    if new_deadline is not None:
        instance_updates["deadline"] = new_deadline

    repo = TaskInstanceRepository(db)
    updated = repo.update(instance.model_copy(update=instance_updates)) if instance_updates else instance

    reminders_changed = previous.reminder_offsets_minutes != template.reminder_offsets_minutes
    # A blocked fixed instance holds its time and carries its jobs like a scheduled one (§6.5).
    on_timeline = updated.status == "scheduled" or (updated.type == "fixed" and updated.status == "blocked")
    if on_timeline and (retimed_at is not None or reminders_changed):
        schedule_reminder_and_overdue_jobs(
            jobs, updated, template.reminder_offsets_minutes, dropped_offsets=previous.reminder_offsets_minutes
        )
    if retimed_at is not None and on_timeline:
        # §3.9: moving clear of an external event resolves its sync_conflict right away,
        # the same as a manual reschedule does.
        resolve_cleared_sync_conflicts(db, now=now)
    if retimed_at is not None or "estimated_duration_minutes" in patch:
        displace_flexible_under(db, jobs, updated, now=now)
    if new_deadline is not None or retimed_at is not None:
        schedule_dependency_at_risk_job(jobs, updated)

    if template.type != "flexible" or updated.status not in ("pending", "scheduled"):
        return updated

    # A new override gives a pending occurrence a fresh attempt, but only invalidates a
    # scheduled one's slot if it no longer covers it (§6.10) - placement is an
    # incremental fit, so a slot that still fits stays put.
    placement_invalidated = "estimated_duration_minutes" in patch or (
        "active_hours_override" in patch
        and (updated.status == "pending" or bool(find_invalid_placements(db, settings, only={updated.id})))
    )
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
    """§9.1: `deadline = nominal_date + deadline_offset_minutes`, so an offset change puts
    the deadline there - which also replaces a custom deadline on an occurrence the user
    chose to bring back into the series. `None` when the offset didn't change or the
    deadline is already there.
    """
    if instance.type != "flexible" or instance.status not in _REDEADLINABLE_FLEXIBLE_STATUSES or instance.deadline is None:
        return None
    if template.deadline_offset_minutes == previous.deadline_offset_minutes:
        return None
    if instance.nominal_date is None:
        delta = (template.deadline_offset_minutes or 0) - (previous.deadline_offset_minutes or 0)
        return instance.deadline + timedelta(minutes=delta)
    recomputed = instance.nominal_date + timedelta(minutes=template.deadline_offset_minutes or 0)
    return None if recomputed == instance.deadline else recomputed


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
