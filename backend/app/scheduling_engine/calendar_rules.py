"""Day-of-week resolution, blackout exclusion, and active-hours merging.

See design doc §3.2 (`active_hours_override`), §3.7 (`active_hours`, `blackout_dates`)
and §6.2 (`effective_hours(day)`).
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from datetime import date, timedelta

from app.scheduling_engine.types import DAY_NAMES, ActiveHoursMap, BlackoutDate


def day_name(day: date) -> str:
    """The lowercase day-of-week name for `day`, matching §3.7's map keys."""
    return DAY_NAMES[day.weekday()]


def day_range(start: date, end: date) -> Iterator[date]:
    """Yield each date from `start` to `end` inclusive, in order. Empty if start > end."""
    current = start
    while current <= end:
        yield current
        current += timedelta(days=1)


def is_blacked_out(day: date, blackout_dates: Sequence[BlackoutDate]) -> bool:
    """True if `day` falls inside any full-day exclusion range (§3.7)."""
    return any(blackout.start <= day <= blackout.end for blackout in blackout_dates)


def merge_active_hours(global_hours: ActiveHoursMap, override: ActiveHoursMap | None) -> ActiveHoursMap:
    """Merge a template's `active_hours_override` over the global settings map (§3.2, §6.2).

    Per-day, not whole-map: a day named in `override` (including with value None,
    meaning excluded) uses the override's value; a day *not* named in `override`
    inherits the global map's value untouched. `override=None` or `{}` inherits the
    global map entirely. This merge is what design doc Example B exists to pin down -
    a whole-map replacement would silently wipe out every day the override didn't
    mention.
    """
    merged = dict(global_hours)
    merged.update(override or {})
    return merged
