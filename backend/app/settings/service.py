"""UserSettings orchestration: first-run default creation, validation, partial update.

See design doc §3.7, §14.1 (timezone default from `TZ`). Framework-agnostic, like every
other service-layer module (architecture-plan §2) - no FastAPI imports here.
"""

from __future__ import annotations

from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy.orm import Session

from app.db.base import generate_id
from app.db.repositories import UserSettingsRepository
from app.db.schemas import ActiveHoursWindow, DayName, UserSettings

DAY_NAMES: tuple[DayName, ...] = (
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
)

# Not specified in design doc §3.7 or architecture-plan for a freshly-created row - the
# only explicitly stated defaults are timezone (from TZ), budget_enforcement ("soft") and
# first_day_of_week ("monday"). active_hours confirmed with the user: every day open
# 09:00-17:00, so scheduling works out of the box rather than silently placing nothing
# until the user visits Settings (a per-day `null` means *excluded*, not unrestricted -
# see §3.2/§3.7 - so "every day null" would be the opposite of a usable default).
DEFAULT_ACTIVE_HOURS: dict[DayName, ActiveHoursWindow | None] = {
    day: ActiveHoursWindow(start="09:00", end="17:00") for day in DAY_NAMES
}
DEFAULT_DAILY_TIME_BUDGET: dict[DayName, int | None] = dict.fromkeys(DAY_NAMES, None)


class SettingsValidationError(Exception):
    """Raised by `update_settings()`. `code` maps to the API error envelope (architecture-plan §3)."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def get_or_create_default(db: Session, *, default_timezone: str) -> UserSettings:
    """The single `UserSettings` row, creating it with defaults on first run if absent."""
    repo = UserSettingsRepository(db)
    existing = repo.get()
    if existing is not None:
        return existing
    return repo.create(
        UserSettings(
            id=generate_id(),
            timezone=default_timezone,
            active_hours=dict(DEFAULT_ACTIVE_HOURS),
            blackout_dates=(),
            daily_time_budget_minutes=dict(DEFAULT_DAILY_TIME_BUDGET),
            budget_enforcement="soft",
            first_day_of_week="monday",
        )
    )


def update_settings(db: Session, *, patch: dict[str, Any]) -> UserSettings:
    """Apply a genuinely partial update - only keys present in `patch` are touched.

    `patch` values for `active_hours`/`daily_time_budget_minutes`/`blackout_dates` are
    already-validated Pydantic sub-models from the API layer's request schema; this
    function owns the checks Pydantic's type system alone can't express (a real IANA
    timezone name, the exact 7-day key set).
    """
    repo = UserSettingsRepository(db)
    current = repo.get()
    if current is None:
        raise SettingsValidationError("settings_not_initialized", "Settings have not been created yet.")

    updates: dict[str, Any] = {}

    if "timezone" in patch:
        _validate_timezone(patch["timezone"])
        updates["timezone"] = patch["timezone"]

    if "active_hours" in patch:
        _validate_full_week(patch["active_hours"], "active_hours")
        updates["active_hours"] = patch["active_hours"]

    if "daily_time_budget_minutes" in patch:
        _validate_full_week(patch["daily_time_budget_minutes"], "daily_time_budget_minutes")
        updates["daily_time_budget_minutes"] = patch["daily_time_budget_minutes"]

    if "blackout_dates" in patch:
        updates["blackout_dates"] = patch["blackout_dates"]

    if "budget_enforcement" in patch:
        updates["budget_enforcement"] = patch["budget_enforcement"]

    if "first_day_of_week" in patch:
        updates["first_day_of_week"] = patch["first_day_of_week"]

    updated = current.model_copy(update=updates)
    return repo.update(updated)


def _validate_timezone(tz: str) -> None:
    try:
        ZoneInfo(tz)
    except ZoneInfoNotFoundError as exc:
        raise SettingsValidationError("invalid_timezone", f"'{tz}' is not a valid IANA timezone name.") from exc


def _validate_full_week(mapping: dict[str, Any], field_name: str) -> None:
    provided = set(mapping.keys())
    expected = set(DAY_NAMES)
    if provided != expected:
        missing = expected - provided
        extra = provided - expected
        detail = []
        if missing:
            detail.append(f"missing {sorted(missing)}")
        if extra:
            detail.append(f"unexpected {sorted(extra)}")
        raise SettingsValidationError(
            "invalid_day_map", f"{field_name} must have exactly the 7 day-of-week keys ({', '.join(detail)})."
        )


def default_timezone_from_env(tz_env_value: str | None) -> str:
    """Resolve the `TZ` env var to a timezone to seed the default settings row with.

    Falls back to UTC - silently for an unset value (documented as optional with a
    sensible default, architecture-plan §7.1), with a warning left to the caller for an
    explicitly-set-but-invalid one, since that's a real misconfiguration worth surfacing.
    """
    if not tz_env_value:
        return "UTC"
    try:
        ZoneInfo(tz_env_value)
    except ZoneInfoNotFoundError:
        return "UTC"
    return tz_env_value


__all__ = [
    "DAY_NAMES",
    "DEFAULT_ACTIVE_HOURS",
    "DEFAULT_DAILY_TIME_BUDGET",
    "SettingsValidationError",
    "default_timezone_from_env",
    "get_or_create_default",
    "update_settings",
]
