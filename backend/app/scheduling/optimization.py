"""Schedule optimization - the "Optimize Schedule" action (design doc §6.11, Rev 14;
architecture-plan §4.1, §5.4).

A global re-placement of every `scheduled`/`pending` flexible task, run in the background
under a lock that pauses schedule edits. The pure plan lives in
`app.scheduling_engine.optimization`; this module selects what goes into it, applies it
through the same placement-change path as every other re-placement (so jobs and
notifications follow), keeps the `ScheduleOptimization` row, and undoes an applied run
while that is still safe. A plan that would take a scheduled task away is held for the
user's approval and recomputed when they give it.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.base import generate_id, utcnow
from app.db.repositories import (
    NotificationRepository,
    ScheduleOptimizationRepository,
    ScheduleRepairRepository,
    TaskInstanceRepository,
    TaskTemplateRepository,
)
from app.db.schemas import ScheduleOptimization, TaskInstance, TaskTemplate, UserSettings
from app.jobs.interface import JobScheduler, deadline_elapsed_job_key, schedule_optimization_job_key
from app.scheduling.adapter import (
    build_blackout_dates,
    build_candidate,
    gather_obstacles,
    to_engine_active_hours,
)
from app.scheduling.orchestration import (
    BUDGET_EXCEEDED,
    UNSCHEDULABLE,
    create_notification,
    has_active_notification,
    place_instance_at,
    require_settings,
    return_to_pending,
    schedule_reminder_and_overdue_jobs,
)
from app.scheduling_engine.deadlines import is_deadline_elapsed
from app.scheduling_engine.fixed_conflicts import intervals_overlap
from app.scheduling_engine.grid import add_elapsed
from app.scheduling_engine.optimization import (
    CurrentSlot,
    OptimizationPlan,
    plan_optimization,
)
from app.scheduling_engine.types import Obstacle

#: A plan waiting for approval, and an applied operation's Undo, each last this long (§6.11).
PLAN_VALID_FOR = timedelta(minutes=10)
UNDO_WINDOW = timedelta(minutes=10)


class OptimizationError(Exception):
    """`code` maps to the API error envelope (architecture-plan §3)."""

    def __init__(self, code: str, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.details = details


@dataclass(frozen=True)
class Limits:
    """How long an optimization may run: when the UI says it is slow, and when it is failed."""

    slow_after: timedelta
    timeout: timedelta


def limits() -> Limits:
    settings = get_settings()
    return Limits(
        slow_after=timedelta(seconds=settings.optimization_slow_after_seconds),
        timeout=timedelta(seconds=settings.optimization_timeout_seconds),
    )


# --- State -----------------------------------------------------------------------------------


def latest(db: Session, *, now: datetime | None = None) -> ScheduleOptimization | None:
    """The most recent operation, after letting time pass: a run past its limit is failed and a
    held plan past its life is expired."""
    now = now or utcnow()
    _expire_stale(db, now)
    return ScheduleOptimizationRepository(db).latest()


def is_locked(db: Session, *, now: datetime | None = None) -> bool:
    """Whether schedule edits are paused: an optimization is running (§6.11). Not while a plan
    merely waits for approval - the user thinking must not lock the schedule."""
    now = now or utcnow()
    _expire_stale(db, now)
    return bool(ScheduleOptimizationRepository(db).list_with_status("running"))


def _expire_stale(db: Session, now: datetime) -> None:
    repo = ScheduleOptimizationRepository(db)
    timeout = limits().timeout
    for row in repo.list_with_status("running"):
        if now - row.requested_at > timeout:
            repo.update(
                row.model_copy(
                    update={
                        "status": "failed",
                        "finished_at": now,
                        "reason": "It took too long to finish. Nothing was changed.",
                    }
                )
            )
    for row in repo.list_with_status("awaiting_approval"):
        if row.valid_until is not None and now > row.valid_until:
            repo.update(row.model_copy(update={"status": "expired", "finished_at": now}))


def fail_interrupted(db: Session, *, now: datetime) -> None:
    """Startup (architecture-plan §4.2): a `running` row can only mean the process died with it
    in flight. Applying and recording happen in one transaction, so nothing was changed."""
    repo = ScheduleOptimizationRepository(db)
    for row in repo.list_with_status("running"):
        repo.update(
            row.model_copy(
                update={
                    "status": "failed",
                    "finished_at": now,
                    "reason": "It was interrupted by a restart. Nothing was changed.",
                }
            )
        )


# --- Requesting, approving, declining --------------------------------------------------------


def request_optimization(db: Session, jobs: JobScheduler, *, now: datetime) -> ScheduleOptimization:
    """Records an optimization and schedules its job to run now - in the caller's transaction."""
    repo = ScheduleOptimizationRepository(db)
    _expire_stale(db, now)
    if repo.list_with_status("running"):
        raise OptimizationError("optimization_in_progress", "The schedule is already being optimized.")
    repair = ScheduleRepairRepository(db).latest()
    if repair is not None and repair.finished_at is None:
        raise OptimizationError("repair_in_progress", "The calendar is being fixed after a settings change. Try again shortly.")
    for held in repo.list_with_status("awaiting_approval"):
        repo.update(held.model_copy(update={"status": "declined", "finished_at": now}))
    row = repo.create(ScheduleOptimization(id=generate_id(), status="running", requested_at=now))
    jobs.schedule_at(job_key=schedule_optimization_job_key(row.id), run_at=now)
    return row


