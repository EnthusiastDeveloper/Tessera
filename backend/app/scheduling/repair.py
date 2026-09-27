"""Schedule repair (design doc §6.10, Rev 11; architecture-plan §4, §5.2).

When the scheduling rules get stricter, some `scheduled` flexible placements stop being
valid. This module finds them (via the pure `app.scheduling_engine.repair` check, fed the
same obstacle set §6.2 places against) and repairs them one at a time - back to `pending`,
then placed again by §6.2 or flagged `unschedulable`. Valid placements are never moved.

Shared by the settings save (`app.settings`), a template's own override edit
(`app.task_templates`) and the background job (`app.jobs`), hence its home here.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping
from datetime import datetime, timedelta
from typing import cast
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.db.base import generate_id
from app.db.repositories import ScheduleRepairRepository, TaskInstanceRepository, TaskTemplateRepository
from app.db.schemas import ScheduleRepair, TaskInstance, UserSettings
from app.jobs.interface import JobScheduler, schedule_repair_job_key
from app.scheduling.adapter import build_blackout_dates, gather_obstacles, to_engine_active_hours
from app.scheduling.orchestration import place_or_defer, return_to_pending
from app.scheduling_engine.repair import PlacedFlexibleTask, placements_that_no_longer_fit
from app.scheduling_engine.types import Obstacle


def find_invalid_placements(db: Session, settings: UserSettings, *, only: Collection[str] | None = None) -> list[TaskInstance]:
    """Every `scheduled` flexible instance whose slot no longer fits the current rules, in
    the order to repair them. `only` limits the answer to those instance ids (a template
    edit repairs just the occurrences it reached) - the budget arithmetic still sees every
    placement, since they share the days."""
    tz = ZoneInfo(settings.timezone)
    repo = TaskInstanceRepository(db)
    templates = TaskTemplateRepository(db)
    scheduled = [i for i in repo.list_by_statuses(("scheduled",)) if i.type == "flexible" and i.scheduled_time and i.deadline]
    placed: list[PlacedFlexibleTask] = []
    for instance in scheduled:
        assert instance.scheduled_time is not None and instance.deadline is not None
        template = templates.get(instance.template_id)
        start = instance.scheduled_time.astimezone(tz)
        placed.append(
            PlacedFlexibleTask(
                id=instance.id,
                start=start,
                end=start + timedelta(minutes=instance.estimated_duration_minutes),
                deadline=instance.deadline.astimezone(tz),
                priority=instance.priority,
                active_hours_override=to_engine_active_hours(template.active_hours_override) if template else None,
            )
        )
    other_obstacles = tuple(
        Obstacle(start=o.start.astimezone(tz), end=o.end.astimezone(tz))
        for o in gather_obstacles(db, include_scheduled_flexible=False)
    )
    global_hours = to_engine_active_hours(settings.active_hours)
    assert global_hours is not None
    invalid_ids = placements_that_no_longer_fit(
        placed,
        active_hours=global_hours,
        blackout_dates=build_blackout_dates(settings),
        daily_time_budget_minutes=cast("Mapping[str, int | None]", settings.daily_time_budget_minutes),
        budget_enforcement=settings.budget_enforcement,
        other_obstacles=other_obstacles,
    )
    by_id = {i.id: i for i in scheduled}
    return [by_id[i] for i in invalid_ids if only is None or i in only]


def repair_placement(
    db: Session, jobs: JobScheduler, instance: TaskInstance, *, settings: UserSettings, now: datetime
) -> TaskInstance:
    """Returns one invalid placement to `pending` and places it again under the current
    rules (§6.2), or leaves it `pending` and `unschedulable`. Jobs re-wired either way."""
    template = TaskTemplateRepository(db).get(instance.template_id)
    if template is None:
        raise LookupError(f"TaskTemplate {instance.template_id} not found")
    pending = return_to_pending(db, jobs, instance, template=template, now=now)
    return place_or_defer(db, jobs, instance=pending, template=template, settings=settings, now=now)


def start_repair_if_needed(db: Session, jobs: JobScheduler, settings: UserSettings, *, now: datetime) -> ScheduleRepair | None:
    """§6.10: after a settings change, if any placement no longer fits, records a repair and
    schedules its job to run now - in the caller's transaction, so neither exists unless
    the settings change commits. Returns the repair, or `None` if nothing needs fixing."""
    invalid = find_invalid_placements(db, settings)
    if not invalid:
        return None
    repair = ScheduleRepairRepository(db).create(ScheduleRepair(id=generate_id(), total=len(invalid), requested_at=now))
    jobs.schedule_at(job_key=schedule_repair_job_key(repair.id), run_at=now)
    return repair


__all__ = ["find_invalid_placements", "repair_placement", "start_repair_if_needed"]
