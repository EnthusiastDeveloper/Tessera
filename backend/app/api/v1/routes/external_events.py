"""External event endpoints: read-only cached `ExternalEvent` rows for Timeline display.
See design doc §3.11, §3.12 (retention), §7 (filtering), §8.1 screen 2; architecture-plan §3.

**Added Stage 9d - a previously-unbuilt gap.** `ExternalEventRepository` has existed since
Stage 7 and the scheduler has read the cache internally since then
(`app.scheduling.adapter.gather_external_obstacles`), but no route ever exposed these rows
to a client. The Timeline's "external busy-blocks" requirement (§8.1 screen 2) needs one -
same category of gap as prior stages' own findings (Stage 8/9a/9c).

A separate top-level resource, not nested under `/calendar-connections` - `ExternalEvent`
is its own aggregate (§3.11) spanning every connection, mirroring how `/task-instances` is
not nested under `/task-templates` despite the same one-to-many relationship shape.
"""

from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy.orm import Session

from app.api.dependencies import DB_SESSION
from app.calendar_sync import service
from app.db.schemas import ExternalEvent

router = APIRouter(prefix="/api/v1/external-events", tags=["external-events"])


@router.get("")
def list_external_events_endpoint(db: Session = DB_SESSION) -> list[ExternalEvent]:
    """No query params - the cache already self-limits to a 90-day-forward/30-day-past
    rolling window per §3.12 retention, so there is no unbounded-result concern to filter
    away.
    """
    return list(service.list_display_events(db))