def approve(db: Session, jobs: JobScheduler, optimization_id: str, *, now: datetime) -> ScheduleOptimization:
    """The user accepts the held plan. The job recomputes it first and applies it only if it is
    still what they were shown."""
    repo = ScheduleOptimizationRepository(db)
    _expire_stale(db, now)
    row = _get(repo, optimization_id)
    if row.status == "expired":
        raise OptimizationError("optimization_expired", "That plan is out of date. Optimize the schedule again.")
    if row.status != "awaiting_approval":
        raise OptimizationError("invalid_optimization_state", f"This optimization is {row.status}, not waiting for approval.")
    if repo.list_with_status("running"):
        raise OptimizationError("optimization_in_progress", "The schedule is already being optimized.")
    row = repo.update(row.model_copy(update={"status": "running", "approved": True, "requested_at": now}))
    jobs.schedule_at(job_key=schedule_optimization_job_key(row.id), run_at=now)
    return row


def decline(db: Session, optimization_id: str, *, now: datetime) -> ScheduleOptimization:
    repo = ScheduleOptimizationRepository(db)
    _expire_stale(db, now)
    row = _get(repo, optimization_id)
    if row.status != "awaiting_approval":
        raise OptimizationError("invalid_optimization_state", f"This optimization is {row.status}, not waiting for approval.")
    return repo.update(row.model_copy(update={"status": "declined", "finished_at": now}))


def _get(repo: ScheduleOptimizationRepository, optimization_id: str) -> ScheduleOptimization:
    row = repo.get(optimization_id)
    if row is None:
        raise OptimizationError("not_found", f"ScheduleOptimization {optimization_id} not found")
    return row


# --- The job ---------------------------------------------------------------------------------


def run(db: Session, jobs: JobScheduler, optimization_id: str, *, now: datetime | None = None) -> None:
    """The background job (architecture-plan §4): compute the plan, then - depending on what
    it says and whether the user already approved it - apply it, hold it for approval, or
    record that there is nothing to do. Everything it writes commits together."""
    now = now or utcnow()
    repo = ScheduleOptimizationRepository(db)
    row = repo.get(optimization_id)
    if row is None or row.status != "running":
        return
    settings = require_settings(db)
    plan = build_plan(db, settings, now=now)
    result, reason = plan.classify()
    plan_json = plan_to_json(plan)

    if row.approved and _comparable(row.plan or {}) == _comparable(plan_json):
        _apply_and_record(db, jobs, repo, row, plan, plan_json, settings, now=now)
        return

    # A fresh decision by the ordinary rules. If the user had approved a plan and this is not it
    # (an event synced, a task changed, time passed), they approved something that is no longer
    # what would happen: it is judged anew - held again if it still needs approval - and flagged.
    row = row.model_copy(update={"approved": False, "plan_changed": row.plan_changed or row.approved})
    if result == "nothing_to_do":
        repo.update(row.model_copy(update={"status": "nothing_to_do", "finished_at": now, "reason": reason, "plan": plan_json}))
    elif result == "needs_approval":
        repo.update(
            row.model_copy(update={"status": "awaiting_approval", "plan": plan_json, "valid_until": now + PLAN_VALID_FOR})
        )
    else:
        _apply_and_record(db, jobs, repo, row, plan, plan_json, settings, now=now)


