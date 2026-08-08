"""TaskInstance service: this-occurrence edit, reschedule, complete, extend-deadline,
delete. See design doc §3.3, §3.8, §3.10, §4, §6.5-§6.9; architecture-plan §4.1 (job
co-location - real job calls are stubs here, Stage 6 wires the real adapter behind the
same interface without touching call sites).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, cast

from sqlalchemy.orm import Session

from app.db.base import utcnow
from app.db.repositories import (
    NotificationRepository,
    TaskInstanceRepository,
    TaskTemplateRepository,
    UserSettingsRepository,
)
from app.db.schemas import StatusHistoryEntry, TaskInstance, TaskTemplate, UserSettings
from app.jobs.interface import JobScheduler, overdue_job_key, reminder_job_key
from app.scheduling.adapter import build_active_hours_map, has_fixed_conflict
from app.scheduling.orchestration import DEADLINE_MISSED, generate_and_place_next_instance, place_or_defer
from app.scheduling_engine.feasibility import validate_feasible_duration

_TERMINAL_STATUSES = frozenset({"completed", "dismissed"})
#: Fields a "this occurrence" edit may touch directly (§3.10). scheduled_time is
#: deliberately excluded - retiming a fixed instance goes through `reschedule()`, which
#: needs §6.5's conflict validation `PATCH` doesn't run.
_THIS_OCCURRENCE_FIELDS = ("name", "description", "location", "priority", "estimated_duration_minutes", "deadline")


class InstanceValidationError(Exception):
    """`code` maps to the API error envelope (architecture-plan §3)."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class DeleteResult:
    deleted_instance_id: str
    unblocked_instance_ids: tuple[str, ...]


def edit_this_occurrence(db: Session, jobs: JobScheduler, instance_id: str, *, patch: dict[str, Any]) -> TaskInstance:
    """§3.10 "this occurrence": touches only the live instance, sets `detached=True`. A
    duration change is checked against §6.8 the same way a template-level one is; a
    duration or deadline change on a non-terminal flexible instance re-enters §6.2.
    """
    instance = _require_instance(db, instance_id)
    template = _require_template(db, instance.template_id)
    settings = _require_settings(db)

    unknown = set(patch) - set(_THIS_OCCURRENCE_FIELDS)
    if unknown:
        raise InstanceValidationError("invalid_field", f"Fields not editable via this-occurrence scope: {sorted(unknown)}")
    if "deadline" in patch and instance.type != "flexible":
        raise InstanceValidationError("invalid_field", "deadline can only be edited on a flexible instance.")

    if "estimated_duration_minutes" in patch and instance.type == "flexible":
        effective_hours = build_active_hours_map(settings, template.active_hours_override)
        if not validate_feasible_duration(cast(int, patch["estimated_duration_minutes"]), effective_hours):
            raise InstanceValidationError(
                "infeasible_duration", "estimated_duration_minutes does not fit any day's effective active-hours window."
            )

    now = utcnow()
    updated = TaskInstanceRepository(db).update(instance.model_copy(update={**patch, "detached": True}))

    invalidates_placement = "estimated_duration_minutes" in patch or "deadline" in patch
    if updated.type == "flexible" and updated.status in ("pending", "scheduled") and invalidates_placement:
        updated = place_or_defer(
            db, jobs, instance=updated.model_copy(update={"status": "pending"}), template=template, settings=settings, now=now
        )
    return updated


