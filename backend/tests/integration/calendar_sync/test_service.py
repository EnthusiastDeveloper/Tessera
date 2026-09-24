"""Integration tests for `app.calendar_sync.service.sync_connection` - the §6.4 poll:
fetch, diff/upsert, retention, collision handling (both branches), and `sync_conflict`
auto-resolution (§3.9).
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy.orm import Session, sessionmaker

import app.calendar_sync.service as calendar_sync_service
from app.calendar_sync.providers.base import ProviderError, ProviderEvent
from app.calendar_sync.service import CalendarSyncError, sync_connection
from app.calendar_sync.token_crypto import encrypt
from app.core.config import Settings
from app.db.base import Base, generate_id, utcnow
from app.db.repositories import (
    ExternalCalendarConnectionRepository,
    ExternalEventRepository,
    NotificationRepository,
    OAuthTokenRepository,
    TaskInstanceRepository,
    TaskTemplateRepository,
)
from app.db.schemas import ExternalCalendarConnection, Recurrence, StatusHistoryEntry, TaskInstance, TaskTemplate, UserSettings
from app.db.session import build_engine
from tests.fixtures.calendar_providers import MockCalendarProvider
from tests.fixtures.db_entities import make_external_calendar_connection, make_external_event, make_oauth_token
from tests.fixtures.jobs import RecordingJobScheduler

SECRET_KEY = "test-secret-key-not-for-production-use"


def _app_settings(**overrides: object) -> Settings:
    defaults: dict[str, object] = {"secret_key": SECRET_KEY, "google_client_id": "id", "google_client_secret": "secret"}
    defaults.update(overrides)
    return Settings(**defaults)  # type: ignore[arg-type]


def _persist_connection(db: Session, *, refresh_interval_minutes: int = 15) -> ExternalCalendarConnection:
    token = OAuthTokenRepository(db).create(
        make_oauth_token(
            encrypted_access_token=encrypt("access-token", secret_key=SECRET_KEY),
            encrypted_refresh_token=encrypt("refresh-token", secret_key=SECRET_KEY),
            access_token_expires_at=utcnow() + timedelta(hours=1),
        )
    )
    connection = ExternalCalendarConnectionRepository(db).create(
        ExternalCalendarConnection(
            id=generate_id(),
            provider="google",
            oauth_credentials_ref=token.id,
            refresh_interval_minutes=refresh_interval_minutes,
            enabled=True,
        )
    )
    db.commit()
    return connection


def _persist_fixed_instance(db: Session, *, scheduled_time: object, **overrides: object) -> TaskInstance:
    now = utcnow()
    template = TaskTemplateRepository(db).create(
        TaskTemplate(
            id=generate_id(),
            name="Team sync",
            type="fixed",
            fixed_time_of_day="18:00",
            recurrence=Recurrence(pattern="one_time", anchor="calendar"),
            priority="medium",
            estimated_duration_minutes=60,
            created_at=now,
            updated_at=now,
            version=1,
        )
    )
    defaults: dict[str, object] = {
        "id": generate_id(),
        "template_id": template.id,
        "name": template.name,
        "type": "fixed",
        "priority": 2,
        "estimated_duration_minutes": 60,
        "status": "scheduled",
        "scheduled_time": scheduled_time,
        "status_history": (StatusHistoryEntry(status="scheduled", at=now),),
        "generated_at": now,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    defaults.update(overrides)
    return TaskInstanceRepository(db).create(TaskInstance(**defaults))


def _persist_flexible_instance(db: Session, *, scheduled_time: object, deadline: object, **overrides: object) -> TaskInstance:
    now = utcnow()
    template = TaskTemplateRepository(db).create(
        TaskTemplate(
            id=generate_id(),
            name="Deep clean garage",
            type="flexible",
            recurrence=Recurrence(pattern="one_time", anchor="calendar"),
            priority="medium",
            estimated_duration_minutes=60,
            deadline_offset_minutes=60 * 24 * 5,
            created_at=now,
            updated_at=now,
            version=1,
        )
    )
    defaults: dict[str, object] = {
        "id": generate_id(),
        "template_id": template.id,
        "name": template.name,
        "type": "flexible",
        "priority": 2,
        "estimated_duration_minutes": 60,
        "status": "scheduled",
        "scheduled_time": scheduled_time,
        "deadline": deadline,
        "status_history": (StatusHistoryEntry(status="scheduled", at=now),),
        "generated_at": now,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    defaults.update(overrides)
    return TaskInstanceRepository(db).create(TaskInstance(**defaults))


def _install_mock_provider(monkeypatch: pytest.MonkeyPatch, provider: MockCalendarProvider) -> None:
    monkeypatch.setattr(calendar_sync_service, "get_provider_client", lambda _provider, *, settings: provider)


class TestListDisplayEvents:
    """`list_display_events` (added Stage 9d) - the Timeline's external busy-block/overlay
    source (§8.1 screen 2). Deliberately a different filter from
    `app.scheduling.adapter.gather_external_obstacles`: transparent events are excluded
    from display too (a "Free" event was never meant to look busy), but all-day events are
    *kept* for display (§7: "imported and shown on the Timeline ... as display-only
    overlays"), unlike the obstacle set which drops them.
    """

    def test_excludes_transparent_events(self, db_session: Session) -> None:
        connection = _persist_connection(db_session)
        ExternalEventRepository(db_session).upsert(
            make_external_event(connection_id=connection.id, provider_event_id="free", is_transparent=True)
        )
        db_session.commit()

        assert calendar_sync_service.list_display_events(db_session) == ()

    def test_includes_all_day_events_with_the_flag_set(self, db_session: Session) -> None:
        connection = _persist_connection(db_session)
        ExternalEventRepository(db_session).upsert(
            make_external_event(connection_id=connection.id, provider_event_id="conf", is_all_day=True, is_transparent=False)
        )
        db_session.commit()

        events = calendar_sync_service.list_display_events(db_session)
        assert len(events) == 1
        assert events[0].is_all_day is True

    def test_includes_opaque_timed_events(self, db_session: Session) -> None:
        connection = _persist_connection(db_session)
        ExternalEventRepository(db_session).upsert(
            make_external_event(connection_id=connection.id, provider_event_id="dentist", is_all_day=False, is_transparent=False)
        )
        db_session.commit()

        events = calendar_sync_service.list_display_events(db_session)
        assert len(events) == 1
        assert events[0].is_all_day is False

    def test_excludes_events_from_disabled_connections(self, db_session: Session) -> None:
        disabled = ExternalCalendarConnectionRepository(db_session).create(make_external_calendar_connection(enabled=False))
        db_session.commit()
        ExternalEventRepository(db_session).upsert(make_external_event(connection_id=disabled.id, provider_event_id="evt-1"))
        db_session.commit()

        assert calendar_sync_service.list_display_events(db_session) == ()


class TestFetchDiffAndRetention:
    def test_new_event_is_upserted_and_last_synced_at_is_set(
        self, db_session: Session, settings: UserSettings, jobs: RecordingJobScheduler, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        connection = _persist_connection(db_session)
        now = utcnow()
        provider = MockCalendarProvider(
            events=(
                ProviderEvent(
                    provider_event_id="evt-1",
                    start=now + timedelta(days=1),
                    end=now + timedelta(days=1, hours=1),
                    title="Dentist",
                    is_all_day=False,
                    is_transparent=False,
                ),
            )
        )
        _install_mock_provider(monkeypatch, provider)

        updated = sync_connection(db_session, jobs, connection=connection, app_settings=_app_settings(), now=now)
        db_session.commit()

        assert updated.last_synced_at == now
        stored = ExternalEventRepository(db_session).get_by_provider_event_id(connection.id, "evt-1")
        assert stored is not None
        assert stored.title == "Dentist"

    def test_events_no_longer_returned_are_soft_deleted(
        self, db_session: Session, settings: UserSettings, jobs: RecordingJobScheduler, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        connection = _persist_connection(db_session)
        now = utcnow()
        event = ProviderEvent(
            provider_event_id="evt-1",
            start=now + timedelta(days=1),
            end=now + timedelta(days=1, hours=1),
            title="Dentist",
            is_all_day=False,
            is_transparent=False,
        )
        provider = MockCalendarProvider(events=(event,))
        _install_mock_provider(monkeypatch, provider)
        sync_connection(db_session, jobs, connection=connection, app_settings=_app_settings(), now=now)
        db_session.commit()

        provider.events = ()  # provider no longer returns it - cancelled/deleted upstream
        sync_connection(db_session, jobs, connection=connection, app_settings=_app_settings(), now=now + timedelta(minutes=15))
        db_session.commit()

        assert ExternalEventRepository(db_session).list_active_for_connection(connection.id) == ()
        stored = ExternalEventRepository(db_session).get_by_provider_event_id(connection.id, "evt-1")
        assert stored is not None and stored.deleted_at is not None

    def test_events_past_retention_are_purged(
        self, db_session: Session, settings: UserSettings, jobs: RecordingJobScheduler, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        connection = _persist_connection(db_session)
        now = utcnow()
        # A prior poll cached an event that has since ended more than 30 days ago -
        # simulated directly (bypassing a real historical poll), matching this suite's
        # existing "write inconsistent/aged state directly via repositories" convention.
        ExternalEventRepository(db_session).upsert(
            calendar_sync_service.ExternalEvent(
                id=generate_id(),
                connection_id=connection.id,
                provider_event_id="evt-ancient",
                start=now - timedelta(days=45),
                end=now - timedelta(days=45) + timedelta(hours=1),
                title="Long over",
                fetched_at=now - timedelta(days=45),
            )
        )
        db_session.commit()

        provider = MockCalendarProvider(events=())
        _install_mock_provider(monkeypatch, provider)
        sync_connection(db_session, jobs, connection=connection, app_settings=_app_settings(), now=now)
        db_session.commit()

        assert ExternalEventRepository(db_session).get_by_provider_event_id(connection.id, "evt-ancient") is None


class TestCollisionHandling:
    """Design doc §6.4 step 3."""

    def test_fixed_collision_creates_sync_conflict_notification(
        self, db_session: Session, settings: UserSettings, jobs: RecordingJobScheduler, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        connection = _persist_connection(db_session)
        now = utcnow()
        instance = _persist_fixed_instance(db_session, scheduled_time=now + timedelta(days=1))
        db_session.commit()

        provider = MockCalendarProvider(
            events=(
                ProviderEvent(
                    provider_event_id="evt-collide",
                    start=now + timedelta(days=1, minutes=-15),
                    end=now + timedelta(days=1, minutes=15),
                    title="Surprise meeting",
                    is_all_day=False,
                    is_transparent=False,
                ),
            )
        )
        _install_mock_provider(monkeypatch, provider)

        sync_connection(db_session, jobs, connection=connection, app_settings=_app_settings(), now=now)
        db_session.commit()

        notifications = NotificationRepository(db_session).list_for_instance(instance.id)
        sync_conflicts = [n for n in notifications if n.type == "sync_conflict"]
        assert len(sync_conflicts) == 1
        refreshed = TaskInstanceRepository(db_session).get(instance.id)
        assert refreshed is not None and refreshed.status == "scheduled"  # never auto-moved

    def test_repeated_poll_does_not_duplicate_the_sync_conflict_notification(
        self, db_session: Session, settings: UserSettings, jobs: RecordingJobScheduler, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        connection = _persist_connection(db_session)
        now = utcnow()
        instance = _persist_fixed_instance(db_session, scheduled_time=now + timedelta(days=1))
        db_session.commit()
        event = ProviderEvent(
            provider_event_id="evt-collide",
            start=now + timedelta(days=1, minutes=-15),
            end=now + timedelta(days=1, minutes=15),
            title="Surprise meeting",
            is_all_day=False,
            is_transparent=False,
        )
        provider = MockCalendarProvider(events=(event,))
        _install_mock_provider(monkeypatch, provider)

        sync_connection(db_session, jobs, connection=connection, app_settings=_app_settings(), now=now)
        db_session.commit()
        # Same event, unmoved - a second poll must not re-flag it as "new/moved".
        sync_connection(db_session, jobs, connection=connection, app_settings=_app_settings(), now=now + timedelta(minutes=15))
        db_session.commit()

        sync_conflicts = [
            n for n in NotificationRepository(db_session).list_for_instance(instance.id) if n.type == "sync_conflict"
        ]
        assert len(sync_conflicts) == 1

    def test_flexible_collision_reverts_to_pending_and_is_replaced_elsewhere(
        self, db_session: Session, settings: UserSettings, jobs: RecordingJobScheduler, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        connection = _persist_connection(db_session)
        now = utcnow()
        original_time = now + timedelta(days=1)
        instance = _persist_flexible_instance(db_session, scheduled_time=original_time, deadline=now + timedelta(days=10))
        db_session.commit()

        provider = MockCalendarProvider(
            events=(
                ProviderEvent(
                    provider_event_id="evt-collide",
                    start=original_time - timedelta(minutes=15),
                    end=original_time + timedelta(minutes=75),
                    title="Concert",
                    is_all_day=False,
                    is_transparent=False,
                ),
            )
        )
        _install_mock_provider(monkeypatch, provider)

        sync_connection(db_session, jobs, connection=connection, app_settings=_app_settings(), now=now)
        db_session.commit()

        refreshed = TaskInstanceRepository(db_session).get(instance.id)
        assert refreshed is not None
        # §6.7's gate lets it place_or_defer immediately - not still pending at the exact
        # original slot, and never left "scheduled" at the now-colliding time.
        assert refreshed.scheduled_time != original_time
        assert refreshed.status in ("scheduled", "pending")

    def test_transparent_event_never_triggers_a_collision(
        self, db_session: Session, settings: UserSettings, jobs: RecordingJobScheduler, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        connection = _persist_connection(db_session)
        now = utcnow()
        instance = _persist_fixed_instance(db_session, scheduled_time=now + timedelta(days=1))
        db_session.commit()

        provider = MockCalendarProvider(
            events=(
                ProviderEvent(
                    provider_event_id="evt-free",
                    start=now + timedelta(days=1, minutes=-15),
                    end=now + timedelta(days=1, minutes=15),
                    title="Optional",
                    is_all_day=False,
                    is_transparent=True,
                ),
            )
        )
        _install_mock_provider(monkeypatch, provider)

        sync_connection(db_session, jobs, connection=connection, app_settings=_app_settings(), now=now)
        db_session.commit()

        assert NotificationRepository(db_session).list_for_instance(instance.id) == ()

    def test_all_day_event_never_triggers_a_collision(
        self, db_session: Session, settings: UserSettings, jobs: RecordingJobScheduler, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        connection = _persist_connection(db_session)
        now = utcnow()
        instance = _persist_fixed_instance(db_session, scheduled_time=now + timedelta(days=1))
        db_session.commit()

        provider = MockCalendarProvider(
            events=(
                ProviderEvent(
                    provider_event_id="evt-holiday",
                    start=now,
                    end=now + timedelta(days=2),
                    title="Holiday",
                    is_all_day=True,
                    is_transparent=False,
                ),
            )
        )
        _install_mock_provider(monkeypatch, provider)

        sync_connection(db_session, jobs, connection=connection, app_settings=_app_settings(), now=now)
        db_session.commit()

        assert NotificationRepository(db_session).list_for_instance(instance.id) == ()

    def test_sync_conflict_auto_resolves_once_the_event_moves_away(
        self, db_session: Session, settings: UserSettings, jobs: RecordingJobScheduler, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """§3.9: "the external event was later removed/moved" self-resolution."""
        connection = _persist_connection(db_session)
        now = utcnow()
        scheduled_time = now + timedelta(days=1)
        instance = _persist_fixed_instance(db_session, scheduled_time=scheduled_time)
        db_session.commit()

        provider = MockCalendarProvider(
            events=(
                ProviderEvent(
                    provider_event_id="evt-collide",
                    start=scheduled_time - timedelta(minutes=15),
                    end=scheduled_time + timedelta(minutes=15),
                    title="Meeting",
                    is_all_day=False,
                    is_transparent=False,
                ),
            )
        )
        _install_mock_provider(monkeypatch, provider)
        sync_connection(db_session, jobs, connection=connection, app_settings=_app_settings(), now=now)
        db_session.commit()
        assert any(
            n.type == "sync_conflict" and n.resolved_at is None
            for n in NotificationRepository(db_session).list_for_instance(instance.id)
        )

        # The event moves well clear of the instance's slot on the next poll.
        provider.events = (
            ProviderEvent(
                provider_event_id="evt-collide",
                start=scheduled_time + timedelta(days=3),
                end=scheduled_time + timedelta(days=3, hours=1),
                title="Meeting",
                is_all_day=False,
                is_transparent=False,
            ),
        )
        sync_connection(db_session, jobs, connection=connection, app_settings=_app_settings(), now=now + timedelta(minutes=15))
        db_session.commit()

        notifications = NotificationRepository(db_session).list_for_instance(instance.id)
        sync_conflicts = [n for n in notifications if n.type == "sync_conflict"]
        assert len(sync_conflicts) == 1
        assert sync_conflicts[0].resolved_at is not None

    def test_in_progress_fixed_instance_is_never_flagged(
        self, db_session: Session, settings: UserSettings, jobs: RecordingJobScheduler, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """§6.4 step 3 scopes collision eviction to a `scheduled` instance, not
        `in_progress` - regression test for a bug where `_handle_collision` created a
        `sync_conflict` for an `in_progress` instance and `resolve_cleared_sync_conflicts`
        then immediately auto-resolved it in the same `sync_connection` call, since the
        resolution check originally treated any non-`scheduled` status as "cleared".
        """
        connection = _persist_connection(db_session)
        now = utcnow()
        instance = _persist_fixed_instance(db_session, scheduled_time=now + timedelta(days=1), status="in_progress")
        db_session.commit()

        provider = MockCalendarProvider(
            events=(
                ProviderEvent(
                    provider_event_id="evt-collide",
                    start=now + timedelta(days=1, minutes=-15),
                    end=now + timedelta(days=1, minutes=15),
                    title="Surprise meeting",
                    is_all_day=False,
                    is_transparent=False,
                ),
            )
        )
        _install_mock_provider(monkeypatch, provider)

        sync_connection(db_session, jobs, connection=connection, app_settings=_app_settings(), now=now)
        db_session.commit()

        assert NotificationRepository(db_session).list_for_instance(instance.id) == ()

    def test_in_progress_flexible_instance_is_never_evicted(
        self, db_session: Session, settings: UserSettings, jobs: RecordingJobScheduler, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Same regression as above, flexible branch: an `in_progress` task must not be
        yanked off the timeline mid-work by a sync collision.
        """
        connection = _persist_connection(db_session)
        now = utcnow()
        scheduled_time = now + timedelta(days=1)
        instance = _persist_flexible_instance(
            db_session, scheduled_time=scheduled_time, deadline=now + timedelta(days=10), status="in_progress"
        )
        db_session.commit()

        provider = MockCalendarProvider(
            events=(
                ProviderEvent(
                    provider_event_id="evt-collide",
                    start=scheduled_time - timedelta(minutes=15),
                    end=scheduled_time + timedelta(minutes=75),
                    title="Concert",
                    is_all_day=False,
                    is_transparent=False,
                ),
            )
        )
        _install_mock_provider(monkeypatch, provider)

        sync_connection(db_session, jobs, connection=connection, app_settings=_app_settings(), now=now)
        db_session.commit()

        refreshed = TaskInstanceRepository(db_session).get(instance.id)
        assert refreshed is not None
        assert refreshed.status == "in_progress"
        assert refreshed.scheduled_time == scheduled_time

    def test_a_still_active_sync_conflict_on_an_in_progress_instance_is_not_auto_resolved(
        self, db_session: Session, settings: UserSettings, jobs: RecordingJobScheduler, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`resolve_cleared_sync_conflicts` must keep checking overlap for an `in_progress`
        instance rather than treating "not scheduled" as "resolved" - the instance still
        occupies `scheduled_time` and the underlying collision may still be real.
        """
        connection = _persist_connection(db_session)
        now = utcnow()
        scheduled_time = now + timedelta(days=1)
        instance = _persist_fixed_instance(db_session, scheduled_time=scheduled_time, status="scheduled")
        db_session.commit()

        colliding_event = ProviderEvent(
            provider_event_id="evt-collide",
            start=scheduled_time - timedelta(minutes=15),
            end=scheduled_time + timedelta(minutes=15),
            title="Meeting",
            is_all_day=False,
            is_transparent=False,
        )
        provider = MockCalendarProvider(events=(colliding_event,))
        _install_mock_provider(monkeypatch, provider)
        sync_connection(db_session, jobs, connection=connection, app_settings=_app_settings(), now=now)
        db_session.commit()
        assert any(
            n.type == "sync_conflict" and n.resolved_at is None
            for n in NotificationRepository(db_session).list_for_instance(instance.id)
        )

        # The user starts working on it - the external event has not moved or been removed.
        started = TaskInstanceRepository(db_session).update(instance.model_copy(update={"status": "in_progress"}))
        db_session.commit()
        assert started.status == "in_progress"

        # A later poll with the same still-colliding event must not silently clear the notification.
        sync_connection(db_session, jobs, connection=connection, app_settings=_app_settings(), now=now + timedelta(minutes=15))
        db_session.commit()

        notifications = NotificationRepository(db_session).list_for_instance(instance.id)
        assert any(n.type == "sync_conflict" and n.resolved_at is None for n in notifications)

    def test_transparency_flip_at_the_same_time_still_triggers_collision_handling(
        self, db_session: Session, settings: UserSettings, jobs: RecordingJobScheduler, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Regression test: an event whose `start`/`end` never change but flips from
        transparent ("Free") to opaque must still be treated as "moved" for §6.4's
        new/moved collision trigger - otherwise it silently becomes a real obstacle
        without ever being checked against live instances.
        """
        connection = _persist_connection(db_session)
        now = utcnow()
        instance = _persist_fixed_instance(db_session, scheduled_time=now + timedelta(days=1))
        db_session.commit()
        event_start = now + timedelta(days=1, minutes=-15)
        event_end = now + timedelta(days=1, minutes=15)

        provider = MockCalendarProvider(
            events=(
                ProviderEvent(
                    provider_event_id="evt-1",
                    start=event_start,
                    end=event_end,
                    title="Optional",
                    is_all_day=False,
                    is_transparent=True,
                ),
            )
        )
        _install_mock_provider(monkeypatch, provider)
        sync_connection(db_session, jobs, connection=connection, app_settings=_app_settings(), now=now)
        db_session.commit()
        assert NotificationRepository(db_session).list_for_instance(instance.id) == ()

        # Same time window, now marked busy - the organizer flipped it without moving it.
        provider.events = (
            ProviderEvent(
                provider_event_id="evt-1",
                start=event_start,
                end=event_end,
                title="Optional",
                is_all_day=False,
                is_transparent=False,
            ),
        )
        sync_connection(db_session, jobs, connection=connection, app_settings=_app_settings(), now=now + timedelta(minutes=15))
        db_session.commit()

        assert any(n.type == "sync_conflict" for n in NotificationRepository(db_session).list_for_instance(instance.id))

    def test_disconnect_deletes_before_cancelling_the_job(
        self, db_session: Session, settings: UserSettings, jobs: RecordingJobScheduler, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Regression test: the connection row must already be gone from the DB at the
        moment the poll job is cancelled - not the other way around - so a failure between
        the two steps never leaves an enabled, still-listed connection with no poll job.
        """
        connection = _persist_connection(db_session)

        class _OrderCheckingScheduler(RecordingJobScheduler):
            def cancel(self, *, job_key: str) -> None:
                assert ExternalCalendarConnectionRepository(db_session).get(connection.id) is None
                super().cancel(job_key=job_key)

        from app.calendar_sync.service import disconnect

        disconnect(db_session, _OrderCheckingScheduler(), connection.id)
        db_session.commit()


class TestTokenLifecycle:
    def test_refreshes_an_expired_access_token(
        self, db_session: Session, settings: UserSettings, jobs: RecordingJobScheduler, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        token = OAuthTokenRepository(db_session).create(
            make_oauth_token(
                encrypted_access_token=encrypt("stale-access-token", secret_key=SECRET_KEY),
                encrypted_refresh_token=encrypt("refresh-token", secret_key=SECRET_KEY),
                access_token_expires_at=utcnow() - timedelta(minutes=1),
            )
        )
        connection = ExternalCalendarConnectionRepository(db_session).create(
            ExternalCalendarConnection(
                id=generate_id(), provider="google", oauth_credentials_ref=token.id, refresh_interval_minutes=15, enabled=True
            )
        )
        db_session.commit()

        provider = MockCalendarProvider(access_token="fresh-access-token")
        _install_mock_provider(monkeypatch, provider)

        sync_connection(db_session, jobs, connection=connection, app_settings=_app_settings(), now=utcnow())
        db_session.commit()

        assert provider.refreshed_tokens == ["refresh-token"]
        refreshed_token = OAuthTokenRepository(db_session).get(token.id)
        assert refreshed_token is not None
        assert refreshed_token.access_token_expires_at > utcnow()

    def test_missing_token_row_raises_calendar_sync_error(
        self, db_session: Session, settings: UserSettings, jobs: RecordingJobScheduler, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        connection = ExternalCalendarConnectionRepository(db_session).create(
            ExternalCalendarConnection(
                id=generate_id(),
                provider="google",
                oauth_credentials_ref="does-not-exist",
                refresh_interval_minutes=15,
                enabled=True,
            )
        )
        db_session.commit()
        _install_mock_provider(monkeypatch, MockCalendarProvider())

        with pytest.raises(CalendarSyncError) as exc_info:
            sync_connection(db_session, jobs, connection=connection, app_settings=_app_settings(), now=utcnow())
        assert exc_info.value.code == "not_found"


def _persist_expired_connection(db: Session) -> tuple[ExternalCalendarConnection, str]:
    token = OAuthTokenRepository(db).create(
        make_oauth_token(
            encrypted_access_token=encrypt("stale-access-token", secret_key=SECRET_KEY),
            encrypted_refresh_token=encrypt("refresh-token", secret_key=SECRET_KEY),
            access_token_expires_at=utcnow() - timedelta(minutes=1),
        )
    )
    connection = ExternalCalendarConnectionRepository(db).create(
        ExternalCalendarConnection(
            id=generate_id(), provider="google", oauth_credentials_ref=token.id, refresh_interval_minutes=15, enabled=True
        )
    )
    db.commit()
    return connection, token.id


class TestRefreshAndFetchOrdering:
    def test_a_failed_fetch_after_a_refresh_keeps_the_refreshed_token(
        self, db_session: Session, settings: UserSettings, jobs: RecordingJobScheduler, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        connection, token_id = _persist_expired_connection(db_session)
        provider = MockCalendarProvider(access_token="fresh-access-token")
        provider.raise_on_fetch = ProviderError("upstream 503")
        _install_mock_provider(monkeypatch, provider)

        result = sync_connection(db_session, jobs, connection=connection, app_settings=_app_settings(), now=utcnow())
        db_session.commit()

        stored = OAuthTokenRepository(db_session).get(token_id)
        assert stored is not None
        assert stored.access_token_expires_at > utcnow(), "a rotated refresh token must not be rolled back"
        assert result.last_synced_at is None, "the poll still failed"

    def test_a_failed_fetch_without_a_refresh_still_raises(
        self, db_session: Session, settings: UserSettings, jobs: RecordingJobScheduler, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        connection = _persist_connection(db_session)
        provider = MockCalendarProvider()
        provider.raise_on_fetch = ProviderError("upstream 503")
        _install_mock_provider(monkeypatch, provider)

        with pytest.raises(CalendarSyncError) as exc_info:
            sync_connection(db_session, jobs, connection=connection, app_settings=_app_settings(), now=utcnow())
        assert exc_info.value.code == "calendar_fetch_failed"

    def test_no_write_lock_is_held_while_events_are_fetched(
        self, tmp_path: Path, jobs: RecordingJobScheduler, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # A real file database: the poll's session and a second connection must contend
        # for SQLite's lock the way two requests would.
        engine = build_engine(f"sqlite:///{tmp_path / 'poll.db'}")
        Base.metadata.create_all(engine)
        session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)()
        connection, _ = _persist_expired_connection(session)
        other_writer_blocked: list[bool] = []

        class _ProbingProvider(MockCalendarProvider):
            def fetch_events(
                self, *, access_token: str, horizon_start: datetime, horizon_end: datetime
            ) -> tuple[ProviderEvent, ...]:
                probe = sqlite3.connect(tmp_path / "poll.db", timeout=0)
                try:
                    probe.execute("UPDATE external_calendar_connections SET enabled = enabled")
                    probe.commit()
                    other_writer_blocked.append(False)
                except sqlite3.OperationalError:
                    other_writer_blocked.append(True)
                finally:
                    probe.close()
                return super().fetch_events(access_token=access_token, horizon_start=horizon_start, horizon_end=horizon_end)

        _install_mock_provider(monkeypatch, _ProbingProvider(access_token="fresh-access-token"))
        try:
            sync_connection(session, jobs, connection=connection, app_settings=_app_settings(), now=utcnow())
            session.commit()
        finally:
            session.close()
            engine.dispose()

        assert other_writer_blocked == [False]