def mark_failed(db: Session, optimization_id: str, *, reason: str, now: datetime | None = None) -> None:
    repo = ScheduleOptimizationRepository(db)
    row = repo.get(optimization_id)
    if row is not None and row.status == "running":
        repo.update(row.model_copy(update={"status": "failed", "finished_at": now or utcnow(), "reason": reason}))


def build_plan(db: Session, settings: UserSettings, *, now: datetime, take_write_lock: bool = True) -> OptimizationPlan:
    """§6.11: every `scheduled` and `pending` flexible instance is a candidate, with its own slot
    taken out of the obstacle set; fixed instances (a blocked one holds its slot), `in_progress`
    work and external events stay where they are. By default takes the write lock (via
    `gather_obstacles`), so what was read is what is applied; `take_write_lock=False` is for
    `opportunity`, which only reads."""
    tz = ZoneInfo(settings.timezone)
    instances = TaskInstanceRepository(db)
    templates = TaskTemplateRepository(db)
    candidates = []
    current: dict[str, CurrentSlot] = {}
    obstacles = tuple(
        Obstacle(start=o.start.astimezone(tz), end=o.end.astimezone(tz))
        for o in gather_obstacles(db, include_scheduled_flexible=False, take_write_lock=take_write_lock)
    )
    for instance in instances.list_by_statuses(("scheduled", "pending")):
        if instance.type != "flexible" or instance.deadline is None or is_deadline_elapsed(instance.deadline, now):
            continue
        template = templates.get(instance.template_id)
        if template is None:
            continue
        candidates.append(build_candidate(db, instance, template, tz=tz))
        if instance.status == "scheduled" and instance.scheduled_time is not None:
            current[instance.id] = CurrentSlot(instance.scheduled_time.astimezone(tz), instance.estimated_duration_minutes)
    global_hours = to_engine_active_hours(settings.active_hours)
    assert global_hours is not None
    return plan_optimization(
        candidates,
        current,
        now=now.astimezone(tz),
        active_hours=global_hours,
        blackout_dates=build_blackout_dates(settings),
        daily_time_budget_minutes=cast("Mapping[str, int | None]", settings.daily_time_budget_minutes),
        budget_enforcement=settings.budget_enforcement,
        obstacles=obstacles,
    )


def _apply_and_record(
    db: Session,
    jobs: JobScheduler,
    repo: ScheduleOptimizationRepository,
    row: ScheduleOptimization,
    plan: OptimizationPlan,
    plan_json: dict[str, Any],
    settings: UserSettings,
    *,
    now: datetime,
) -> None:
    # A run that overstayed its limit has already been declared failed and the lock released;
    # it must not then change the schedule.
    fresh = repo.get(row.id)
    if fresh is None or fresh.status != "running" or now - fresh.requested_at > limits().timeout:
        return
    versions, notifications = _apply(db, jobs, plan, now=now)
    plan_json = {**plan_json, "notifications_created": notifications}
    repo.update(
        row.model_copy(
            update={
                "status": "applied",
                "approved": False,
                "finished_at": now,
                "undo_until": now + UNDO_WINDOW,
                "plan": plan_json,
                "applied_versions": versions,
            }
        )
    )


