"""TaskTemplate endpoints. See design doc §3.2, §3.8, §3.10; architecture-plan §3."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.dependencies import DB_SESSION, get_request_job_scheduler
from app.api.errors import AppError
from app.db.base import utcnow
from app.db.schemas import (
    INT_TO_PRIORITY,
    ActiveHoursWindow,
    DayName,
    Priority,
    Recurrence,
    RecurrenceAnchor,
    TaskInstance,
    TaskTemplate,
    TaskType,
)
from app.jobs.interface import JobScheduler
from app.task_templates import service

router = APIRouter(prefix="/api/v1/task-templates", tags=["task-templates"])


class RecurrenceIn(BaseModel):
    pattern: Literal["one_time", "daily", "weekly", "monthly"]
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
    # Required (§3.2, Rev 10): a local "YYYY-MM-DD" in the user's timezone. Not accepted on
    # PATCH - the series' dates come from its occurrences once it exists.
    start_date: date
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
    deleted_instance_ids: tuple[str, ...]
    unblocked_instance_ids: tuple[str, ...]


class VirtualOccurrenceResponse(BaseModel):
    """§9.2 - a projected, non-persisted ghost occurrence. Deliberately a distinct shape
    from `TaskInstance` (no `id`, no status, no dependencies) so the frontend cannot
    mistake one for a real, interactive row.
    """

    template_id: str
    name: str
    type: TaskType
    priority: Priority
    estimated_duration_minutes: int
    occurs_at: datetime
    anchor: RecurrenceAnchor


@router.get("/projections")
def list_projections_endpoint(db: Session = DB_SESSION) -> list[VirtualOccurrenceResponse]:
    """`GET /task-templates/projections` (design doc §9.2) - Timeline "ghost" occurrences
    for every recurring template, out to the fixed 30-day horizon. Registered *before*
    `/{template_id}` below so `"projections"` is never captured as a `template_id` path
    parameter - FastAPI/Starlette matches routes in registration order.
    """
    occurrences = service.list_virtual_occurrences(db, now=utcnow())
    return [
        VirtualOccurrenceResponse(
            template_id=occ.template_id,
            name=occ.name,
            type=occ.type,
            priority=INT_TO_PRIORITY[occ.priority],
            estimated_duration_minutes=occ.estimated_duration_minutes,
            occurs_at=occ.occurs_at,
            anchor=occ.anchor,
        )
        for occ in occurrences
    ]


@router.get("/{template_id}")
def get_template_endpoint(template_id: str, db: Session = DB_SESSION) -> TaskTemplate:
    try:
        return service.get_template(db, template_id)
    except service.TemplateValidationError as exc:
        raise AppError.for_code(exc.code, str(exc), details=exc.details) from exc


@router.post("", status_code=201)
def create_template_endpoint(
    payload: CreateTemplateRequest,
    db: Session = DB_SESSION,
    jobs: JobScheduler = Depends(get_request_job_scheduler),
) -> CreateTemplateResponse:
    draft = service.TaskTemplateDraft(
        name=payload.name,
        type=payload.type,
        recurrence=Recurrence(**payload.recurrence.model_dump()),
        priority=payload.priority,
        estimated_duration_minutes=payload.estimated_duration_minutes,
        start_date=payload.start_date,
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
        raise AppError.for_code(exc.code, str(exc), details=exc.details) from exc
    return CreateTemplateResponse(template=result.template, instance=result.instance)


@router.patch("/{template_id}")
def patch_template_endpoint(
    template_id: str,
    payload: PatchTemplateRequest,
    scope: Literal["this_and_future"] = Query(...),
    from_instance: str | None = None,
    include_detached: bool = False,
    db: Session = DB_SESSION,
    jobs: JobScheduler = Depends(get_request_job_scheduler),
) -> TaskTemplate:
    """§3.10 "this and future": `from_instance` names the edited occurrence (required for
    a recurring task); `include_detached` is the edit dialog's "include these" checkbox."""
    # Deliberately not payload.model_dump() - see the identical note in
    # app.api.v1.routes.settings.patch_settings_endpoint: it would flatten nested models
    # to plain dicts, and model_copy(update=...) does not re-validate.
    patch: dict[str, object] = {field: getattr(payload, field) for field in payload.model_fields_set}
    if payload.recurrence is not None:
        patch["recurrence"] = Recurrence(**payload.recurrence.model_dump())
    try:
        return service.edit_template_this_and_future(
            db, jobs, template_id, patch=patch, from_instance_id=from_instance, include_detached=include_detached
        )
    except service.TemplateValidationError as exc:
        raise AppError.for_code(exc.code, str(exc), details=exc.details) from exc


@router.delete("/{template_id}")
def archive_template_endpoint(
    template_id: str, db: Session = DB_SESSION, jobs: JobScheduler = Depends(get_request_job_scheduler)
) -> ArchiveResponse:
    """§3.8 (Rev 11): ends the series - archives the template and deletes every open
    occurrence. Returns what was deleted and which dependents that unblocked."""
    try:
        result = service.archive_template(db, jobs, template_id)
    except service.TemplateValidationError as exc:
        raise AppError.for_code(exc.code, str(exc), details=exc.details) from exc
    return ArchiveResponse(
        template=result.template,
        deleted_instance_ids=result.deleted_instance_ids,
        unblocked_instance_ids=result.unblocked_instance_ids,
    )
