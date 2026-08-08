"""Startup job-store reconciliation. See architecture-plan §4.2.

Runs once, synchronously, before the app starts serving traffic (`app.main`'s lifespan).
Jobs are event-driven rather than periodic scans (§4), which means a process killed
mid-batch can leave SQLite and the job store silently out of sync with no later scan that
would ever notice on its own - this closes that gap.

Items 1-2 reconcile the *job store* against the database (recreate missing jobs, cancel
orphans). Items 3-4 reconcile *missed events* - work that should have happened while the
process was down and that no future event will re-trigger, since the event that would
have triggered it has already been consumed.
"""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy.orm import Session

from app.db.base import utcnow
from app.db.repositories import TaskInstanceRepository, TaskTemplateRepository, UserSettingsRepository
from app.jobs.handlers import DEPENDENCY_AT_RISK_THRESHOLD
from app.jobs.interface import (
    JobScheduler,
    deadline_elapsed_job_key,
    dependency_at_risk_job_key,
    occurrence_boundary_job_key,
    overdue_job_key,
    reminder_job_key,
)
from app.scheduling.orchestration import schedule_next_occurrence_boundary
from app.task_instances.service import promote_if_unblocked

_LIVE_SCHEDULED_STATUSES = ("scheduled", "in_progress")


def reconcile_on_startup(db: Session, jobs: JobScheduler) -> None:
    """Runs all four reconciliation items in sequence. Idempotent - every `schedule_at`
    call replaces any existing job under the same key, and every `cancel` is a no-op if
    nothing exists, so running this twice (e.g. two restarts in a row) is harmless.
    """
    _recreate_or_cancel_instance_jobs(db, jobs)
    _reconcile_occurrence_boundary_jobs(db, jobs)
    _run_missed_unblocks(db, jobs)


def _recreate_or_cancel_instance_jobs(db: Session, jobs: JobScheduler) -> None:
    """Items 1-2: every `scheduled`/`in_progress` instance should have its expected jobs
    (reminders, overdue check); every `pending` instance should have a deadline-elapsed
    check; every `blocked` instance should have a dependency-at-risk check and nothing
    else; every instance that has left all of that (terminal, or `missed`) should have no
    jobs at all. `schedule_at`'s replace-existing semantics make "recreate" and
    "reschedule-to-the-same-time" the same call - no need to check whether a job already
    exists first.
    """
    repo = TaskInstanceRepository(db)
    templates_by_id = {t.id: t for t in TaskTemplateRepository(db).list(include_archived=True)}

    for instance in repo.list_by_statuses(_LIVE_SCHEDULED_STATUSES):
        if instance.scheduled_time is None:
            continue
        jobs.schedule_at(job_key=overdue_job_key(instance.id), run_at=instance.scheduled_time)
        template = templates_by_id.get(instance.template_id)
        if template is not None:
            for offset in template.reminder_offsets_minutes:
                jobs.schedule_at(
                    job_key=reminder_job_key(instance.id, offset), run_at=instance.scheduled_time - timedelta(minutes=offset)
                )
        jobs.cancel(job_key=deadline_elapsed_job_key(instance.id))
        jobs.cancel(job_key=dependency_at_risk_job_key(instance.id))

    for instance in repo.list_by_statuses(("pending",)):
        jobs.cancel(job_key=dependency_at_risk_job_key(instance.id))
        if instance.deadline is not None:
            jobs.schedule_at(job_key=deadline_elapsed_job_key(instance.id), run_at=instance.deadline)

    for instance in repo.list_by_statuses(("blocked",)):
        # Only dependency-at-risk belongs to a blocked instance - reminder/overdue never
        # applied (no scheduled_time), and deadline-elapsed for blocked instances is the
        # periodic sweep's job (§6.7 check #1), not a per-instance one-off.
        jobs.cancel(job_key=overdue_job_key(instance.id))
        jobs.cancel(job_key=deadline_elapsed_job_key(instance.id))
        template = templates_by_id.get(instance.template_id)
        if template is not None:
            for offset in template.reminder_offsets_minutes:
                jobs.cancel(job_key=reminder_job_key(instance.id, offset))
        if instance.deadline is not None:
            jobs.schedule_at(
                job_key=dependency_at_risk_job_key(instance.id), run_at=instance.deadline - DEPENDENCY_AT_RISK_THRESHOLD
            )

    for instance in repo.list_by_statuses(("missed", "completed", "dismissed")):
        jobs.cancel_all_for_instance(instance_id=instance.id)


def _reconcile_occurrence_boundary_jobs(db: Session, jobs: JobScheduler) -> None:
    """Item 3: exactly one pending occurrence-boundary job per non-archived, non-`one_time`,
    `calendar`-anchored template. If its nominal time already passed while the process was
    down, fire it immediately rather than silently skipping the occurrence - matching the
    "must not silently end the series" principle §9.1 exists to enforce.
    """
    settings = UserSettingsRepository(db).get()
    if settings is None:
        return
    now = utcnow()

    for template in TaskTemplateRepository(db).list(include_archived=True):
        recurring_calendar = template.recurrence.pattern != "one_time" and template.recurrence.anchor == "calendar"
        if template.archived or not recurring_calendar:
            jobs.cancel(job_key=occurrence_boundary_job_key(template.id))
            continue

        instances = TaskInstanceRepository(db).list_by_template(template.id)
        if not instances:
            continue  # generation is mid-transaction elsewhere or genuinely missing - not this pass's job to fix
        schedule_next_occurrence_boundary(db, jobs, template=template, latest_instance=instances[0], settings=settings, now=now)


def _run_missed_unblocks(db: Session, jobs: JobScheduler) -> None:
    """Item 4: any `blocked` instance whose dependencies have all since reached `completed`
    - the reconciliation counterpart to §6.9's event hook, for a process that died between
    a dependency completing and its dependent being placed.
    """
    now = utcnow()
    for instance in TaskInstanceRepository(db).list_by_statuses(("blocked",)):
        promote_if_unblocked(db, jobs, instance, now=now)


__all__ = ["reconcile_on_startup"]