def _apply(db: Session, jobs: JobScheduler, plan: OptimizationPlan, *, now: datetime) -> tuple[dict[str, int], list[str]]:
    """Writes the plan through the placement-change path every re-placement uses (§6.4, 6.5,
    6.10): statuses and slots, then jobs, then notifications. Returns each changed instance's
    resulting `version` and the notifications raised, for Undo."""
    instances = TaskInstanceRepository(db)
    templates = TaskTemplateRepository(db)
    changed: list[str] = []
    created: list[str] = []

    def load(task_id: str) -> tuple[TaskInstance, TaskTemplate]:
        instance = instances.get(task_id)
        template = templates.get(instance.template_id) if instance is not None else None
        if instance is None or template is None:
            raise LookupError(f"TaskInstance {task_id} or its template disappeared during the optimization")
        return instance, template

    for loss in plan.lost:
        instance, template = load(loss.task_id)
        pending = return_to_pending(db, jobs, instance, template=template, now=now)
        if not has_active_notification(db, instance_id=pending.id, notification_type=UNSCHEDULABLE):
            created.append(
                create_notification(
                    db,
                    type_=UNSCHEDULABLE,
                    instance_id=pending.id,
                    message=f'"{template.name}" has no available slot before its deadline.',
                    now=now,
                ).id
            )
        if pending.deadline is not None:
            jobs.schedule_at(job_key=deadline_elapsed_job_key(pending.id), run_at=pending.deadline)
        changed.append(pending.id)

    for move in plan.moved:
        instance, template = load(move.task_id)
        updated = instances.update(instance.model_copy(update={"scheduled_time": move.to_start}))
        schedule_reminder_and_overdue_jobs(jobs, updated, template.reminder_offsets_minutes)
        changed.append(updated.id)

    for new in plan.newly_scheduled:
        instance, template = load(new.task_id)
        updated = place_instance_at(db, jobs, instance=instance, template=template, start=new.to_start, now=now)
        changed.append(updated.id)

    for task_id in plan.over_budget_ids:
        instance, template = load(task_id)
        if not has_active_notification(db, instance_id=task_id, notification_type=BUDGET_EXCEEDED):
            created.append(
                create_notification(
                    db,
                    type_=BUDGET_EXCEEDED,
                    instance_id=task_id,
                    message=f'"{template.name}" now sits on a day over its daily time budget.',
                    now=now,
                ).id
            )

    versions = {task_id: _version(instances, task_id) for task_id in changed}
    return versions, created


def _version(instances: TaskInstanceRepository, task_id: str) -> int:
    instance = instances.get(task_id)
    assert instance is not None
    return instance.version


# --- Is it worth it? ---


@dataclass(frozen=True)
class Opportunity:
    """What pressing "Optimize Schedule" would achieve right now (design doc §6.11, "the button
    says whether it is worth pressing"). `gain` is the net number of *more* tasks that would be
    scheduled than are today (never negative); that is the value. Moves alone are churn, and a
    swap - one task gains a slot while another loses its own - places no more tasks than today,
    so neither is advertised."""

    gain: int
    newly_scheduled: int
    lost: int
    over_budget: int
    moved: int
    needs_approval: bool
    worthwhile: bool


def opportunity(db: Session, *, now: datetime | None = None) -> Opportunity:
    """Runs the plan - the very computation a real run starts with, so the two cannot disagree
    about the rules - **without taking the write lock and without writing anything**."""
    now = now or utcnow()
    plan = build_plan(db, require_settings(db), now=now, take_write_lock=False)
    result, _ = plan.classify()
    gain = max(0, plan.placed_after - plan.placed_before)
    return Opportunity(
        gain=gain,
        newly_scheduled=len(plan.newly_scheduled),
        lost=len(plan.lost),
        over_budget=len(plan.over_budget_ids),
        moved=len(plan.moved),
        needs_approval=result == "needs_approval",
        worthwhile=gain > 0 and result in ("applied", "needs_approval"),
    )


# --- Undo ------------------------------------------------------------------------------------


