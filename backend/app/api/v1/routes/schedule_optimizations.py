"""Schedule optimization endpoints. See design doc §6.11 (Rev 14); architecture-plan §3, §5.4."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.dependencies import DB_SESSION, get_request_job_scheduler
from app.api.errors import AppError
from app.db.base import utcnow
from app.db.schemas import OptimizationStatus, ScheduleOptimization
from app.jobs.interface import JobScheduler
from app.scheduling import optimization

router = APIRouter(prefix="/api/v1/schedule-optimizations", tags=["schedule-optimizations"])


class OptimizationResponse(BaseModel):
    """One optimization as the client needs it: where it is, what it did or would do, and
    whether Undo is on offer *right now* (computed on every read, never stored)."""

    id: str
    status: OptimizationStatus
    requested_at: datetime
    finished_at: datetime | None
    valid_until: datetime | None
    undo_until: datetime | None
    reason: str | None
    plan_changed: bool
    undo_available: bool
    #: The limits in force (configurable, `OPTIMIZATION_*` env vars) so the UI never hardcodes them.
    slow_after_seconds: int
    timeout_seconds: int
    summary: dict[str, Any] | None


def _respond(db: Session, row: ScheduleOptimization) -> OptimizationResponse:
    now = utcnow()
    limit = optimization.limits()
    return OptimizationResponse(
        id=row.id,
        status=row.status,
        requested_at=row.requested_at,
        finished_at=row.finished_at,
        valid_until=row.valid_until,
        undo_until=row.undo_until,
        reason=row.reason,
        plan_changed=row.plan_changed,
        undo_available=row.status == "applied" and not optimization.undo_blockers(db, row, now=now),
        slow_after_seconds=int(limit.slow_after.total_seconds()),
        timeout_seconds=int(limit.timeout.total_seconds()),
        summary=optimization.build_summary(db, row),
    )


def _error(exc: optimization.OptimizationError) -> AppError:
    return AppError.for_code(exc.code, str(exc), details=exc.details)


@router.post("", status_code=202)
def request_optimization_endpoint(
    db: Session = DB_SESSION, jobs: JobScheduler = Depends(get_request_job_scheduler)
) -> OptimizationResponse:
    """Starts the background run (202). The client polls `GET /latest`."""
    try:
        row = optimization.request_optimization(db, jobs, now=utcnow())
    except optimization.OptimizationError as exc:
        raise _error(exc) from exc
    return _respond(db, row)


class OpportunityResponse(BaseModel):
    """What Optimize Schedule would achieve right now (design doc §6.11): `gain` is how many more
    tasks would be scheduled than today (net, never negative). `worthwhile` is `gain > 0`; moves
    alone and swaps are not value, and a plan placing fewer tasks than today is never one."""

    gain: int
    newly_scheduled: int
    lost: int
    over_budget: int
    moved: int
    needs_approval: bool
    worthwhile: bool


@router.get("/opportunity")
def optimization_opportunity_endpoint(db: Session = DB_SESSION) -> OpportunityResponse:
    """Read-only: runs the plan without the write lock and writes nothing, so the Timeline can ask
    on every load without getting in anyone's way."""
    found = optimization.opportunity(db)
    return OpportunityResponse(
        gain=found.gain,
        newly_scheduled=found.newly_scheduled,
        lost=found.lost,
        over_budget=found.over_budget,
        moved=found.moved,
        needs_approval=found.needs_approval,
        worthwhile=found.worthwhile,
    )


@router.get("/latest")
def latest_optimization_endpoint(db: Session = DB_SESSION) -> OptimizationResponse | None:
    """The most recent optimization, or `null`. Polled while one runs, and read after a reload so
    the summary and the Undo survive it."""
    row = optimization.latest(db)
    return _respond(db, row) if row is not None else None


@router.post("/{optimization_id}/approve", status_code=202)
def approve_optimization_endpoint(
    optimization_id: str, db: Session = DB_SESSION, jobs: JobScheduler = Depends(get_request_job_scheduler)
) -> OptimizationResponse:
    try:
        row = optimization.approve(db, jobs, optimization_id, now=utcnow())
    except optimization.OptimizationError as exc:
        raise _error(exc) from exc
    return _respond(db, row)


@router.post("/{optimization_id}/decline")
def decline_optimization_endpoint(optimization_id: str, db: Session = DB_SESSION) -> OptimizationResponse:
    try:
        row = optimization.decline(db, optimization_id, now=utcnow())
    except optimization.OptimizationError as exc:
        raise _error(exc) from exc
    return _respond(db, row)


@router.post("/{optimization_id}/undo")
def undo_optimization_endpoint(
    optimization_id: str, db: Session = DB_SESSION, jobs: JobScheduler = Depends(get_request_job_scheduler)
) -> OptimizationResponse:
    try:
        row = optimization.undo(db, jobs, optimization_id, now=utcnow())
    except optimization.OptimizationError as exc:
        raise _error(exc) from exc
    return _respond(db, row)
