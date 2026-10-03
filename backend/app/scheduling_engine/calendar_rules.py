"""Day-of-week resolution, blackout exclusion, and active-hours merging.

See design doc §3.2 (`active_hours_override`), §3.7 (`active_hours`, `blackout_dates`)
and §6.2 (`effective_hours(day)`).
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from datetime import date, datetime, time, timedelta, tzinfo

from app.scheduling_engine.types import DAY_NAMES, ActiveHoursMap, ActiveHoursWindow, BlackoutDate

type Interval = tuple[datetime, datetime]


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
    if not override:
        return global_hours
    merged = dict(global_hours)
    merged.update(override)
    return merged


def _minute_of_day(moment: time) -> int:
    return moment.hour * 60 + moment.minute


def validate_day_windows(windows: Sequence[ActiveHoursWindow]) -> str | None:
    """Why `windows` can't be one day's list, or None if it can (§3.7).

    A window needs a length (`end != start`); an overnight window (`end < start`) runs to
    the next morning. Within one day the windows must not overlap, measured on the
    timeline that starts at that day's midnight - so `22:00`-`02:00` and `01:00`-`03:00`
    on the same day don't overlap (the first ends on the next date). Windows of
    *different* days may overlap freely; they are merged when placing (`eligible_intervals`).
    """
    spans: list[tuple[int, int]] = []
    for window in windows:
        start, end = _minute_of_day(window.start), _minute_of_day(window.end)
        if start == end:
            return f"A window can't start and end at the same time ({window.start:%H:%M})."
        spans.append((start, end if end > start else end + 24 * 60))
    spans.sort()
    furthest_end = -1
    for start, end in spans:
        if start < furthest_end:
            return "Windows on the same day can't overlap."
        furthest_end = max(furthest_end, end)
    return None


def window_interval(day: date, window: ActiveHoursWindow, tz: tzinfo | None) -> Interval:
    """The absolute interval of `window` declared on `day`: an overnight one ends on `day + 1`."""
    start = datetime.combine(day, window.start, tzinfo=tz)
    end_day = day if window.end > window.start else day + timedelta(days=1)
    return start, datetime.combine(end_day, window.end, tzinfo=tz)


def merge_touching(intervals: Sequence[Interval]) -> list[Interval]:
    """Sort `intervals` and join any that overlap or meet end to start."""
    merged: list[Interval] = []
    for start, end in sorted(intervals):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def eligible_intervals(
    first_day: date, last_day: date, hours: ActiveHoursMap, excluded_dates: Sequence[BlackoutDate], tz: tzinfo | None
) -> list[Interval]:
    """Every stretch of time placement may use that overlaps `first_day`..`last_day` (§6.2).

    Each date contributes the windows its day of the week lists; an overnight window carries
    over into the next date, so the day before `first_day` is read too. Overlapping or
    touching windows (Monday's spill-over into Tuesday's morning window) merge into one
    stretch a task may straddle midnight inside. Then a blackout date cuts at midnight:
    whatever falls on a blacked-out calendar date is removed, whichever window it came from.
    """
    raw: list[Interval] = []
    for day in day_range(first_day - timedelta(days=1), last_day):
        for window in hours.get(day_name(day)) or ():
            raw.append(window_interval(day, window, tz))
    merged = merge_touching(raw)
    if not excluded_dates:
        return merged

    kept: list[Interval] = []
    for start, end in merged:
        for day in day_range(start.date(), end.date()):
            segment_start = max(start, datetime.combine(day, time.min, tzinfo=tz))
            segment_end = min(end, datetime.combine(day + timedelta(days=1), time.min, tzinfo=tz))
            if segment_start < segment_end and not is_blacked_out(day, excluded_dates):
                kept.append((segment_start, segment_end))
    return merge_touching(kept)
