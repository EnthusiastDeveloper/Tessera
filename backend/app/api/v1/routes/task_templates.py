"""TaskTemplate endpoints. See design doc §3.2, §3.8, §3.10; architecture-plan §3."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.errors import AppError
from app.db.schemas import ActiveHoursWindow, DayName, Priority, Recurrence, TaskInstance, TaskTemplate, TaskType
from app.db.session import get_db
from app.jobs.interface import JobScheduler, get_job_scheduler
from app.task_templates import service

router = APIRouter(prefix="/api/v1/task-templates", tags=["task-templates"])

_VALIDATION_ERROR_STATUS = {
    "invalid_recurrence_anchor": 422,
    "infeasible_duration": 422,
    "creation_conflict": 409,
    "cycle_detected": 409,
    "not_found": 404,
}


class RecurrenceIn(BaseModel):
    pattern: Literal["one_time", "daily", "weekly", "monthly", "custom"]
    interval: int | None = None
    day_of_week: int | None = None
    day_of_month: int | None = None
    anchor: Literal["calendar", "completion"]


class CreateTemplateRequest(BaseModel):
    name: str
    type: TaskType
    recurrence: RecurrenceIn
    priority: Priority
    estimated_duration_minutes: int
    description: str | None = None
    location: str | None = None
    fixed_time_of_day: str | None = None
    deadline_offset_minutes: int | None = None
    reminder_offsets_minutes: tuple[int, ...] = ()
    active_hours_override: dict[DayName, ActiveHoursWindow | None] | None = None
    dependencies: tuple[str, ...] = ()


class CreateTemplateResponse(BaseModel):
    template: TaskTemplate
    instance: TaskInstance


class PatchTemplateRequest(BaseModel):
    """Genuinely partial - only fields actually present in the request are applied
    (read via `model_fields_set`, see `patch_template_endpoint`).
    """

    name: str | None = None
    description: str | None = None
    location: str | None = None
    fixed_time_of_day: str | None = None
    deadline_offset_minutes: int | None = None
    priority: Priority | None = None
    estimated_duration_minutes: int | None = None
    reminder_offsets_minutes: tuple[int, ...] | None = None
    active_hours_override: dict[DayName, ActiveHoursWindow | None] | None = None
    recurrence: RecurrenceIn | None = None


class ArchiveResponse(BaseModel):
    template: TaskTemplate
    incomplete_instance_ids: tuple[str, ...]


@router.post("", status_code=201)
def create_template_endpoint(
    payload: CreateTemplateRequest,
    db: Session = Depends(get_db),
    jobs: JobScheduler = Depends(get_job_scheduler),
) -> CreateTemplateResponse:
    draft = service.TaskTemplateDraft(
        name=payload.name,
        type=payload.type,
        recurrence=Recurrence(**payload.recurrence.model_dump()),
        priority=payload.priority,
        estimated_duration_minutes=payload.estimated_duration_minutes,
        description=payload.description,
        location=payload.location,
        fixed_time_of_day=payload.fixed_time_of_day,
        deadline_offset_minutes=payload.deadline_offset_minutes,
        reminder_offsets_minutes=payload.reminder_offsets_minutes,
        active_hours_override=payload.active_hours_override,
        dependencies=payload.dependencies,
    )
    try:
        result = service.create_template(db, jobs, draft)
    except service.TemplateValidationError as exc:
        raise AppError(_VALIDATION_ERROR_STATUS[exc.code], exc.code, str(exc)) from exc
    return CreateTemplateResponse(template=result.template, instance=result.instance)


@router.patch("/{template_id}")
def patch_template_endpoint(
    template_id: str,
    payload: PatchTemplateRequest,
    scope: Literal["this_and_future"] = Query(...),
    db: Session = Depends(get_db),
    jobs: JobScheduler = Depends(get_job_scheduler),
) -> TaskTemplate:
    # Deliberately not payload.model_dump() - see the identical note in
    # app.api.v1.routes.settings.patch_settings_endpoint: it would flatten nested models
    # to plain dicts, and model_copy(update=...) does not re-validate.
    patch: dict[str, object] = {field: getattr(payload, field) for field in payload.model_fields_set}
    if payload.recurrence is not None:
        patch["recurrence"] = Recurrence(**payload.recurrence.model_dump())
    try:
        return service.edit_template_this_and_future(db, jobs, template_id, patch=patch)
    except service.TemplateValidationError as exc:
        raise AppError(_VALIDATION_ERROR_STATUS[exc.code], exc.code, str(exc)) from exc


@router.delete("/{template_id}")
def archive_template_endpoint(template_id: str, db: Session = Depends(get_db)) -> ArchiveResponse:
    """§3.8: soft-delete. Returns the incomplete instances left behind so the frontend's
    confirmation dialog (§3.8's "must show a confirmation dialog explaining the
    implications") can list them.
    """
    try:
        result = service.archive_template(db, template_id)
    except service.TemplateValidationError as exc:
        raise AppError(_VALIDATION_ERROR_STATUS[exc.code], exc.code, str(exc)) from exc
    return ArchiveResponse(template=result.template, incomplete_instance_ids=result.incomplete_instance_ids)