def undo_blockers(db: Session, row: ScheduleOptimization, *, now: datetime) -> list[dict[str, str]]:
    """Why Undo is not safe right now, one entry per reason - empty when it is (§6.11): the
    window is open, every changed instance still has the version the operation left it with,
    and every slot about to be restored is clear of anything but the operation's own tasks."""
    if row.status != "applied":
        return [{"reason": "not_applied"}]
    if row.undo_until is None or now > row.undo_until:
        return [{"reason": "window_elapsed"}]
    plan = row.plan or {}
    versions = row.applied_versions or {}
    instances = TaskInstanceRepository(db)
    reasons: list[dict[str, str]] = []
    for task_id, version in versions.items():
        instance = instances.get(task_id)
        if instance is None:
            reasons.append({"reason": "instance_gone", "instance_id": task_id})
        elif instance.version != version:
            reasons.append({"reason": "instance_changed", "instance_id": task_id, "name": instance.name})
    if reasons:
        return reasons
    obstacles = gather_obstacles(db, exclude_instance_ids=set(versions))
    for entry in (*plan.get("moved", []), *plan.get("lost", [])):
        instance = instances.get(entry["id"])
        assert instance is not None
        start = _parse(entry["from"])
        end = add_elapsed(start, timedelta(minutes=instance.estimated_duration_minutes))
        if any(intervals_overlap(start, end, o.start, o.end) for o in obstacles):
            reasons.append({"reason": "slot_taken", "instance_id": entry["id"], "name": instance.name})
    return reasons


def undo(db: Session, jobs: JobScheduler, optimization_id: str, *, now: datetime) -> ScheduleOptimization:
    """Puts every changed instance back as it was, in one transaction, through the same job
    re-wiring and notification reconciliation as applying. One level: only the latest."""
    repo = ScheduleOptimizationRepository(db)
    _expire_stale(db, now)
    row = _get(repo, optimization_id)
    latest_row = repo.latest()
    if latest_row is None or latest_row.id != row.id:
        raise OptimizationError(
            "undo_unavailable", "A newer optimization has replaced this one.", details={"reasons": [{"reason": "superseded"}]}
        )
    if row.status == "applied" and row.undo_until is not None and now > row.undo_until:
        raise OptimizationError("optimization_expired", "The time to undo this has passed.")
    blockers = undo_blockers(db, row, now=now)
    if blockers:
        raise OptimizationError("undo_unavailable", "This can no longer be undone.", details={"reasons": blockers})

    instances = TaskInstanceRepository(db)
    templates = TaskTemplateRepository(db)
    plan = row.plan or {}

    def load(task_id: str) -> tuple[TaskInstance, TaskTemplate]:
        instance = instances.get(task_id)
        assert instance is not None
        template = templates.get(instance.template_id)
        assert template is not None
        return instance, template

    for entry in plan.get("moved", []):
        instance, template = load(entry["id"])
        updated = instances.update(instance.model_copy(update={"scheduled_time": _parse(entry["from"])}))
        schedule_reminder_and_overdue_jobs(jobs, updated, template.reminder_offsets_minutes)
    for entry in plan.get("lost", []):
        instance, template = load(entry["id"])
        place_instance_at(db, jobs, instance=instance, template=template, start=_parse(entry["from"]), now=now)
    for entry in plan.get("newly_scheduled", []):
        instance, template = load(entry["id"])
        pending = return_to_pending(db, jobs, instance, template=template, now=now)
        if not has_active_notification(db, instance_id=pending.id, notification_type=UNSCHEDULABLE):
            create_notification(
                db,
                type_=UNSCHEDULABLE,
                instance_id=pending.id,
                message=f'"{template.name}" has no available slot before its deadline.',
                now=now,
            )
        if pending.deadline is not None:
            jobs.schedule_at(job_key=deadline_elapsed_job_key(pending.id), run_at=pending.deadline)
    notifications = NotificationRepository(db)
    for notification_id in plan.get("notifications_created", []):
        notification = notifications.get(notification_id)
        if notification is not None and notification.resolved_at is None:
            notifications.update(notification.model_copy(update={"resolved_at": now}))
    return repo.update(row.model_copy(update={"status": "undone", "finished_at": now, "undo_until": None}))


