"""Repository for `TaskInstance` rows. See design doc §3.3, architecture-plan §2."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any, cast

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.task_instance import TaskInstanceORM, task_instance_dependencies
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

    def list_by_statuses(self, statuses: Sequence[str]) -> tuple[TaskInstance, ...]:
        """Every instance in any of `statuses` - the obstacle set is `scheduled`/`in_progress`, both types (§6.2)."""
        stmt = select(TaskInstanceORM).where(TaskInstanceORM.status.in_(statuses))
        return tuple(_to_domain(orm) for orm in self._session.scalars(stmt))

    def list_all_dependency_edges(self) -> tuple[tuple[str, str], ...]:
        """Every `(dependent_id, dependency_id)` edge system-wide - what `cycle_check`
        (§6.1) validates a proposed new edge set against.
        """
        rows = self._session.execute(
            select(task_instance_dependencies.c.dependent_id, task_instance_dependencies.c.dependency_id)
        )
        return tuple((dependent_id, dependency_id) for dependent_id, dependency_id in rows)

    def list_by_template(self, template_id: str) -> tuple[TaskInstance, ...]:
        """Every instance generated from `template_id`, most recent first - "this and future"
        propagation (§3.10) needs to find the currently-live one.
        """
        stmt = (
            select(TaskInstanceORM)
            .where(TaskInstanceORM.template_id == template_id)
            .order_by(TaskInstanceORM.generated_at.desc())
        )
        return tuple(_to_domain(orm) for orm in self._session.scalars(stmt))

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
        """No cascading delete (§3.8) - dependents just lose the link, via the join table's `ondelete=CASCADE`.

        That cascade happens at the SQLite level, which SQLAlchemy's session has no way
        to know about on its own: a dependent instance already loaded in this session
        would otherwise keep serving its stale, pre-deletion `dependencies` collection
        from the identity map. `expire_all()` forces every already-loaded object to
        re-query on next access, so a caller checking "does this instance still have
        dependencies" right after a delete sees the real, post-cascade answer.
        """
        orm = self._session.get(TaskInstanceORM, instance_id)
        if orm is None:
            raise LookupError(f"TaskInstance {instance_id} not found")
        self._session.delete(orm)
        self._session.flush()
        self._session.expire_all()

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
