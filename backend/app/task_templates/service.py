"""TaskTemplate service: create, archive, "this and future" edit. See design doc §3.2,
§3.8, §3.10; architecture-plan §4.1 (job co-location - real job calls are stubs here,
Stage 6 wires the real adapter behind the same interface without touching call sites).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import cast

from sqlalchemy.orm import Session

from app.db.base import generate_id, utcnow
from app.db.repositories import TaskInstanceRepository, TaskTemplateRepository, UserSettingsRepository
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
    dependency_at_risk_job_key,
    occurrence_boundary_job_key,
    overdue_job_key,
    reminder_job_key,
)
from app.scheduling.adapter import build_active_hours_map, has_fixed_conflict
from app.scheduling.generation import GeneratedInstanceFields, generate_next_instance
from app.scheduling.orchestration import place_or_defer, schedule_next_occurrence_boundary
from app.scheduling_engine.dependencies import cycle_check
from app.scheduling_engine.feasibility import validate_feasible_duration

#: §6.3's flat POC threshold. Duplicated from `app.jobs.handlers`' identical constant
#: rather than imported - a trivial 1-line constant, same "small duplication across
#: layers beats improper coupling" precedent as the priority-mapping constant in
#: `app.db.repositories.task_template_repository` and `app.scheduling.generation`.
_DEPENDENCY_AT_RISK_THRESHOLD = timedelta(days=3)


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


def create_template(db: Session, jobs: JobScheduler, draft: TaskTemplateDraft) -> CreatedTemplate:
    """§3.1/§9.1: creating a template always spawns its initial instance in the same
    transaction. Every check below can reject the whole save (§6.1, §6.5, §6.8) and none
    of it is persisted until all of them pass.
    """
    now = utcnow()

    if draft.recurrence.anchor == "completion" and draft.type != "flexible":
        raise TemplateValidationError("invalid_recurrence_anchor", 'anchor: "completion" is only valid on flexible templates.')

    settings = _require_settings(db)

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
        jobs.schedule_at(
            job_key=dependency_at_risk_job_key(instance.id), run_at=instance.deadline - _DEPENDENCY_AT_RISK_THRESHOLD
        )

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
        jobs.schedule_at(job_key=overdue_job_key(instance.id), run_at=scheduled_time)
        for offset in template.reminder_offsets_minutes:
            jobs.schedule_at(job_key=reminder_job_key(instance.id, offset), run_at=scheduled_time - timedelta(minutes=offset))
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


#: Fields "this and future" propagates onto a non-detached live instance - the same
#: content set §3.10 lists for the "this occurrence" edit scope. Deliberately not
#: including fixed_time_of_day -> scheduled_time re-projection or deadline_offset_minutes
#: -> deadline recomputation here: neither is exercised by any of Stage 5's required
#: tests, and both need real conflict/re-placement handling to do properly rather than
#: half-implementing silently. Documented gap, not an oversight - Stage 6/8 can pick it
#: up alongside the completion-triggered generation call they already own.
_PROPAGATABLE_FIELDS = ("name", "description", "location", "priority", "estimated_duration_minutes")

_TERMINAL_STATUSES = frozenset({"completed", "dismissed"})


@dataclass(frozen=True)
class ArchiveResult:
    template: TaskTemplate
    incomplete_instance_ids: tuple[str, ...]


def archive_template(db: Session, jobs: JobScheduler, template_id: str) -> ArchiveResult:
    """§3.8: soft-delete - `archived=true`, keeping the row so historical instances'
    `template_id` references stay valid. Returns the ids of any non-terminal instances
    left behind, for the frontend's confirmation dialog to list.

    Cancels the calendar-anchor occurrence-boundary job if one exists (architecture-plan
    §4.1 Rev 3: forgetting that cancellation "leaves a job that will resurrect a series
    the user just ended"). `app.jobs.handlers.run_occurrence_boundary` also no-ops
    defensively on an archived template - this is the direct cancellation, that is the
    fallback for the gap before the next startup reconciliation pass (§4.2 item 3).
    """
    repo = TaskTemplateRepository(db)
    template = repo.get(template_id)
    if template is None:
        raise TemplateValidationError("not_found", f"TaskTemplate {template_id} not found")

    incomplete = tuple(
        instance.id
        for instance in TaskInstanceRepository(db).list_by_template(template_id)
        if instance.status not in _TERMINAL_STATUSES
    )
    archived = repo.archive(template_id)
    if template.recurrence.pattern != "one_time" and template.recurrence.anchor == "calendar":
        jobs.cancel(job_key=occurrence_boundary_job_key(template_id))
    return ArchiveResult(template=archived, incomplete_instance_ids=incomplete)


def edit_template_this_and_future(db: Session, jobs: JobScheduler, template_id: str, *, patch: dict[str, object]) -> TaskTemplate:
    """§3.10 "this and future": writes the template, then - unless the currently-live
    instance is already `detached` - propagates matching fields to it in the same
    transaction, re-entering §6.2 if the propagation invalidates its placement.
    """
    repo = TaskTemplateRepository(db)
    current = repo.get(template_id)
    if current is None:
        raise TemplateValidationError("not_found", f"TaskTemplate {template_id} not found")

    prospective = current.model_copy(update=patch)
    if prospective.recurrence.anchor == "completion" and prospective.type != "flexible":
        raise TemplateValidationError("invalid_recurrence_anchor", 'anchor: "completion" is only valid on flexible templates.')

    settings = _require_settings(db)
    duration_or_hours_changed = "estimated_duration_minutes" in patch or "active_hours_override" in patch
    if prospective.type == "flexible" and duration_or_hours_changed:
        effective_hours = build_active_hours_map(settings, prospective.active_hours_override)
        if not validate_feasible_duration(prospective.estimated_duration_minutes, effective_hours):
            raise TemplateValidationError(
                "infeasible_duration",
                "estimated_duration_minutes does not fit any day's effective active-hours window.",
            )

    new_template = repo.update(prospective)

    live = _find_live_instance(db, template_id)
    if live is not None and not live.detached:
        _propagate_to_instance(db, jobs, instance=live, template=new_template, settings=settings, patch=patch)

    return new_template


def _find_live_instance(db: Session, template_id: str) -> TaskInstance | None:
    """The most recently generated non-terminal instance - §3.10's "currently-live" one."""
    for instance in TaskInstanceRepository(db).list_by_template(template_id):  # most-recent-first
        if instance.status not in _TERMINAL_STATUSES:
            return instance
    return None


def _propagate_to_instance(
    db: Session,
    jobs: JobScheduler,
    *,
    instance: TaskInstance,
    template: TaskTemplate,
    settings: UserSettings,
    patch: dict[str, object],
) -> TaskInstance:
    instance_updates: dict[str, object] = {}
    for field in _PROPAGATABLE_FIELDS:
        if field in patch:
            instance_updates[field] = getattr(template, field)

    updated = TaskInstanceRepository(db).update(instance.model_copy(update=instance_updates)) if instance_updates else instance

    invalidates_placement = "estimated_duration_minutes" in patch or "active_hours_override" in patch
    if template.type == "flexible" and updated.status in ("pending", "scheduled") and invalidates_placement:
        updated = place_or_defer(
            db,
            jobs,
            instance=updated.model_copy(update={"status": "pending"}),
            template=template,
            settings=settings,
            now=utcnow(),
        )
    return updated


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


def _require_settings(db: Session) -> UserSettings:
    settings = UserSettingsRepository(db).get()
    if settings is None:
        raise RuntimeError("UserSettings row missing - expected to exist from app startup (Stage 4)")
    return settings


__all__ = [
    "ArchiveResult",
    "CreatedTemplate",
    "TaskTemplateDraft",
    "TemplateValidationError",
    "archive_template",
    "create_template",
    "edit_template_this_and_future",
]
