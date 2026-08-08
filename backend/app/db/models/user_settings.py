"""ORM model for `UserSettings`. See design doc §3.7.

Singleton in practice (one row for the single POC user) - nothing at the schema level
enforces that; `UserSettingsRepository` is responsible for the singleton access pattern.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import JSON, Enum, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, generate_id

_DAY_NAMES = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")


class UserSettingsORM(Base):
    """Global scheduling preferences. See §3.7 for the per-day map semantics."""

    __tablename__ = "user_settings"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=generate_id)
    timezone: Mapped[str] = mapped_column(String, nullable=False)

    # {day_name: {"start": "HH:MM", "end": "HH:MM"} | null}. Per-day null == excluded (§3.7).
    active_hours: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)

    # [{"start": "YYYY-MM-DD", "end": "YYYY-MM-DD", "label": str | null}, ...]
    blackout_dates: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)

    # {day_name: int | null}. null == unlimited for that day.
    daily_time_budget_minutes: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)

    # `create_constraint=True` on every `Enum` here: SQLAlchemy 2.0 defaults it to False -
    # see task_template.py's note.
    budget_enforcement: Mapped[str] = mapped_column(
        Enum("strict", "soft", name="budget_enforcement", create_constraint=True), nullable=False, default="soft"
    )
    first_day_of_week: Mapped[str] = mapped_column(
        Enum(*_DAY_NAMES, name="first_day_of_week", create_constraint=True), nullable=False, default="monday"
    )
