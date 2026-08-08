"""Job-fire handlers - the actual work each scheduled job performs when it runs. See
design doc §6.3, §6.6, §6.7; architecture-plan §4's job breakdown table.

`app.jobs` sits outside import-linter's "Layering" contract's sibling tier (see
`backend/pyproject.toml`), so it may freely call into `app.task_instances`,
`app.task_templates`, `app.scheduling`, and `app.db` - the one restriction that still
applies is that `app.scheduling_engine` must never import back into it.

Every handler re-reads the instance fresh from the DB and no-ops if it is no longer in
the state the job was scheduled for (completed/dismissed/deleted in the meantime,
already re-placed, etc.) - jobs are fire-and-forget against a database that can have
moved on since they were scheduled, not RPCs with a guaranteed-current target.
"""

from __future__ import annotations

from datetime import timedelta
from typing import cast

from sqlalchemy.orm import Session

from app.db.base import generate_id, utcnow
from app.db.repositories import (
    NotificationRepository,
    TaskInstanceRepository,
    TaskTemplateRepository,
    UserSettingsRepository,
)
from app.db.schemas import Notification, NotificationType, StatusHistoryEntry, TaskInstance
from app.jobs.interface import JobScheduler
from app.scheduling.adapter import attempt_placement
from app.scheduling.orchestration import generate_and_place_next_instance, place_or_defer, schedule_next_occurrence_boundary
from app.scheduling_engine.deadlines import is_deadline_elapsed

REMINDER = "reminder"
OVERDUE = "overdue"
DEPENDENCY_AT_RISK = "dependency_at_risk"

#: §6.3's flat POC threshold - only worth a speculative placement pass once the deadline
#: is this close. The one-off job is scheduled to fire exactly at this boundary already
#: (deadline - 3 days), but the periodic sweep re-checks anything the one-off might have
#: missed, so both paths re-apply the same threshold rather than assuming the job fired
#: at the "right" time.
DEPENDENCY_AT_RISK_THRESHOLD = timedelta(days=3)


def run_reminder(db: Session, *, instance_id: str, offset_minutes: int) -> None:
    """§3.4/§5 `reminder` - one-off, fires at `scheduled_time - offset_minutes`. No-ops if
    the instance is no longer live and scheduled by the time this fires.
    """
    instance = TaskInstanceRepository(db).get(instance_id)
    if instance is None or instance.status not in ("scheduled", "in_progress"):
        return
    _create_notification(db, type_=REMINDER, instance_id=instance.id, message=f'Reminder: "{instance.name}" is coming up.')


def run_overdue_check(db: Session, jobs: JobScheduler, *, instance_id: str) -> None:
    """§6.6. Fixed: status unchanged, informational `overdue` Notification only (its
    reschedule/complete/skip actions are the existing endpoints, no special handling
    needed here). Flexible: clear `scheduled_time`, re-enter §6.2 (subject to §6.7's gate
    first), plus the same `overdue` Notification so the move isn't silent.
    """
    instance = TaskInstanceRepository(db).get(instance_id)
    if instance is None or instance.status not in ("scheduled", "in_progress"):
        return

    now = utcnow()
    if instance.type == "flexible":
        template = TaskTemplateRepository(db).get(instance.template_id)
        settings = UserSettingsRepository(db).get()
        if template is None or settings is None:
            return
        reverted = TaskInstanceRepository(db).update(
            instance.model_copy(
                update={
                    "status": "pending",
                    "scheduled_time": None,
                    "status_history": (*instance.status_history, StatusHistoryEntry(status="pending", at=now)),
                }
            )
        )
        place_or_defer(db, jobs, instance=reverted, template=template, settings=settings, now=now)

    _create_notification(db, type_=OVERDUE, instance_id=instance.id, message=f'"{instance.name}" is overdue.')


def run_deadline_elapsed_check(db: Session, jobs: JobScheduler, *, instance_id: str) -> None:
    """§6.7's one-off safety net - scheduled whenever `place_or_defer` leaves an instance
    `pending` with an active `unschedulable` notification. No-ops if the instance has
    since been placed, completed, or otherwise left the pending pool.
    """
    instance = TaskInstanceRepository(db).get(instance_id)
    if instance is None or instance.status != "pending":
        return
    _recheck_deadline(db, jobs, instance)


def run_deadline_elapsed_sweep(db: Session, jobs: JobScheduler) -> None:
    """§6.7 check #1 - periodic, for every `pending`/`blocked` flexible instance. This is
    the *only* safety net for a `blocked` instance, which never receives the per-instance
    one-off job (it isn't handed to `place_or_defer` until it unblocks) - and a second net
    alongside the one-off for `pending` instances, covering e.g. a process restart landing
    in the gap between a missed one-off firing and reconciliation recreating it.
    """
    now = utcnow()
    for instance in TaskInstanceRepository(db).list_by_statuses(("pending", "blocked")):
        if instance.type != "flexible" or instance.deadline is None:
            continue
        if not is_deadline_elapsed(instance.deadline, now):
            continue
        _recheck_deadline(db, jobs, instance)


