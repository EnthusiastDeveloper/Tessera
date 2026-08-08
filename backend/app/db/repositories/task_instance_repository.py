"""Repository for `TaskInstance` rows. See design doc §3.3, architecture-plan §2."""

from __future__ import annotations

from datetime import datetime
from typing import Any, cast

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.task_instance import TaskInstanceORM
from app.db.schemas import StatusHistoryEntry, TaskInstance, TaskInstanceStatus, TaskType


class TaskInstanceRepository:
    """CRUD plus the dependency-graph lookups the Backlog view needs (§8.1, §3.3)."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def create(self, instance: TaskInstance) -> TaskInstance:
        """`instance` must already carry a generated `id` and initial timestamps/version."""
        orm = TaskInstanceORM(**_to_orm_kwargs(instance))
        orm.dependencies = self._resolve(instance.dependencies)
        self._session.add(orm)
        self._session.flush()
        return _to_domain(orm)

    def get(self, instance_id: str) -> TaskInstance | None:
        orm = self._session.get(TaskInstanceORM, instance_id)
        return _to_domain(orm) if orm is not None else None

    def list_pending_flexible(self) -> tuple[TaskInstance, ...]:
        """Candidates for the next scheduling pass (§6.2)."""
        stmt = select(TaskInstanceORM).where(TaskInstanceORM.status == "pending", TaskInstanceORM.type == "flexible")
        return tuple(_to_domain(orm) for orm in self._session.scalars(stmt))

    def list_dependents(self, instance_id: str) -> tuple[TaskInstance, ...]:
        """Instances waiting on `instance_id` - the Backlog view's reverse navigation direction (§8.1, §3.3)."""
        orm = self._session.get(TaskInstanceORM, instance_id)
        if orm is None:
            raise LookupError(f"TaskInstance {instance_id} not found")
        return tuple(_to_domain(dependent) for dependent in orm.dependents)

    def update(self, instance: TaskInstance) -> TaskInstance:
        """Full-row update. Partial-PATCH conflict semantics (architecture-plan §5.1) are a service-layer concern.

        `version` is never assigned here - it is the `version_id_col` (architecture-plan
        §5), incremented automatically by the ORM on flush. Letting a caller set it
        directly would let a stale write reset the optimistic-lock counter it exists to
        protect.
        """
        orm = self._session.get(TaskInstanceORM, instance.id)
        if orm is None:
            raise LookupError(f"TaskInstance {instance.id} not found")
        for key, value in _to_orm_kwargs(instance).items():
            if key not in ("id", "generated_at", "created_at", "version"):
                setattr(orm, key, value)
        orm.dependencies = self._resolve(instance.dependencies)
        self._session.flush()
        return _to_domain(orm)

    def delete(self, instance_id: str) -> None:
        """No cascading delete (§3.8) - dependents just lose the link, via the join table's `ondelete=CASCADE`."""
        orm = self._session.get(TaskInstanceORM, instance_id)
        if orm is None:
            raise LookupError(f"TaskInstance {instance_id} not found")
        self._session.delete(orm)
        self._session.flush()

    def _resolve(self, ids: tuple[str, ...]) -> list[TaskInstanceORM]:
        if not ids:
            return []
        stmt = select(TaskInstanceORM).where(TaskInstanceORM.id.in_(ids))
        return list(self._session.scalars(stmt))


def _to_orm_kwargs(instance: TaskInstance) -> dict[str, Any]:
    return {
        "id": instance.id,
        "template_id": instance.template_id,
        "name": instance.name,
        "description": instance.description,
        "location": instance.location,
        "type": instance.type,
        "priority": instance.priority,
        "estimated_duration_minutes": instance.estimated_duration_minutes,
        "detached": instance.detached,
        "scheduled_time": instance.scheduled_time,
        "deadline": instance.deadline,
        "status": instance.status,
        "status_history": [_serialize_status_entry(entry) for entry in instance.status_history],
        "completed_at": instance.completed_at,
        "generated_at": instance.generated_at,
        "created_at": instance.created_at,
        "updated_at": instance.updated_at,
        "version": instance.version,
    }


def _serialize_status_entry(entry: StatusHistoryEntry) -> dict[str, str]:
    return {"status": entry.status, "at": entry.at.isoformat()}


def _deserialize_status_entry(raw: dict[str, str]) -> StatusHistoryEntry:
    return StatusHistoryEntry(status=cast(TaskInstanceStatus, raw["status"]), at=datetime.fromisoformat(raw["at"]))


def _to_domain(orm: TaskInstanceORM) -> TaskInstance:
    return TaskInstance(
        id=orm.id,
        template_id=orm.template_id,
        name=orm.name,
        description=orm.description,
        location=orm.location,
        type=cast(TaskType, orm.type),
        priority=orm.priority,
        estimated_duration_minutes=orm.estimated_duration_minutes,
        detached=orm.detached,
        scheduled_time=orm.scheduled_time,
        deadline=orm.deadline,
        status=cast(TaskInstanceStatus, orm.status),
        status_history=tuple(_deserialize_status_entry(entry) for entry in orm.status_history),
        dependencies=tuple(dependency.id for dependency in orm.dependencies),
        completed_at=orm.completed_at,
        generated_at=orm.generated_at,
        created_at=orm.created_at,
        updated_at=orm.updated_at,
        version=orm.version,
    )
