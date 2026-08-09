"""Design doc §10 Worked Example C, full version - "Sync evicts a scheduled flexible
task" (§6.4), now genuinely end-to-end through `app.calendar_sync.service.sync_connection`
with a mocked provider, rather than a bare obstacle-list fixture at the engine layer.

Starting state is Example B's own stated outcome (§10: "Starting state: Example B's
outcome...") - constructed directly rather than re-derived through the full creation
pipeline, exactly as the example's own "Given" table frames it.
"""

from __future__ import annotations

from zoneinfo import ZoneInfo

import pytest
from sqlalchemy.orm import Session

import app.calendar_sync.service as calendar_sync_service
from app.calendar_sync.providers.base import ProviderEvent
from app.calendar_sync.service import sync_connection
from app.calendar_sync.token_crypto import encrypt
from app.core.config import Settings
from app.db.base import generate_id, utcnow
from app.db.repositories import (
    ExternalCalendarConnectionRepository,
    OAuthTokenRepository,
    TaskInstanceRepository,
    TaskTemplateRepository,
    UserSettingsRepository,
)
from app.db.schemas import (
    ActiveHoursWindow,
    ExternalCalendarConnection,
    Recurrence,
    StatusHistoryEntry,
    TaskInstance,
    TaskTemplate,
    UserSettings,
)
from tests.fixtures.calendar_providers import MockCalendarProvider
from tests.fixtures.db_entities import make_oauth_token
from tests.fixtures.jobs import RecordingJobScheduler
from tests.fixtures.scheduling import ny

NY = ZoneInfo("America/New_York")
SECRET_KEY = "test-secret-key-not-for-production-use"
_DAY_NAMES = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")


def test_example_c_sync_eviction_and_replacement(
    db_session: Session, settings: UserSettings, jobs: RecordingJobScheduler, monkeypatch: pytest.MonkeyPatch
) -> None:
    # --- Settings, matching Example B's "Given" table exactly (§10). ---
    settings = UserSettingsRepository(db_session).update(
        settings.model_copy(
            update={
                "timezone": "America/New_York",
                "active_hours": dict.fromkeys(_DAY_NAMES, ActiveHoursWindow(start="18:00", end="21:00")),
                "daily_time_budget_minutes": dict.fromkeys(_DAY_NAMES, None),
                "budget_enforcement": "soft",
            }
        )
    )
    db_session.commit()

    # --- Starting state: Example B's outcome. ---
    now = utcnow()
    template = TaskTemplateRepository(db_session).create(
        TaskTemplate(
            id=generate_id(),
            name="Replace HVAC filters",
            type="flexible",
            recurrence=Recurrence(pattern="monthly", interval=1, anchor="completion"),
            priority="medium",
            estimated_duration_minutes=30,
            deadline_offset_minutes=7200,
            active_hours_override={"tuesday": ActiveHoursWindow(start="18:00", end="22:30")},
            created_at=now,
            updated_at=now,
            version=1,
        )
    )
    instance = TaskInstanceRepository(db_session).create(
        TaskInstance(
            id=generate_id(),
            template_id=template.id,
            name=template.name,
            type="flexible",
            priority=2,
            estimated_duration_minutes=30,
            status="scheduled",
            scheduled_time=ny(2026, 3, 3, 21, 45),
            deadline=ny(2026, 3, 7, 9, 0),
            status_history=(StatusHistoryEntry(status="scheduled", at=now),),
            generated_at=now,
            created_at=now,
            updated_at=now,
            version=1,
        )
    )
    db_session.commit()

    # --- Connection + token, so the poll has real (encrypted) credentials to decrypt. ---
    token = OAuthTokenRepository(db_session).create(
        make_oauth_token(
            encrypted_access_token=encrypt("access-token", secret_key=SECRET_KEY),
            encrypted_refresh_token=encrypt("refresh-token", secret_key=SECRET_KEY),
            access_token_expires_at=now.replace(year=now.year + 1),
        )
    )
    connection = ExternalCalendarConnectionRepository(db_session).create(
        ExternalCalendarConnection(
            id=generate_id(), provider="google", oauth_credentials_ref=token.id, refresh_interval_minutes=15, enabled=True
        )
    )
    db_session.commit()

    # --- New poll result: "Concert", Tue 2026-03-03 21:00-23:00, opaque (§10 Example C). ---
    provider = MockCalendarProvider(
        events=(
            ProviderEvent(
                provider_event_id="concert",
                start=ny(2026, 3, 3, 21, 0),
                end=ny(2026, 3, 3, 23, 0),
                title="Concert",
                is_all_day=False,
                is_transparent=False,
            ),
        )
    )

    poll_now = ny(2026, 3, 3, 21, 0)  # the moment the collision is detected
    app_settings = Settings(secret_key=SECRET_KEY, google_client_id="id", google_client_secret="secret")  # type: ignore[call-arg]
    monkeypatch.setattr(calendar_sync_service, "get_provider_client", lambda _provider, *, settings: provider)

    sync_connection(db_session, jobs, connection=connection, app_settings=app_settings, now=poll_now)
    db_session.commit()

    # --- Expected (§10 Example C): re-placed Wed 2026-03-04 18:00. ---
    refreshed = TaskInstanceRepository(db_session).get(instance.id)
    assert refreshed is not None
    assert refreshed.status == "scheduled"
    assert refreshed.scheduled_time is not None
    placed = refreshed.scheduled_time.astimezone(NY)
    assert (placed.year, placed.month, placed.day, placed.hour, placed.minute) == (2026, 3, 4, 18, 0)
