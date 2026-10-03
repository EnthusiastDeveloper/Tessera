"""JSON-column (de)serialization for per-day active-hours maps - `UserSettings.active_hours`
(§3.7, always present) and `TaskTemplate.active_hours_override` (§3.2, nullable). Shared
by both repositories; a per-day `null` means "day excluded" in either (§3.2, B4), and a
day otherwise holds a list of windows (§3.7, Rev 13).
"""

from __future__ import annotations

from typing import Any, cast, overload

from app.db.schemas import ActiveHoursWindow, DayName


@overload
def serialize_active_hours(mapping: dict[DayName, list[ActiveHoursWindow] | None]) -> dict[str, list[dict[str, str]] | None]: ...
@overload
def serialize_active_hours(mapping: None) -> None: ...
def serialize_active_hours(
    mapping: dict[DayName, list[ActiveHoursWindow] | None] | None,
) -> dict[str, list[dict[str, str]] | None] | None:
    if mapping is None:
        return None
    return {
        day: ([window.model_dump() for window in windows] if windows is not None else None) for day, windows in mapping.items()
    }


@overload
def deserialize_active_hours(raw: dict[str, Any]) -> dict[DayName, list[ActiveHoursWindow] | None]: ...
@overload
def deserialize_active_hours(raw: None) -> None: ...
def deserialize_active_hours(raw: dict[str, Any] | None) -> dict[DayName, list[ActiveHoursWindow] | None] | None:
    if raw is None:
        return None
    return {
        cast(DayName, day): ([ActiveHoursWindow(**window) for window in windows] if windows is not None else None)
        for day, windows in raw.items()
    }
