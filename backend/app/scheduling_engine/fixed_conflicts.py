"""Fixed-task overlap predicate. See design doc §6.5.

On creating/retiming a fixed instance, the caller validates against all other
`scheduled` fixed instances and all known external busy-blocks (filtered per
§7) and hard-blocks the save on overlap. This module is the pure predicate only;
the hard-block/error-code behavior is a service-layer concern (Stage 5).
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from app.scheduling_engine.types import Obstacle


def intervals_overlap(a_start: datetime, a_end: datetime, b_start: datetime, b_end: datetime) -> bool:
    """True if half-open intervals [a_start, a_end) and [b_start, b_end) overlap.

    Touching boundaries (one interval ending exactly when the other starts) do
    not count as overlap. The single shared definition of "overlap" for the
    engine - placement.py reuses this rather than re-deriving the comparison.
    """
    return a_start < b_end and b_start < a_end


def check_fixed_conflict(start: datetime, end: datetime, obstacles: Sequence[Obstacle]) -> bool:
    """True if the half-open interval [start, end) overlaps any obstacle (§6.5)."""
    return any(intervals_overlap(start, end, obstacle.start, obstacle.end) for obstacle in obstacles)
