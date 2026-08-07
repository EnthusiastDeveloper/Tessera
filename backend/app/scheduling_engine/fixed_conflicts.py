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


def check_fixed_conflict(start: datetime, end: datetime, obstacles: Sequence[Obstacle]) -> bool:
    """True if the half-open interval [start, end) overlaps any obstacle.

    Touching boundaries (one interval ending exactly when another starts) do not
    count as a conflict.
    """
    return any(start < obstacle.end and obstacle.start < end for obstacle in obstacles)
