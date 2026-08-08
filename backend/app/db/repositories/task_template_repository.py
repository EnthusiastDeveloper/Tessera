"""Repository for `TaskTemplate` rows. See design doc §3.2, architecture-plan §2."""

from __future__ import annotations

from typing import Any, cast

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.task_template import TaskTemplateORM
from app.db.schemas import (
    ActiveHoursWindow,
    DayName,
    Priority,
    Recurrence,
    RecurrenceAnchor,
    RecurrencePattern,
    TaskTemplate,
    TaskType,
)

# Numeric priority mapping is internal-only, never exposed in the API (§3.2 notes).
_PRIORITY_TO_INT: dict[Priority, int] = {"low": 1, "medium": 2, "high": 3, "critical": 4}
_INT_TO_PRIORITY: dict[int, Priority] = {value: key for key, value in _PRIORITY_TO_INT.items()}


class TaskTemplateRepository:
    """CRUD for `TaskTemplate`. Converts to/from `TaskTemplateORM` - never leaks ORM rows past this layer."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def create(self, template: TaskTemplate) -> TaskTemplate:
        """`template` must already carry a generated `id` and initial timestamps/version."""
        orm = TaskTemplateORM(**_to_orm_kwargs(template))
        self._session.add(orm)
        self._session.flush()
        return _to_domain(orm)

    def get(self, template_id: str) -> TaskTemplate | None:
        orm = self._session.get(TaskTemplateORM, template_id)
        return _to_domain(orm) if orm is not None else None

    def list(self, *, include_archived: bool = False) -> tuple[TaskTemplate, ...]:
        stmt = select(TaskTemplateORM)
        if not include_archived:
            stmt = stmt.where(TaskTemplateORM.archived.is_(False))
        return tuple(_to_domain(orm) for orm in self._session.scalars(stmt))

    def update(self, template: TaskTemplate) -> TaskTemplate:
        """Full-row update. Partial-PATCH conflict semantics (architecture-plan §5.1) are a service-layer concern.

        `version` is never assigned here - it is the `version_id_col` (architecture-plan
        §5), incremented automatically by the ORM on flush. Letting a caller set it
        directly would let a stale write reset the optimistic-lock counter it exists to
        protect.
        """
        orm = self._session.get(TaskTemplateORM, template.id)
        if orm is None:
            raise LookupError(f"TaskTemplate {template.id} not found")
        for key, value in _to_orm_kwargs(template).items():
            if key not in ("id", "created_at", "version"):
                setattr(orm, key, value)
        self._session.flush()
        return _to_domain(orm)

    def archive(self, template_id: str) -> TaskTemplate:
        """Soft-delete. See §3.8 - templates with history are archived, never hard-deleted."""
        orm = self._session.get(TaskTemplateORM, template_id)
        if orm is None:
            raise LookupError(f"TaskTemplate {template_id} not found")
        orm.archived = True
        self._session.flush()
        return _to_domain(orm)


def _to_orm_kwargs(template: TaskTemplate) -> dict[str, Any]:
    return {
        "id": template.id,
        "name": template.name,
        "description": template.description,
        "location": template.location,
        "type": template.type,
        "recurrence_pattern": template.recurrence.pattern,
        "recurrence_interval": template.recurrence.interval,
        "recurrence_day_of_week": template.recurrence.day_of_week,
        "recurrence_day_of_month": template.recurrence.day_of_month,
        "recurrence_anchor": template.recurrence.anchor,
        "fixed_time_of_day": template.fixed_time_of_day,
        "deadline_offset_minutes": template.deadline_offset_minutes,
        "priority": _PRIORITY_TO_INT[template.priority],
        "estimated_duration_minutes": template.estimated_duration_minutes,
        "reminder_offsets_minutes": list(template.reminder_offsets_minutes),
        "active_hours_override": _serialize_active_hours(template.active_hours_override),
        "archived": template.archived,
        "created_at": template.created_at,
        "updated_at": template.updated_at,
        "version": template.version,
    }


def _serialize_active_hours(
    override: dict[DayName, ActiveHoursWindow | None] | None,
) -> dict[str, dict[str, str] | None] | None:
    if override is None:
        return None
    return {day: (window.model_dump() if window is not None else None) for day, window in override.items()}


def _deserialize_active_hours(
    raw: dict[str, Any] | None,
) -> dict[DayName, ActiveHoursWindow | None] | None:
    if raw is None:
        return None
    return {cast(DayName, day): (ActiveHoursWindow(**window) if window is not None else None) for day, window in raw.items()}


def _to_domain(orm: TaskTemplateORM) -> TaskTemplate:
    return TaskTemplate(
        id=orm.id,
        name=orm.name,
        description=orm.description,
        location=orm.location,
        type=cast(TaskType, orm.type),
        recurrence=Recurrence(
            pattern=cast(RecurrencePattern, orm.recurrence_pattern),
            interval=orm.recurrence_interval,
            day_of_week=orm.recurrence_day_of_week,
            day_of_month=orm.recurrence_day_of_month,
            anchor=cast(RecurrenceAnchor, orm.recurrence_anchor),
        ),
        fixed_time_of_day=orm.fixed_time_of_day,
        deadline_offset_minutes=orm.deadline_offset_minutes,
        priority=_INT_TO_PRIORITY[orm.priority],
        estimated_duration_minutes=orm.estimated_duration_minutes,
        reminder_offsets_minutes=tuple(orm.reminder_offsets_minutes),
        active_hours_override=_deserialize_active_hours(orm.active_hours_override),
        archived=orm.archived,
        created_at=orm.created_at,
        updated_at=orm.updated_at,
        version=orm.version,
    )
