"""TaskInstance action endpoints. See design doc §3.3, §3.8, §3.10; architecture-plan §3."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.errors import AppError
from app.db.schemas import TaskInstance, TaskInstanceStatus, TaskType
from app.db.session import get_db
from app.jobs.interface import JobScheduler, get_job_scheduler
from app.task_instances import service

router = APIRouter(prefix="/api/v1/task-instances", tags=["task-instances"])

_VALIDATION_ERROR_STATUS = {
    "invalid_field": 422,
    "infeasible_duration": 422,
    "creation_conflict": 409,
    "not_found": 404,
    "scope_required": 422,
}


class PatchInstanceRequest(BaseModel):
    """§3.10 "this occurrence" - genuinely partial, only fields present are applied."""

    name: str | None = None
    description: str | None = None
    location: str | None = None
    priority: int | None = None
    estimated_duration_minutes: int | None = None
    deadline: datetime | None = None


class RescheduleRequest(BaseModel):
    scheduled_time: datetime


class ExtendDeadlineRequest(BaseModel):
    deadline: datetime


class DeleteResponse(BaseModel):
    deleted_instance_id: str
    unblocked_instance_ids: tuple[str, ...]


@router.get("")
def list_instances_endpoint(
    status: TaskInstanceStatus | None = None,
    priority: int | None = None,
    type: TaskType | None = None,
    view: Literal["backlog"] | None = None,
    db: Session = Depends(get_db),
) -> list[TaskInstance]:
    """architecture-plan §3: `status`/`priority`/`type` filters, plus `?view=backlog`
    (design doc §8.1) - a filter on this same collection, not its own resource.
    """
    return list(service.list_instances(db, status=status, priority=priority, type=type, view=view))


@router.patch("/{instance_id}")
def patch_instance_endpoint(
    instance_id: str,
    payload: PatchInstanceRequest,
    db: Session = Depends(get_db),
    jobs: JobScheduler = Depends(get_job_scheduler),
) -> TaskInstance:
    patch: dict[str, Any] = {field: getattr(payload, field) for field in payload.model_fields_set}
    try:
        return service.edit_this_occurrence(db, jobs, instance_id, patch=patch)
    except service.InstanceValidationError as exc:
        raise AppError(_VALIDATION_ERROR_STATUS[exc.code], exc.code, str(exc)) from exc


@router.post("/{instance_id}/reschedule")
def reschedule_endpoint(
    instance_id: str,
    payload: RescheduleRequest,
    db: Session = Depends(get_db),
    jobs: JobScheduler = Depends(get_job_scheduler),
) -> TaskInstance:
    try:
        return service.reschedule(db, jobs, instance_id, new_scheduled_time=payload.scheduled_time)
    except service.InstanceValidationError as exc:
        raise AppError(_VALIDATION_ERROR_STATUS[exc.code], exc.code, str(exc)) from exc


@router.post("/{instance_id}/complete")
def complete_endpoint(
    instance_id: str, db: Session = Depends(get_db), jobs: JobScheduler = Depends(get_job_scheduler)
) -> TaskInstance:
    try:
        return service.complete(db, jobs, instance_id)
    except service.InstanceValidationError as exc:
        raise AppError(_VALIDATION_ERROR_STATUS[exc.code], exc.code, str(exc)) from exc


@router.post("/{instance_id}/extend-deadline")
def extend_deadline_endpoint(
    instance_id: str,
    payload: ExtendDeadlineRequest,
    db: Session = Depends(get_db),
    jobs: JobScheduler = Depends(get_job_scheduler),
) -> TaskInstance:
    try:
        return service.extend_deadline(db, jobs, instance_id, new_deadline=payload.deadline)
    except service.InstanceValidationError as exc:
        raise AppError(_VALIDATION_ERROR_STATUS[exc.code], exc.code, str(exc)) from exc


@router.post("/{instance_id}/start")
def start_endpoint(instance_id: str, db: Session = Depends(get_db)) -> TaskInstance:
    """§4 state diagram: `scheduled` -> `in_progress`. No `jobs` dependency - this
    transition has no job side effects (see `service.start_progress`'s docstring).
    """
    try:
        return service.start_progress(db, instance_id)
    except service.InstanceValidationError as exc:
        raise AppError(_VALIDATION_ERROR_STATUS[exc.code], exc.code, str(exc)) from exc


@router.post("/{instance_id}/dismiss")
def dismiss_endpoint(
    instance_id: str, db: Session = Depends(get_db), jobs: JobScheduler = Depends(get_job_scheduler)
) -> TaskInstance:
    try:
        return service.dismiss(db, jobs, instance_id)
    except service.InstanceValidationError as exc:
        raise AppError(_VALIDATION_ERROR_STATUS[exc.code], exc.code, str(exc)) from exc


@router.delete("/{instance_id}")
def delete_instance_endpoint(
    instance_id: str,
    scope: service.DeleteScope | None = None,
    db: Session = Depends(get_db),
    jobs: JobScheduler = Depends(get_job_scheduler),
) -> DeleteResponse:
    try:
        result = service.delete_instance(db, jobs, instance_id, scope=scope)
    except service.InstanceValidationError as exc:
        raise AppError(_VALIDATION_ERROR_STATUS[exc.code], exc.code, str(exc)) from exc
    return DeleteResponse(deleted_instance_id=result.deleted_instance_id, unblocked_instance_ids=result.unblocked_instance_ids)
