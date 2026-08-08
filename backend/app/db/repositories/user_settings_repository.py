"""Repository for `UserSettings` rows. See design doc §3.7.

Singleton in practice - the default-row-on-first-run behavior (timezone sourced from
`TZ`) belongs to Stage 4, per implementation-plan Stage 4 "In scope". This repository
only persists/reads whatever row exists; it does not decide defaults.
"""

from __future__ import annotations

from typing import Any, cast

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.user_settings import UserSettingsORM
from app.db.schemas import ActiveHoursWindow, BlackoutDate, BudgetEnforcement, DayName, UserSettings


class UserSettingsRepository:
    """CRUD for the single `UserSettings` row."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def create(self, settings: UserSettings) -> UserSettings:
        orm = UserSettingsORM(**_to_orm_kwargs(settings))
        self._session.add(orm)
        self._session.flush()
        return _to_domain(orm)

    def get(self) -> UserSettings | None:
        """The one settings row, if it has been created yet."""
        orm = self._session.scalars(select(UserSettingsORM)).first()
        return _to_domain(orm) if orm is not None else None

    def update(self, settings: UserSettings) -> UserSettings:
        orm = self._session.get(UserSettingsORM, settings.id)
        if orm is None:
            raise LookupError(f"UserSettings {settings.id} not found")
        for key, value in _to_orm_kwargs(settings).items():
            if key != "id":
                setattr(orm, key, value)
        self._session.flush()
        return _to_domain(orm)


def _to_orm_kwargs(settings: UserSettings) -> dict[str, Any]:
    return {
        "id": settings.id,
        "timezone": settings.timezone,
        "active_hours": _serialize_active_hours(settings.active_hours),
        "blackout_dates": [blackout.model_dump(mode="json") for blackout in settings.blackout_dates],
        "daily_time_budget_minutes": dict(settings.daily_time_budget_minutes),
        "budget_enforcement": settings.budget_enforcement,
        "first_day_of_week": settings.first_day_of_week,
    }


def _serialize_active_hours(
    active_hours: dict[DayName, ActiveHoursWindow | None],
) -> dict[str, dict[str, str] | None]:
    return {day: (window.model_dump() if window is not None else None) for day, window in active_hours.items()}


def _deserialize_active_hours(raw: dict[str, Any]) -> dict[DayName, ActiveHoursWindow | None]:
    return {cast(DayName, day): (ActiveHoursWindow(**window) if window is not None else None) for day, window in raw.items()}


def _to_domain(orm: UserSettingsORM) -> UserSettings:
    return UserSettings(
        id=orm.id,
        timezone=orm.timezone,
        active_hours=_deserialize_active_hours(orm.active_hours),
        blackout_dates=tuple(BlackoutDate(**blackout) for blackout in orm.blackout_dates),
        daily_time_budget_minutes={cast(DayName, day): budget for day, budget in orm.daily_time_budget_minutes.items()},
        budget_enforcement=cast(BudgetEnforcement, orm.budget_enforcement),
        first_day_of_week=cast(DayName, orm.first_day_of_week),
    )
