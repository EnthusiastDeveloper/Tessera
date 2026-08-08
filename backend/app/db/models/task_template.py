"""ORM model for `TaskTemplate`. See design doc §3.2.

`recurrence.anchor == "completion"` requiring `type == "flexible"` is a business rule
(`invalid_recurrence_anchor`, §3.2) validated at save time by the service layer (Stage 5),
not a schema-level constraint - see architecture-plan §2 / implementation-plan Stage 2
"Out of scope". Only enum membership is enforced here.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, Enum, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, UTCDateTime, generate_id, utcnow


class TaskTemplateORM(Base):
    """Recurrence rule + defaults a `TaskInstance` is generated from. See §3.2."""

    __tablename__ = "task_templates"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=generate_id)
    name: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str | None] = mapped_column(String, nullable=True)
    location: Mapped[str | None] = mapped_column(String, nullable=True)

    # `create_constraint=True`: SQLAlchemy 2.0 defaults it to False, which would leave
    # `Enum` a Python-side-only check - implementation-plan Stage 2 requires a real
    # DB-level CHECK constraint, so every `Enum` column in this module sets it explicitly.
    type: Mapped[str] = mapped_column(
        Enum("fixed", "flexible", name="task_template_type", create_constraint=True), nullable=False
    )

    # --- Recurrence ---
    recurrence_pattern: Mapped[str] = mapped_column(
        Enum("one_time", "daily", "weekly", "monthly", "custom", name="recurrence_pattern", create_constraint=True),
        nullable=False,
    )
    recurrence_interval: Mapped[int | None] = mapped_column(Integer, nullable=True)
    recurrence_day_of_week: Mapped[int | None] = mapped_column(Integer, nullable=True)
    recurrence_day_of_month: Mapped[int | None] = mapped_column(Integer, nullable=True)
    recurrence_anchor: Mapped[str] = mapped_column(
        Enum("calendar", "completion", name="recurrence_anchor", create_constraint=True), nullable=False
    )

    # --- Fixed-type scheduling ---
    fixed_time_of_day: Mapped[str | None] = mapped_column(String, nullable=True)  # wall-clock "HH:MM", §14.1

    # --- Flexible-type scheduling ---
    deadline_offset_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)

    priority: Mapped[int] = mapped_column(Integer, nullable=False)  # numeric mapping: low=1..critical=4
    estimated_duration_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    reminder_offsets_minutes: Mapped[list[int]] = mapped_column(JSON, nullable=False, default=list)

    # {day_name: {"start": "HH:MM", "end": "HH:MM"} | null} merged per-day over UserSettings.active_hours.
    # NULL (the column itself, not an empty dict) means "no override at all" - distinct from `{}`.
    active_hours_override: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    archived: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow, onupdate=utcnow)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    __mapper_args__ = {"version_id_col": version}
