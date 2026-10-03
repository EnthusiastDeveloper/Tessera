"""Repository for `ScheduleOptimization` rows. See design doc §6.11, architecture-plan §5.4."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.schedule_optimization import ScheduleOptimizationORM
from app.db.schemas import ScheduleOptimization


class ScheduleOptimizationRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def create(self, optimization: ScheduleOptimization) -> ScheduleOptimization:
        orm = ScheduleOptimizationORM(**optimization.model_dump())
        self._session.add(orm)
        self._session.flush()
        return _to_domain(orm)

    def get(self, optimization_id: str) -> ScheduleOptimization | None:
        orm = self._session.get(ScheduleOptimizationORM, optimization_id)
        return _to_domain(orm) if orm is not None else None

    def latest(self) -> ScheduleOptimization | None:
        orm = self._session.scalars(
            select(ScheduleOptimizationORM).order_by(
                ScheduleOptimizationORM.requested_at.desc(), ScheduleOptimizationORM.id.desc()
            )
        ).first()
        return _to_domain(orm) if orm is not None else None

    def list_with_status(self, *statuses: str) -> list[ScheduleOptimization]:
        rows = self._session.scalars(select(ScheduleOptimizationORM).where(ScheduleOptimizationORM.status.in_(statuses))).all()
        return [_to_domain(orm) for orm in rows]

    def update(self, optimization: ScheduleOptimization) -> ScheduleOptimization:
        orm = self._session.get(ScheduleOptimizationORM, optimization.id)
        if orm is None:
            raise LookupError(f"ScheduleOptimization {optimization.id} not found")
        for key, value in optimization.model_dump(exclude={"id"}).items():
            setattr(orm, key, value)
        self._session.flush()
        return _to_domain(orm)


def _to_domain(orm: ScheduleOptimizationORM) -> ScheduleOptimization:
    return ScheduleOptimization(
        id=orm.id,
        status=orm.status,
        requested_at=orm.requested_at,
        finished_at=orm.finished_at,
        approved=orm.approved,
        plan_changed=orm.plan_changed,
        valid_until=orm.valid_until,
        undo_until=orm.undo_until,
        reason=orm.reason,
        plan=orm.plan,
        applied_versions=orm.applied_versions,
    )