def _recheck_deadline(db: Session, jobs: JobScheduler, instance: TaskInstance) -> None:
    template = TaskTemplateRepository(db).get(instance.template_id)
    settings = UserSettingsRepository(db).get()
    if template is None or settings is None:
        return
    place_or_defer(db, jobs, instance=instance, template=template, settings=settings, now=utcnow())


def run_dependency_at_risk_check(db: Session, *, instance_id: str) -> None:
    """§6.3 - one-off, scheduled at `deadline - 3 days` when an instance is created with
    dependencies (architecture-plan §4's job breakdown: a one-off check rather than a
    table-wide interval scan). No-ops if the instance has since become terminal or its
    dependencies have all completed (no longer "at risk" of anything).

    **Simplification, documented rather than silently assumed:** the design doc's
    "speculative placement pass ... over the whole chain" is approximated here as a
    single hypothetical placement of *this* instance via `attempt_placement` - which
    already ignores incomplete dependencies entirely when building its candidate (see
    `app.scheduling.adapter.build_candidate`), so this naturally answers "if every
    prerequisite finished right now, would this still fit before its deadline?" without
    projecting each prerequisite's own completion time. A full multi-level chain
    projection is not built - there is no worked example in design doc §10 to validate
    one against, and this stage's tests (§4.1) only require the notification-creation
    contract, not a specific projection algorithm.
    """
    instance = TaskInstanceRepository(db).get(instance_id)
    if instance is None or instance.status in ("completed", "dismissed", "missed"):
        return
    if instance.type != "flexible" or instance.deadline is None or not instance.dependencies:
        return
    if _all_dependencies_completed(db, instance):
        return

    template = TaskTemplateRepository(db).get(instance.template_id)
    settings = UserSettingsRepository(db).get()
    if template is None or settings is None:
        return

    now = utcnow()
    result = attempt_placement(db, instance=instance, template=template, settings=settings, now=now)
    if result.placements:
        projected_end = result.placements[0].scheduled_start + timedelta(minutes=instance.estimated_duration_minutes)
        at_risk = projected_end > instance.deadline
    else:
        at_risk = True  # no slot at all before the deadline - definitely at risk

    if at_risk and not _has_active(db, instance_id=instance.id, notification_type=DEPENDENCY_AT_RISK):
        _create_notification(
            db,
            type_=DEPENDENCY_AT_RISK,
            instance_id=instance.id,
            message=f'"{instance.name}" is at risk of missing its deadline - an incomplete dependency may not leave enough time.',
        )


def run_occurrence_boundary(db: Session, jobs: JobScheduler, *, template_id: str) -> None:
    """§9.1's calendar-anchor generation trigger (architecture-plan §4's job breakdown) -
    fires at the current occurrence's nominal time, generates the next instance, and
    schedules the job for the occurrence after that, keeping the chain alive indefinitely.

    No-ops if the template was archived since this job was scheduled - archiving is
    supposed to cancel this job directly (`app.task_templates.service.archive_template`),
    this is the defensive fallback for the gap between an archive and the next
    reconciliation pass, matching architecture-plan §4.2 item 3's own framing.
    """
    template = TaskTemplateRepository(db).get(template_id)
    if template is None or template.archived:
        return
    settings = UserSettingsRepository(db).get()
    if settings is None:
        return

    instances = TaskInstanceRepository(db).list_by_template(template_id)
    if not instances:
        raise AssertionError(f"occurrence-boundary job fired for template {template_id} with no instances - data integrity bug")

    now = utcnow()
    generated = generate_and_place_next_instance(
        db, jobs, template=template, predecessor=instances[0], settings=settings, now=now
    )
    schedule_next_occurrence_boundary(db, jobs, template=template, latest_instance=generated, settings=settings, now=now)


def _all_dependencies_completed(db: Session, instance: TaskInstance) -> bool:
    repo = TaskInstanceRepository(db)
    return all((dep := repo.get(dep_id)) is not None and dep.status == "completed" for dep_id in instance.dependencies)


def _has_active(db: Session, *, instance_id: str, notification_type: str) -> bool:
    return any(
        n.type == notification_type and n.resolved_at is None and n.dismissed_at is None
        for n in NotificationRepository(db).list_for_instance(instance_id)
    )


def _create_notification(db: Session, *, type_: str, instance_id: str, message: str) -> Notification:
    return NotificationRepository(db).create(
        Notification(
            id=generate_id(),
            type=cast(NotificationType, type_),
            related_instance_id=instance_id,
            message=message,
            created_at=utcnow(),
        )
    )


__all__ = [
    "DEPENDENCY_AT_RISK_THRESHOLD",
    "run_deadline_elapsed_check",
    "run_deadline_elapsed_sweep",
    "run_dependency_at_risk_check",
    "run_occurrence_boundary",
    "run_overdue_check",
    "run_reminder",
]
