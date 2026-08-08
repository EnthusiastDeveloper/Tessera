"""Settings endpoints: GET/PATCH /api/v1/settings. See design doc §3.7, architecture-plan §3."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.errors import AppError
from app.db.schemas import ActiveHoursWindow, BlackoutDate, DayName, UserSettings
from app.db.session import get_db
from app.settings import service

router = APIRouter(prefix="/api/v1/settings", tags=["settings"])

_VALIDATION_ERROR_STATUS = {
    "invalid_timezone": 422,
    "invalid_day_map": 422,
    "settings_not_initialized": 500,
}


class SettingsPatchRequest(BaseModel):
    """All fields optional - only keys actually present in the request body are applied.

    None of these fields has a meaningful "clear to null" state (there is no such thing
    as a null timezone), so `exclude_unset` alone - without the omitted-vs-null sentinel
    dance architecture-plan §5.1 describes for TaskInstance/TaskTemplate - is sufficient
    here.
    """

    timezone: str | None = None
    active_hours: dict[DayName, ActiveHoursWindow | None] | None = None
    blackout_dates: list[BlackoutDate] | None = None
    daily_time_budget_minutes: dict[DayName, int | None] | None = None
    budget_enforcement: Literal["strict", "soft"] | None = None
    first_day_of_week: DayName | None = None


@router.get("")
def get_settings_endpoint(db: Session = Depends(get_db)) -> UserSettings:
    return service.get_or_create_default(db, default_timezone="UTC")


@router.patch("")
def patch_settings_endpoint(payload: SettingsPatchRequest, db: Session = Depends(get_db)) -> UserSettings:
    # Deliberately not payload.model_dump() - that recursively flattens nested models
    # (ActiveHoursWindow, BlackoutDate) to plain dicts, and model_copy(update=...) below
    # does not re-validate, so the domain object would end up holding raw dicts where it
    # expects real ActiveHoursWindow/BlackoutDate instances. Reading fields directly off
    # the already-validated payload keeps them as the real objects Pydantic parsed.
    patch: dict[str, Any] = {field: getattr(payload, field) for field in payload.model_fields_set}
    if patch.get("blackout_dates") is not None:
        patch["blackout_dates"] = tuple(patch["blackout_dates"])
    try:
        return service.update_settings(db, patch=patch)
    except service.SettingsValidationError as exc:
        raise AppError(_VALIDATION_ERROR_STATUS[exc.code], exc.code, str(exc)) from exc
