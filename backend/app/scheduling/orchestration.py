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
from app.jobs.interface import JobScheduler, deadline_elapsed_job_key, overdue_job_key, reminder_job_key
from app.scheduling.adapter import attempt_placement
from app.scheduling_engine.deadlines import is_deadline_elapsed

#: Notification types Stage 5 creates at the trigger points it owns (design doc §5) -
#: everything else in the table (reminder, sync_conflict, dependency_at_risk, overdue) is
#: job/periodic-scan driven and deferred to Stage 6/7.
UNSCHEDULABLE = "unschedulable"
BUDGET_EXCEEDED = "budget_exceeded"
DEADLINE_MISSED = "deadline_missed"


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


__all__ = ["BUDGET_EXCEEDED", "DEADLINE_MISSED", "UNSCHEDULABLE", "place_or_defer"]
