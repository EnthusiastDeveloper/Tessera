"""Shared "place a pending flexible instance" orchestration - the §6.7 missed-gate check,
§6.2 placement, `unschedulable`/`budget_exceeded`/`deadline_missed` notification
creation/self-resolution, and job-stub (re)scheduling, all in one place.

Both `app.task_templates` (a freshly-created instance) and `app.task_instances`
(dependency unblock, extend-deadline, this-and-future propagation invalidating a
placement) need this identical sequence. They are independent siblings by the
import-linter "Layering" contract and must not import each other, so - like
`app.scheduling.adapter` - this lives in the shared tier below them rather than being
owned by (and duplicated for) either one. Unlike `adapter.py`, this module *does* create
Notification rows and call the job-scheduler stub: that business meaning is identical
for every caller, so centralizing it here is the same "fix it once" reasoning as the
adapter itself, not a layering violation - `app.scheduling` sits above `app.db` (where
`NotificationRepository` lives) and `app.jobs` is unrestricted by the contract entirely.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import cast

from sqlalchemy.orm import Session

from app.db.base import generate_id
from app.db.repositories import NotificationRepository, TaskInstanceRepository
from app.db.schemas import (
    Notification,
    NotificationType,
    StatusHistoryEntry,
    TaskInstance,
    TaskInstanceStatus,
    TaskTemplate,
    UserSettings,
)
from app.jobs.interface import (
    JobScheduler,
    deadline_elapsed_job_key,
    occurrence_boundary_job_key,
    overdue_job_key,
    reminder_job_key,
)
from app.scheduling.adapter import attempt_placement, gather_external_obstacles, has_fixed_conflict
from app.scheduling.generation import generate_next_instance
from app.scheduling_engine.deadlines import is_deadline_elapsed

#: Notification types Stage 5 creates at the trigger points it owns (design doc §5) -
#: everything else in the table (reminder, sync_conflict, dependency_at_risk, overdue) is
#: job/periodic-scan driven and deferred to Stage 6/7.
UNSCHEDULABLE = "unschedulable"
BUDGET_EXCEEDED = "budget_exceeded"
DEADLINE_MISSED = "deadline_missed"
#: Stage 6 addition - see generate_and_place_next_instance's docstring for why an
#: auto-generated fixed instance gets a Notification instead of a synchronous rejection.
CREATION_CONFLICT = "creation_conflict"
#: Stage 7 addition - §6.4's fixed-instance collision Notification.
SYNC_CONFLICT = "sync_conflict"


def place_or_defer(
    db: Session,
    jobs: JobScheduler,
    *,
    instance: TaskInstance,
    template: TaskTemplate,
    settings: UserSettings,
    now: datetime,
) -> TaskInstance:
    """`instance` must already be `pending` (or about to become so) and `flexible`, with a
    set `deadline`. Runs the §6.7 gate first - a flexible instance is never handed to the
    placement algorithm with an already-elapsed deadline (design doc §6.7's inverted-window
    failure mode) - then places it, resolves/creates notifications, and (re)wires jobs.
    Returns the persisted, up-to-date instance.
    """
    if instance.deadline is not None and is_deadline_elapsed(instance.deadline, now):
        return _transition_to_missed(db, jobs, instance=instance, now=now)

    result = attempt_placement(db, instance=instance, template=template, settings=settings, now=now)

    if result.placements:
        placement = result.placements[0]
        updated = TaskInstanceRepository(db).update(
            instance.model_copy(
                update={
                    "status": _status("scheduled"),
                    "scheduled_time": placement.scheduled_start,
                    "status_history": (*instance.status_history, _status_entry("scheduled", now)),
                }
            )
        )
        _resolve_active(db, instance_id=instance.id, notification_type=UNSCHEDULABLE, now=now)
        if placement.budget_overridden:
            _create_notification(
                db, type_=BUDGET_EXCEEDED, instance_id=instance.id, message=_budget_exceeded_message(template), now=now
            )
        jobs.cancel(job_key=deadline_elapsed_job_key(instance.id))
        _schedule_reminder_and_overdue_jobs(jobs, updated, template)
        return updated

    # unschedulable - stays pending, but flag it if this is a newly-surfaced condition.
    if not _has_active(db, instance_id=instance.id, notification_type=UNSCHEDULABLE):
        _create_notification(
            db,
            type_=UNSCHEDULABLE,
            instance_id=instance.id,
            message=f'"{template.name}" has no available slot before its deadline.',
            now=now,
        )
    if instance.deadline is not None:
        jobs.schedule_at(job_key=deadline_elapsed_job_key(instance.id), run_at=instance.deadline)
    return instance


def generate_and_place_next_instance(
    db: Session,
    jobs: JobScheduler,
    *,
    template: TaskTemplate,
    predecessor: TaskInstance | None,
    settings: UserSettings,
    now: datetime,
) -> TaskInstance:
    """§9.1 - generates the next occurrence from `template` (never from a possibly-detached
    predecessor's overridden fields, see `app.scheduling.generation`'s module docstring),
    persists it with no dependencies (§3.2's `TaskTemplate` carries no `dependencies` field
    for generation to copy - a template has no standing memory of what its instances
    depended on), and places it immediately if flexible.

    Shared by both anchor mechanisms' triggers - the completion-anchor event hook
    (`app.task_instances.service.complete`/`dismiss`) and the calendar-anchor
    occurrence-boundary job (`app.jobs.handlers.run_occurrence_boundary`) - which are
    independent siblings under the layering contract and both need this identical
    sequence, hence its home here rather than in either one.

    A newly generated **fixed** instance is never rejected on conflict the way a
    user-initiated create is (Example A) - there is no request to reject, and silently
    skipping the occurrence would break the series exactly as design doc §9.1 warns
    against for a missed generation call. Instead it is persisted and flagged with a
    `creation_conflict` Notification so the user notices and reschedules it manually.
    """
    generated = generate_next_instance(template, predecessor=predecessor, now=now, timezone=settings.timezone)
    status: TaskInstanceStatus = "scheduled" if template.type == "fixed" else "pending"
    instance = TaskInstanceRepository(db).create(
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
            status=status,
            status_history=(StatusHistoryEntry(status=status, at=now),),
            dependencies=(),
            generated_at=now,
            created_at=now,
            updated_at=now,
            version=1,
        )
    )

    if template.type == "fixed":
        assert instance.scheduled_time is not None
        end = instance.scheduled_time + timedelta(minutes=instance.estimated_duration_minutes)
        if has_fixed_conflict(db, start=instance.scheduled_time, end=end, exclude_instance_id=instance.id):
            _create_notification(
                db,
                type_=CREATION_CONFLICT,
                instance_id=instance.id,
                message=f'"{instance.name}" was generated at a time that collides with an existing fixed task or external event.',
                now=now,
            )
        _schedule_reminder_and_overdue_jobs(jobs, instance, template)
        return instance

    return place_or_defer(db, jobs, instance=instance, template=template, settings=settings, now=now)


def schedule_next_occurrence_boundary(
    db: Session,
    jobs: JobScheduler,
    *,
    template: TaskTemplate,
    latest_instance: TaskInstance,
    settings: UserSettings,
    now: datetime,
) -> None:
    """Schedules the one-off job that will generate the occurrence *after* `latest_instance`
    (architecture-plan §4's job breakdown: "calendar anchor - a one-off job at the next
    occurrence's nominal time ... on firing it generates the instance and schedules the
    next boundary job"). Only meaningful for a non-`one_time`, `calendar`-anchored
    template - callers are expected to have already checked that.
    """
    upcoming = generate_next_instance(template, predecessor=latest_instance, now=now, timezone=settings.timezone)
    jobs.schedule_at(job_key=occurrence_boundary_job_key(template.id), run_at=upcoming.nominal_date)


def resolve_cleared_sync_conflicts(db: Session, *, now: datetime) -> None:
    """§3.9: a `sync_conflict` auto-resolves once its instance no longer overlaps any
    filtered external-event obstacle (§7) - whether because the event moved/was removed
    (`app.calendar_sync.service.sync_connection`'s poll) or the instance itself was
    rescheduled clear of it (§6.6 Rev 7 manual reschedule, `app.task_instances.service.reschedule`).
    A global sweep, not scoped to one connection or one instance - §3.9 draws no such
    distinction, and both call sites already hold a fresh `now`.
    """
    notification_repo = NotificationRepository(db)
    instance_repo = TaskInstanceRepository(db)
    external_obstacles = gather_external_obstacles(db)

    for notification in notification_repo.list_active():
        if notification.type != SYNC_CONFLICT:
            continue
        instance = instance_repo.get(notification.related_instance_id)
        if instance is None or instance.status != "scheduled" or instance.scheduled_time is None:
            notification_repo.update(notification.model_copy(update={"resolved_at": now}))
            continue
        end = instance.scheduled_time + timedelta(minutes=instance.estimated_duration_minutes)
        still_conflicts = any(instance.scheduled_time < obstacle.end and obstacle.start < end for obstacle in external_obstacles)
        if not still_conflicts:
            notification_repo.update(notification.model_copy(update={"resolved_at": now}))


def _transition_to_missed(db: Session, jobs: JobScheduler, *, instance: TaskInstance, now: datetime) -> TaskInstance:
    updated = TaskInstanceRepository(db).update(
        instance.model_copy(
            update={
                "status": _status("missed"),
                "status_history": (*instance.status_history, _status_entry("missed", now)),
            }
        )
    )
    _create_notification(
        db,
        type_=DEADLINE_MISSED,
        instance_id=instance.id,
        message=f'"{updated.name}"\'s deadline has elapsed.',
        now=now,
    )
    jobs.cancel_all_for_instance(instance_id=instance.id)
    return updated


def _schedule_reminder_and_overdue_jobs(jobs: JobScheduler, instance: TaskInstance, template: TaskTemplate) -> None:
    if instance.scheduled_time is None:
        return
    jobs.schedule_at(job_key=overdue_job_key(instance.id), run_at=instance.scheduled_time)
    for offset in template.reminder_offsets_minutes:
        jobs.schedule_at(
            job_key=reminder_job_key(instance.id, offset), run_at=instance.scheduled_time - timedelta(minutes=offset)
        )


def _has_active(db: Session, *, instance_id: str, notification_type: str) -> bool:
    return any(
        n.type == notification_type and n.resolved_at is None and n.dismissed_at is None
        for n in NotificationRepository(db).list_for_instance(instance_id)
    )


def _resolve_active(db: Session, *, instance_id: str, notification_type: str, now: datetime) -> None:
    repo = NotificationRepository(db)
    for notification in repo.list_for_instance(instance_id):
        if notification.type == notification_type and notification.resolved_at is None:
            repo.update(notification.model_copy(update={"resolved_at": now}))


def _create_notification(db: Session, *, type_: str, instance_id: str, message: str, now: datetime) -> Notification:
    return NotificationRepository(db).create(
        Notification(
            id=generate_id(),
            type=cast(NotificationType, type_),
            related_instance_id=instance_id,
            message=message,
            created_at=now,
        )
    )


def _budget_exceeded_message(template: TaskTemplate) -> str:
    return f'"{template.name}" was placed by overriding its daily time budget to meet its deadline.'


def _status(value: str) -> TaskInstanceStatus:
    return cast(TaskInstanceStatus, value)


def _status_entry(status: str, at: datetime) -> StatusHistoryEntry:
    return StatusHistoryEntry(status=_status(status), at=at)


__all__ = [
    "BUDGET_EXCEEDED",
    "CREATION_CONFLICT",
    "DEADLINE_MISSED",
    "SYNC_CONFLICT",
    "UNSCHEDULABLE",
    "generate_and_place_next_instance",
    "place_or_defer",
    "resolve_cleared_sync_conflicts",
    "schedule_next_occurrence_boundary",
]