def reschedule(db: Session, jobs: JobScheduler, instance_id: str, *, new_scheduled_time: datetime) -> TaskInstance:
    """§6.6/§3.10: retiming a `fixed` instance - a "this occurrence" edit of `scheduled_time`
    specifically, so it gets §6.5's hard-block validation `PATCH` doesn't run.
    """
    instance = _require_instance(db, instance_id)
    if instance.type != "fixed":
        raise InstanceValidationError("invalid_field", "Only fixed instances can be rescheduled.")

    end = new_scheduled_time + timedelta(minutes=instance.estimated_duration_minutes)
    if has_fixed_conflict(db, start=new_scheduled_time, end=end, exclude_instance_id=instance.id):
        raise InstanceValidationError("creation_conflict", "This time collides with an existing fixed task or external event.")

    updated = TaskInstanceRepository(db).update(
        instance.model_copy(update={"scheduled_time": new_scheduled_time, "detached": True})
    )
    jobs.cancel(job_key=overdue_job_key(instance.id))
    jobs.schedule_at(job_key=overdue_job_key(instance.id), run_at=new_scheduled_time)
    template = _require_template(db, instance.template_id)
    for offset in template.reminder_offsets_minutes:
        jobs.cancel(job_key=reminder_job_key(instance.id, offset))
        jobs.schedule_at(job_key=reminder_job_key(instance.id, offset), run_at=new_scheduled_time - timedelta(minutes=offset))
    return updated


def complete(db: Session, jobs: JobScheduler, instance_id: str) -> TaskInstance:
    """§3.3/§4: reachable directly from `pending`, `blocked`, or `scheduled` - not only
    via `in_progress`. Unblocks dependents (§6.9) and, for a `completion`-anchored
    template, generates the successor - both in the same transaction as the completion
    that triggered them (architecture-plan §4.1 Rev 3: "Completion is now two side
    effects, not one").
    """
    instance = _require_instance(db, instance_id)
    if instance.status in _TERMINAL_STATUSES:
        raise InstanceValidationError("invalid_field", f"Cannot complete a {instance.status} instance - it is terminal.")
    now = utcnow()

    updated = TaskInstanceRepository(db).update(
        instance.model_copy(
            update={
                "status": "completed",
                "completed_at": now,
                "status_history": (*instance.status_history, StatusHistoryEntry(status="completed", at=now)),
            }
        )
    )
    jobs.cancel_all_for_instance(instance_id=instance.id)
    _resolve_notifications(db, instance_id=instance.id, types=(DEADLINE_MISSED,), now=now)
    _unblock_dependents(db, jobs, completed_instance_id=instance.id, now=now)

    template = _require_template(db, instance.template_id)
    if template.recurrence.anchor == "completion" and not template.archived:
        settings = _require_settings(db)
        generate_and_place_next_instance(db, jobs, template=template, predecessor=updated, settings=settings, now=now)

    return updated


def extend_deadline(db: Session, jobs: JobScheduler, instance_id: str, *, new_deadline: datetime) -> TaskInstance:
    """§6.7 resolution path: `missed` -> `pending`, a "this occurrence" edit of `deadline`
    (sets `detached=True`), re-entering §6.2 immediately (design doc §6.2's own trigger
    list: "a new flexible instance enters pending").
    """
    instance = _require_instance(db, instance_id)
    if instance.status != "missed":
        raise InstanceValidationError("invalid_field", "extend-deadline only applies to a missed instance.")

    now = utcnow()
    template = _require_template(db, instance.template_id)
    settings = _require_settings(db)

    pending_instance = TaskInstanceRepository(db).update(
        instance.model_copy(
            update={
                "status": "pending",
                "deadline": new_deadline,
                "detached": True,
                "status_history": (*instance.status_history, StatusHistoryEntry(status="pending", at=now)),
            }
        )
    )
    _resolve_notifications(db, instance_id=instance.id, types=(DEADLINE_MISSED,), now=now)
    return place_or_defer(db, jobs, instance=pending_instance, template=template, settings=settings, now=now)


