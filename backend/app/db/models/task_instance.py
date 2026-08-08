"""ORM model for `TaskInstance`. See design doc §3.3.

`dependencies` is persisted as a join table (`task_instance_dependencies`), not an array
column, so the Backlog view can navigate "what does this depend on" and "what depends on
this" without a full-table scan - see §3.3's note and architecture-plan §2.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, Column, Enum, ForeignKey, Integer, String, Table
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, UTCDateTime, generate_id, utcnow

task_instance_dependencies = Table(
    "task_instance_dependencies",
    Base.metadata,
    Column("dependent_id", String, ForeignKey("task_instances.id", ondelete="CASCADE"), primary_key=True),
    Column("dependency_id", String, ForeignKey("task_instances.id", ondelete="CASCADE"), primary_key=True),
)


class TaskInstanceORM(Base):
    """The schedulable unit generated from a `TaskTemplate`. See §3.3."""

    __tablename__ = "task_instances"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=generate_id)
    template_id: Mapped[str] = mapped_column(String, ForeignKey("task_templates.id"), nullable=False)

    name: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str | None] = mapped_column(String, nullable=True)
    location: Mapped[str | None] = mapped_column(String, nullable=True)
    # `create_constraint=True` on every `Enum` here: SQLAlchemy 2.0 defaults it to False,
    # which would leave `Enum` a Python-side-only check - implementation-plan Stage 2
    # requires a real DB-level CHECK constraint.
    type: Mapped[str] = mapped_column(
        Enum("fixed", "flexible", name="task_instance_type", create_constraint=True), nullable=False
    )
    priority: Mapped[int] = mapped_column(Integer, nullable=False)  # numeric, copied from template at generation
    estimated_duration_minutes: Mapped[int] = mapped_column(Integer, nullable=False)

    detached: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    scheduled_time: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    deadline: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)

    status: Mapped[str] = mapped_column(
        Enum(
            "pending",
            "scheduled",
            "in_progress",
            "completed",
            "blocked",
            "missed",
            "dismissed",
            name="task_instance_status",
            create_constraint=True,
        ),
        nullable=False,
    )
    # [{"status": str, "at": ISO8601 str}, ...] - immutable trail, append-only at the service layer.
    status_history: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)

    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    generated_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)

    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow, onupdate=utcnow)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    # This instance's own dependencies (must all be "completed" before this can start).
    dependencies: Mapped[list["TaskInstanceORM"]] = relationship(
        secondary=task_instance_dependencies,
        primaryjoin=id == task_instance_dependencies.c.dependent_id,
        secondaryjoin=id == task_instance_dependencies.c.dependency_id,
        back_populates="dependents",
    )
    # Instances that depend on this one - the Backlog view's reverse navigation direction.
    dependents: Mapped[list["TaskInstanceORM"]] = relationship(
        secondary=task_instance_dependencies,
        primaryjoin=id == task_instance_dependencies.c.dependency_id,
        secondaryjoin=id == task_instance_dependencies.c.dependent_id,
        back_populates="dependencies",
    )

    __mapper_args__ = {"version_id_col": version}
