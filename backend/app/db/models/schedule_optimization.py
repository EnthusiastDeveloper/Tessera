"""ORM model for an "Optimize Schedule" operation. See design doc §6.11 (Rev 14) and
architecture-plan §5.4 - operational state, not a design doc §3 entity.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, Enum, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, UTCDateTime, generate_id

OPTIMIZATION_STATUSES = (
    "running",
    "awaiting_approval",
    "applied",
    "nothing_to_do",
    "declined",
    "undone",
    "expired",
    "failed",
)


class ScheduleOptimizationORM(Base):
    """One optimization, from the click that requested it to its last state."""

    __tablename__ = "schedule_optimizations"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=generate_id)
    # `create_constraint=True`: see task_template.py's note on every `Enum` here.
    status: Mapped[str] = mapped_column(
        Enum(*OPTIMIZATION_STATUSES, name="schedule_optimization_status", create_constraint=True), nullable=False
    )
    requested_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    # The user has approved the held plan; the job recomputes and applies it only if unchanged.
    approved: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # The plan the user approved no longer matched when it was recomputed, so a fresh one is held.
    plan_changed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    valid_until: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    undo_until: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    # `nothing_to_do`'s reason, or a failure's explanation.
    reason: Mapped[str | None] = mapped_column(String, nullable=True)
    # The plan (moved / newly scheduled / lost / counts) as JSON - see `app.scheduling.optimization`.
    plan: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    # {instance_id: version} for every instance the operation changed, as it finished - Undo's
    # "nobody touched it since" check.
    applied_versions: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
