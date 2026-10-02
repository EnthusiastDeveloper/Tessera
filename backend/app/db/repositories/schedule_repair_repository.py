"""Repository for `ScheduleRepair` rows. See design doc §6.10, architecture-plan §5.2."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.schedule_repair import ScheduleRepairORM
from app.db.schemas import ScheduleRepair


class ScheduleRepairRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def create(self, repair: ScheduleRepair) -> ScheduleRepair:
        orm = ScheduleRepairORM(**repair.model_dump())
        self._session.add(orm)
        self._session.flush()
        return _to_domain(orm)

    def get(self, repair_id: str) -> ScheduleRepair | None:
        orm = self._session.get(ScheduleRepairORM, repair_id)
        return _to_domain(orm) if orm is not None else None

    def latest(self) -> ScheduleRepair | None:
        orm = self._session.scalars(
            select(ScheduleRepairORM).order_by(ScheduleRepairORM.requested_at.desc(), ScheduleRepairORM.id.desc())
        ).first()
        return _to_domain(orm) if orm is not None else None

    def update(self, repair: ScheduleRepair) -> ScheduleRepair:
        orm = self._session.get(ScheduleRepairORM, repair.id)
        if orm is None:
            raise LookupError(f"ScheduleRepair {repair.id} not found")
        for key, value in repair.model_dump(exclude={"id"}).items():
            setattr(orm, key, value)
        self._session.flush()
        return _to_domain(orm)


def _to_domain(orm: ScheduleRepairORM) -> ScheduleRepair:
    return ScheduleRepair(
        id=orm.id,
        total=orm.total,
        done=orm.done,
        moved=orm.moved,
        unschedulable=orm.unschedulable,
        requested_at=orm.requested_at,
        finished_at=orm.finished_at,
    )
