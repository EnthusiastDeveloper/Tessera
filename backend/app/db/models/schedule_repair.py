"""ORM model for a schedule repair's progress. See design doc §6.10 (Rev 11) and
architecture-plan §5.2 - operational state, not a design doc §3 entity.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, UTCDateTime, generate_id


class ScheduleRepairORM(Base):
    """One background repair, from the settings save that started it to its last move."""

    __tablename__ = "schedule_repairs"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=generate_id)
    total: Mapped[int] = mapped_column(Integer, nullable=False)
    done: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    moved: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    unschedulable: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    requested_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, index=True)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
