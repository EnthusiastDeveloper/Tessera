"""Creation-time feasibility validation for flexible tasks. See design doc §6.8.

Before a flexible TaskTemplate (and its initial instance) is saved, its
`estimated_duration_minutes` must fit within at least one day's effective
active-hours window - otherwise it would sit `pending` forever, re-triggering
`unschedulable` on every pass with no signal that the real problem is that the
task is structurally too big to ever fit as a single block.
"""

from __future__ import annotations

from app.scheduling_engine.grid import DEFAULT_GRID_MINUTES, usable_minutes
from app.scheduling_engine.types import ActiveHoursMap


def validate_feasible_duration(
    estimated_duration_minutes: int,
    effective_active_hours_map: ActiveHoursMap,
    grid_minutes: int = DEFAULT_GRID_MINUTES,
) -> bool:
    """True if `estimated_duration_minutes` fits some day's usable window.

    `effective_active_hours_map` must already be the MERGED map (see
    `calendar_rules.merge_active_hours`) - checking a template's override in
    isolation would reject tasks that are feasible against the combined map.
    """
    windows = [window for window in effective_active_hours_map.values() if window is not None]
    if not windows:
        return False
    return estimated_duration_minutes <= max(usable_minutes(window, grid_minutes) for window in windows)
