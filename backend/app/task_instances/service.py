"""TaskInstance service: this-occurrence edit, reschedule, complete, extend-deadline,
delete. See design doc §3.3, §3.8, §3.10, §4, §6.5-§6.9; architecture-plan §4.1 (job
co-location - real job calls are stubs here, Stage 6 wires the real adapter behind the
same interface without touching call sites).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Literal, cast

from sqlalchemy.orm import Session

from app.db.base import utcnow
from app.db.repositories import (
    TaskInstanceRepository,
    TaskTemplateRepository,
)
from app.db.schemas import StatusHistoryEntry, TaskInstance, TaskTemplate
from app.jobs.interface import JobScheduler
from app.scheduling.adapter import build_active_hours_map, has_fixed_conflict
from app.scheduling.orchestration import (
    DEADLINE_MISSED,
    TERMINAL_STATUSES,
    UNSCHEDULABLE,
    all_dependencies_completed,
    archive_template_and_cancel_jobs,
    displace_flexible_under,
    fixed_slot_change_conflicts,
    generate_and_place_next_instance,
    has_active_notification,
    place_or_defer,
    require_settings,
    resolve_cleared_sync_conflicts,
    resolve_notifications,
    return_to_pending,
    schedule_reminder_and_overdue_jobs,
)
from app.scheduling_engine.feasibility import validate_feasible_duration

#: Fields a "this occurrence" edit may touch directly (§3.10). scheduled_time is
#: deliberately excluded - retiming a fixed instance goes through `reschedule()`, which
#: needs §6.5's conflict validation `PATCH` doesn't run.
_THIS_OCCURRENCE_FIELDS = ("name", "description", "location", "priority", "estimated_duration_minutes", "deadline")
#: §3.8's dismiss side effect: "auto-resolve its open notifications per 3.9 (overdue,
#: unschedulable, deadline_missed): the condition has cleared because the user has closed
#: the occurrence out." `sync_conflict` is deliberately not listed here - it already
#: auto-resolves through `resolve_cleared_sync_conflicts` once the instance is no longer
#: `scheduled` (see that function's `_SYNC_CONFLICT_MOOT_STATUSES`), no second mechanism needed.
_DISMISS_RESOLVED_NOTIFICATION_TYPES = ("overdue", UNSCHEDULABLE, DEADLINE_MISSED)

DeleteScope = Literal["this_occurrence", "this_and_future"]


class InstanceValidationError(Exception):
    """`code` maps to the API error envelope (architecture-plan §3). `details` carries
    the `conflict` code's required payload (architecture-plan §3's error table: the body
    "must name the conflicting fields and their current server-side values").
    """

    def __init__(self, code: str, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.details = details


@dataclass(frozen=True)
class DeleteResult:
    deleted_instance_id: str
    unblocked_instance_ids: tuple[str, ...]


def list_instances(
    db: Session, *, status: str | None = None, priority: int | None = None, type: str | None = None, view: str | None = None
) -> tuple[TaskInstance, ...]:
    """`GET /task-instances` (architecture-plan §3). `view=backlog` is the Backlog view
    (design doc §8.1, architecture-plan §3 Rev 3): "a filter on the existing collection,
    not its own resource" - `blocked`/`missed` instances, plus `pending` instances
    carrying an active `unschedulable` notification. Not specified whether `view=backlog`
    may be combined with the other filters - chosen behavior: it takes over the query
    entirely and the other filters are ignored, since the Backlog view already fully
    determines its own status set.
    """
    if view == "backlog":
        return _list_backlog(db)
    return TaskInstanceRepository(db).list_filtered(status=status, priority=priority, type_=type)


def _list_backlog(db: Session) -> tuple[TaskInstance, ...]:
    repo = TaskInstanceRepository(db)
    blocked_or_missed = repo.list_by_statuses(("blocked", "missed"))
    pending_unschedulable = tuple(
        instance
        for instance in repo.list_by_statuses(("pending",))
        if has_active_notification(db, instance_id=instance.id, notification_type=UNSCHEDULABLE)
    )
    return blocked_or_missed + pending_unschedulable


def edit_this_occurrence(
    db: Session, jobs: JobScheduler, instance_id: str, *, patch: dict[str, Any], expected: dict[str, Any] | None = None
) -> TaskInstance:
    """§3.10 "this occurrence": touches only the live instance, sets `detached=True`. A
    duration change is checked against §6.8 the same way a template-level one is; a
    duration or deadline change on a non-terminal flexible instance re-enters §6.2. A
    longer duration on a fixed instance is held to §6.5's hard block, like a retime.

    `expected` is architecture-plan §5.1's expected-values PATCH: for each field the
    caller names, reject with `conflict` if the current row disagrees - fields the
    caller doesn't name (because it never read them, or isn't touching them) are never
    compared, so an unrelated background-job write can't bounce this edit.
    """
    instance = _require_instance(db, instance_id)
    template = _require_template(db, instance.template_id)
    settings = require_settings(db)

    unknown = set(patch) - set(_THIS_OCCURRENCE_FIELDS)
    if unknown:
        raise InstanceValidationError("invalid_field", f"Fields not editable via this-occurrence scope: {sorted(unknown)}")
    if "deadline" in patch and instance.type != "flexible":
        raise InstanceValidationError("invalid_field", "deadline can only be edited on a flexible instance.")

    if expected:
        unknown_expected = set(expected) - set(_THIS_OCCURRENCE_FIELDS)
        if unknown_expected:
            raise InstanceValidationError(
                "invalid_field", f"Fields not editable via this-occurrence scope: {sorted(unknown_expected)}"
            )
        conflicts = {field: getattr(instance, field) for field, value in expected.items() if getattr(instance, field) != value}
        if conflicts:
            raise InstanceValidationError(
                "conflict",
                f"Concurrently modified fields: {sorted(conflicts)}",
                details={"conflicting_fields": conflicts},
            )

    if "estimated_duration_minutes" in patch and instance.type == "flexible":
        effective_hours = build_active_hours_map(settings, template.active_hours_override)
        if not validate_feasible_duration(cast(int, patch["estimated_duration_minutes"]), effective_hours):
            raise InstanceValidationError(
                "infeasible_duration", "estimated_duration_minutes does not fit any day's effective active-hours window."
            )

    if "estimated_duration_minutes" in patch and fixed_slot_change_conflicts(
        db, instance, start=instance.scheduled_time or utcnow(), duration_minutes=cast(int, patch["estimated_duration_minutes"])
    ):
        raise InstanceValidationError(
            "creation_conflict", "The longer duration collides with an existing fixed task or external event."
        )

    now = utcnow()
    updated = TaskInstanceRepository(db).update(instance.model_copy(update={**patch, "detached": True}))

    if "estimated_duration_minutes" in patch:
        displace_flexible_under(db, jobs, updated, now=now)

    invalidates_placement = "estimated_duration_minutes" in patch or "deadline" in patch
    if updated.type == "flexible" and updated.status in ("pending", "scheduled") and invalidates_placement:
        if updated.status == "scheduled":
            updated = return_to_pending(db, jobs, updated, template=template, now=now)
        updated = place_or_defer(db, jobs, instance=updated, template=template, settings=settings, now=now)
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

    now = utcnow()
    updated = TaskInstanceRepository(db).update(
        instance.model_copy(update={"scheduled_time": new_scheduled_time, "detached": True})
    )
    template = _require_template(db, instance.template_id)
    schedule_reminder_and_overdue_jobs(jobs, updated, template.reminder_offsets_minutes)
    displace_flexible_under(db, jobs, updated, now=now)
    # §3.9: a manual reschedule that clears the collision resolves any sync_conflict this
    # instance was carrying, immediately rather than waiting for the next poll (Stage 7).
    resolve_cleared_sync_conflicts(db, now=now)
    return updated


def complete(db: Session, jobs: JobScheduler, instance_id: str) -> TaskInstance:
    """§3.3/§4: reachable directly from `pending`, `blocked`, or `scheduled` - not only
    via `in_progress`. Unblocks dependents (§6.9) and, for a `completion`-anchored
    template, generates the successor - both in the same transaction as the completion
    that triggered them (architecture-plan §4.1 Rev 3: "Completion is now two side
    effects, not one").
    """
    instance = _require_instance(db, instance_id)
    if instance.status in TERMINAL_STATUSES:
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
    resolve_notifications(db, instance_id=instance.id, types=(DEADLINE_MISSED,), now=now)
    _unblock_dependents(db, jobs, completed_instance_id=instance.id, now=now)

    template = _require_template(db, instance.template_id)
    if template.recurrence.anchor == "completion" and not template.archived:
        settings = require_settings(db)
        generate_and_place_next_instance(db, jobs, template=template, predecessor=updated, settings=settings, now=now)

    return updated


def start_progress(db: Session, instance_id: str) -> TaskInstance:
    """§4 state diagram: `scheduled` -> `in_progress`, user-triggered and optional. The
    only inbound edge in the diagram is from `scheduled`, so that's the only status this
    accepts from. No `jobs` param (unlike `dismiss`/`complete`) - the reminder and
    overdue-check handlers already treat `in_progress` identically to `scheduled`
    (`app/jobs/handlers.py`'s `status not in ("scheduled", "in_progress")` guards), so
    this transition has no job side effects to co-locate, matching
    `app.notifications.service.dismiss`'s precedent for a job-free mutation.
    """
    instance = _require_instance(db, instance_id)
    if instance.status != "scheduled":
        raise InstanceValidationError(
            "invalid_field", f"Cannot mark a {instance.status} instance in-progress - only a scheduled instance can be started."
        )
    now = utcnow()
    return TaskInstanceRepository(db).update(
        instance.model_copy(
            update={
                "status": "in_progress",
                "status_history": (*instance.status_history, StatusHistoryEntry(status="in_progress", at=now)),
            }
        )
    )


def dismiss(db: Session, jobs: JobScheduler, instance_id: str) -> TaskInstance:
    """§3.8 "skip this occurrence" - terminal (`dismissed`), preserving the row rather
    than destroying it (the routine way to clear a stale predecessor under calendar
    anchoring, §9.1). Reachable from any non-terminal status. Dependents are deliberately
    left `blocked` - `dismissed` does not satisfy a dependency (§4).
    """
    instance = _require_instance(db, instance_id)
    if instance.status in TERMINAL_STATUSES:
        raise InstanceValidationError("invalid_field", f"Cannot dismiss a {instance.status} instance - it is terminal.")
    now = utcnow()

    updated = TaskInstanceRepository(db).update(
        instance.model_copy(
            update={
                "status": "dismissed",
                "status_history": (*instance.status_history, StatusHistoryEntry(status="dismissed", at=now)),
            }
        )
    )
    jobs.cancel_all_for_instance(instance_id=instance.id)
    resolve_notifications(db, instance_id=instance.id, types=_DISMISS_RESOLVED_NOTIFICATION_TYPES, now=now)

    template = _require_template(db, instance.template_id)
    if template.recurrence.anchor == "completion" and not template.archived:
        # §3.8 "Re-anchoring on this_occurrence": dismissing isn't completing, so there is
        # no completed_at to anchor against - the successor's nominal date is
        # `now + cadence`. `predecessor=None` is exactly that: the same "advance the rule
        # from now" path `generate_next_instance` already uses for a template's very
        # first instance (see its module docstring's `_next_nominal_instant`).
        settings = require_settings(db)
        generate_and_place_next_instance(db, jobs, template=template, predecessor=None, settings=settings, now=now)

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
    settings = require_settings(db)

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
    resolve_notifications(db, instance_id=instance.id, types=(DEADLINE_MISSED,), now=now)
    return place_or_defer(db, jobs, instance=pending_instance, template=template, settings=settings, now=now)


def delete_instance(db: Session, jobs: JobScheduler, instance_id: str, *, scope: DeleteScope | None = None) -> DeleteResult:
    """§3.8: unlink, not cascade. Deleting an instance other instances depend on just
    removes the link; if that leaves a dependent with zero remaining dependencies, it
    unblocks and is placed immediately, in the same transaction (matching §6.9's
    co-location principle - design doc Example D's own expected outcome is "placed by
    6.2", not merely "eligible for a later pass").

    `scope` mirrors §3.10's edit-scope prompt (§3.8): required for a recurring template
    (the two scopes are equivalent for `one_time`, so the prompt - and this argument - is
    skipped there, matching design doc §3.8's own framing). `this_occurrence` deletes just
    this instance and the series continues (a successor is generated per §9.1 for a
    `completion`-anchored template - a `calendar`-anchored one already continues on its
    own via the independently-running occurrence-boundary job). `this_and_future` deletes
    this instance **and** archives the template, ending the series.
    """
    repo = TaskInstanceRepository(db)
    instance = _require_instance(db, instance_id)  # 404s cleanly if the id is unknown
    template = _require_template(db, instance.template_id)
    is_recurring = template.recurrence.pattern != "one_time"
    if is_recurring and scope is None:
        raise InstanceValidationError("scope_required", "scope is required when deleting an instance of a recurring template.")

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

    if scope == "this_and_future":
        archive_template_and_cancel_jobs(db, jobs, template.id)
    elif is_recurring and scope == "this_occurrence" and not template.archived and template.recurrence.anchor == "completion":
        # See dismiss()'s identical §3.8 "Re-anchoring on this_occurrence" comment -
        # deleting isn't completing, so the successor anchors at `now + cadence`.
        settings = require_settings(db)
        generate_and_place_next_instance(db, jobs, template=template, predecessor=None, settings=settings, now=now)

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
    if instance.status != "blocked" or not all_dependencies_completed(db, instance):
        return None
    repo = TaskInstanceRepository(db)
    template = _require_template(db, instance.template_id)
    settings = require_settings(db)
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


__all__ = [
    "DeleteResult",
    "DeleteScope",
    "InstanceValidationError",
    "complete",
    "delete_instance",
    "dismiss",
    "edit_this_occurrence",
    "extend_deadline",
    "list_instances",
    "promote_if_unblocked",
    "reschedule",
    "start_progress",
]