def delete_instance(db: Session, jobs: JobScheduler, instance_id: str) -> DeleteResult:
    """§3.8: unlink, not cascade. Deleting an instance other instances depend on just
    removes the link; if that leaves a dependent with zero remaining dependencies, it
    unblocks and is placed immediately, in the same transaction (matching §6.9's
    co-location principle - design doc Example D's own expected outcome is "placed by
    6.2", not merely "eligible for a later pass").
    """
    repo = TaskInstanceRepository(db)
    _require_instance(db, instance_id)  # 404s cleanly if the id is unknown
    dependents = repo.list_dependents(instance_id)

    jobs.cancel_all_for_instance(instance_id=instance_id)
    repo.delete(instance_id)

    unblocked: list[str] = []
    now = utcnow()
    for dependent in dependents:
        refreshed = repo.get(dependent.id)
        if refreshed is None:
            continue
        promoted = promote_if_unblocked(db, jobs, refreshed, now=now)
        if promoted is not None:
            unblocked.append(promoted.id)

    return DeleteResult(deleted_instance_id=instance_id, unblocked_instance_ids=tuple(unblocked))


def _unblock_dependents(db: Session, jobs: JobScheduler, *, completed_instance_id: str, now: datetime) -> None:
    repo = TaskInstanceRepository(db)
    for dependent in repo.list_dependents(completed_instance_id):
        refreshed = repo.get(dependent.id)
        if refreshed is None:
            continue
        promote_if_unblocked(db, jobs, refreshed, now=now)


def promote_if_unblocked(db: Session, jobs: JobScheduler, instance: TaskInstance, *, now: datetime) -> TaskInstance | None:
    """If `instance` is `blocked` and every dependency has since reached `completed`,
    promote it to `pending` and place it immediately if flexible (§6.9). Returns the
    updated instance, or `None` if it wasn't eligible.

    Public - besides the two direct triggers above (completion, deletion), Stage 6's
    startup reconciliation (architecture-plan §4.2 item 4) needs this exact check outside
    either normal trigger path, to catch a dependency that completed while the process
    that should have unblocked its dependent was down.
    """
    if instance.status != "blocked" or not _all_dependencies_completed(db, instance):
        return None
    repo = TaskInstanceRepository(db)
    template = _require_template(db, instance.template_id)
    settings = _require_settings(db)
    promoted = repo.update(
        instance.model_copy(
            update={
                "status": "pending",
                "status_history": (*instance.status_history, StatusHistoryEntry(status="pending", at=now)),
            }
        )
    )
    if promoted.type == "flexible":
        return place_or_defer(db, jobs, instance=promoted, template=template, settings=settings, now=now)
    return promoted


def _all_dependencies_completed(db: Session, instance: TaskInstance) -> bool:
    repo = TaskInstanceRepository(db)
    return all((dep := repo.get(dep_id)) is not None and dep.status == "completed" for dep_id in instance.dependencies)


def _resolve_notifications(db: Session, *, instance_id: str, types: tuple[str, ...], now: datetime) -> None:
    repo = NotificationRepository(db)
    for notification in repo.list_for_instance(instance_id):
        if notification.type in types and notification.resolved_at is None:
            repo.update(notification.model_copy(update={"resolved_at": now}))


def _require_instance(db: Session, instance_id: str) -> TaskInstance:
    instance = TaskInstanceRepository(db).get(instance_id)
    if instance is None:
        raise InstanceValidationError("not_found", f"TaskInstance {instance_id} not found")
    return instance


def _require_template(db: Session, template_id: str) -> TaskTemplate:
    template = TaskTemplateRepository(db).get(template_id)
    if template is None:
        raise RuntimeError(f"TaskTemplate {template_id} not found for an existing TaskInstance - data integrity bug")
    return template


def _require_settings(db: Session) -> UserSettings:
    settings = UserSettingsRepository(db).get()
    if settings is None:
        raise RuntimeError("UserSettings row missing - expected to exist from app startup (Stage 4)")
    return settings


__all__ = [
    "DeleteResult",
    "InstanceValidationError",
    "complete",
    "delete_instance",
    "edit_this_occurrence",
    "extend_deadline",
    "promote_if_unblocked",
    "reschedule",
]
