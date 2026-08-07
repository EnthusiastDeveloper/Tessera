"""Deadline-elapsed gate predicate. See design doc §6.7.

This is the pure predicate only - `is_deadline_elapsed` decides nothing beyond
"has this instant passed". The `missed`-transition orchestration (status change,
`deadline_missed` Notification, exclusion from the candidate pool) is a
service-layer concern (Stage 5): it calls this predicate at every point a flexible
instance is about to (re-)enter the `pending` pool, so a task is never handed to
`schedule_pending_flexible_tasks` with an already-inverted `[now, deadline]` window.
"""

from __future__ import annotations

from datetime import datetime


def is_deadline_elapsed(deadline: datetime, now: datetime) -> bool:
    """True once `deadline` has passed (inclusive of the exact instant)."""
    return deadline <= now