# --- Plan <-> JSON, summary ------------------------------------------------------------------


def plan_to_json(plan: OptimizationPlan) -> dict[str, Any]:
    return {
        "moved": [
            {"id": m.task_id, "from": _iso(m.from_start), "to": _iso(m.to_start), "over_budget": m.newly_over_budget}
            for m in plan.moved
        ],
        "newly_scheduled": [
            {"id": p.task_id, "to": _iso(p.to_start), "over_budget": p.newly_over_budget} for p in plan.newly_scheduled
        ],
        "lost": [{"id": x.task_id, "from": _iso(x.from_start)} for x in plan.lost],
        "over_budget_unchanged": list(plan.newly_over_budget_unchanged),
        "unchanged": len(plan.unchanged),
        "still_unplaced": len(plan.still_unplaced),
        "placed_before": plan.placed_before,
        "placed_after": plan.placed_after,
    }


def _comparable(plan_json: Mapping[str, Any]) -> tuple[object, ...]:
    """The parts of a stored plan that approval is for (mirrors `OptimizationPlan.signature`)."""
    return (
        tuple(sorted((m["id"], m["from"], m["to"], m["over_budget"]) for m in plan_json.get("moved", []))),
        tuple(sorted((p["id"], p["to"], p["over_budget"]) for p in plan_json.get("newly_scheduled", []))),
        tuple(sorted((x["id"], x["from"]) for x in plan_json.get("lost", []))),
        tuple(sorted(plan_json.get("over_budget_unchanged", []))),
    )


def build_summary(db: Session, row: ScheduleOptimization) -> dict[str, Any] | None:
    """What changed (or would), with the instances' names, for the user (§6.11 "the summary")."""
    plan = row.plan
    if plan is None:
        return None
    instances = TaskInstanceRepository(db)

    def info(task_id: str) -> tuple[str, str | None]:
        instance = instances.get(task_id)
        if instance is None:
            return "(deleted task)", None
        return instance.name, _iso(instance.deadline) if instance.deadline else None

    moved = [{"instance_id": m["id"], "name": info(m["id"])[0], "from": m["from"], "to": m["to"]} for m in plan["moved"]]
    newly = [{"instance_id": p["id"], "name": info(p["id"])[0], "to": p["to"]} for p in plan["newly_scheduled"]]
    lost = [
        {
            "instance_id": x["id"],
            "name": info(x["id"])[0],
            "from": x["from"],
            "deadline": info(x["id"])[1],
            "reason": "no_slot_before_deadline",
        }
        for x in plan["lost"]
    ]
    over_ids = [
        *(m["id"] for m in plan["moved"] if m["over_budget"]),
        *(p["id"] for p in plan["newly_scheduled"] if p["over_budget"]),
        *plan["over_budget_unchanged"],
    ]
    over = [{"instance_id": task_id, "name": info(task_id)[0]} for task_id in over_ids]
    return {
        "counts": {
            "newly_scheduled": len(newly),
            "moved": len(moved),
            "lost": len(lost),
            "over_budget": len(over),
            "unchanged": plan["unchanged"],
            "still_unplaced": plan["still_unplaced"],
        },
        "newly_scheduled": newly,
        "moved": moved,
        "lost": lost,
        "over_budget": over,
    }


def _iso(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat()


def _parse(value: str) -> datetime:
    return datetime.fromisoformat(value)


__all__ = [
    "PLAN_VALID_FOR",
    "UNDO_WINDOW",
    "Limits",
    "Opportunity",
    "OptimizationError",
    "approve",
    "build_plan",
    "build_summary",
    "decline",
    "fail_interrupted",
    "is_locked",
    "latest",
    "limits",
    "mark_failed",
    "opportunity",
    "plan_to_json",
    "request_optimization",
    "run",
    "undo",
    "undo_blockers",
]
