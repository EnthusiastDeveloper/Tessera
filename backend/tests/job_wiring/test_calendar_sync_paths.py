"""Job-wiring tests for the calendar-sync mutation paths: does connect schedule the poll
interval job, and does disconnect cancel it? See architecture-plan §4.1.
"""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

import app.calendar_sync.service as calendar_sync_service
from app.calendar_sync.service import build_authorize_url, complete_oauth_callback, disconnect
from app.core.config import Settings
from app.db.base import utcnow
from app.db.schemas import UserSettings
from app.jobs.interface import calendar_poll_job_key
from tests.fixtures.calendar_providers import MockCalendarProvider
from tests.fixtures.jobs import RecordingJobScheduler

_APP_SETTINGS = Settings(
    secret_key="test-secret-key-not-for-production-use", google_client_id="id", google_client_secret="secret"
)  # type: ignore[call-arg]


def _install_mock_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(calendar_sync_service, "get_provider_client", lambda _provider, *, settings: MockCalendarProvider())


class TestConnectSchedulesThePollJob:
    def test_callback_schedules_an_interval_job_at_the_requested_cadence(
        self, db_session: Session, settings: UserSettings, jobs: RecordingJobScheduler, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _install_mock_provider(monkeypatch)
        result = build_authorize_url(
            provider="google",
            session_id="sess-1",
            redirect_uri="http://localhost:8000/api/v1/calendar-connections/google/callback",
            refresh_interval_minutes=30,
            app_settings=_APP_SETTINGS,
        )

        connection = complete_oauth_callback(
            db_session,
            jobs,
            provider="google",
            code="code",
            state=result.state,
            session_id="sess-1",
            redirect_uri="http://localhost:8000/api/v1/calendar-connections/google/callback",
            app_settings=_APP_SETTINGS,
            now=utcnow(),
        )
        db_session.commit()

        assert (calendar_poll_job_key(connection.id), 30) in jobs.intervals


class TestDisconnectCancelsThePollJob:
    def test_disconnect_cancels_the_poll_job(
        self, db_session: Session, settings: UserSettings, jobs: RecordingJobScheduler, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _install_mock_provider(monkeypatch)
        result = build_authorize_url(
            provider="google",
            session_id="sess-1",
            redirect_uri="http://localhost:8000/api/v1/calendar-connections/google/callback",
            refresh_interval_minutes=15,
            app_settings=_APP_SETTINGS,
        )
        connection = complete_oauth_callback(
            db_session,
            jobs,
            provider="google",
            code="code",
            state=result.state,
            session_id="sess-1",
            redirect_uri="http://localhost:8000/api/v1/calendar-connections/google/callback",
            app_settings=_APP_SETTINGS,
            now=utcnow(),
        )
        db_session.commit()

        disconnect(db_session, jobs, connection.id)
        db_session.commit()

        assert calendar_poll_job_key(connection.id) in jobs.cancelled
