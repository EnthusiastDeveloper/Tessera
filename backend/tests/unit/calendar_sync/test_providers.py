"""Unit tests for the Google/Outlook event-parsing logic - pure functions, no real HTTP.
See design doc §7 (`is_all_day`/`is_transparent` filter inputs).
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

import httpx
import pytest

from app.calendar_sync.providers import base, google, outlook
from app.calendar_sync.providers.base import ProviderError, parse_token_response


class TestGoogleEventParsing:
    def test_timed_opaque_event(self) -> None:
        event = google._parse_event(
            {
                "id": "evt-1",
                "summary": "Dentist",
                "start": {"dateTime": "2026-03-03T18:00:00-05:00"},
                "end": {"dateTime": "2026-03-03T19:00:00-05:00"},
            }
        )
        assert event.provider_event_id == "evt-1"
        assert event.title == "Dentist"
        assert event.is_all_day is False
        assert event.is_transparent is False

    def test_transparent_event(self) -> None:
        event = google._parse_event(
            {
                "id": "evt-2",
                "summary": "Focus time (free)",
                "start": {"dateTime": "2026-03-03T18:00:00-05:00"},
                "end": {"dateTime": "2026-03-03T19:00:00-05:00"},
                "transparency": "transparent",
            }
        )
        assert event.is_transparent is True

    def test_all_day_event(self) -> None:
        event = google._parse_event(
            {"id": "evt-3", "summary": "Company holiday", "start": {"date": "2026-03-03"}, "end": {"date": "2026-03-04"}}
        )
        assert event.is_all_day is True
        assert event.start == datetime(2026, 3, 3, tzinfo=UTC)

    def test_missing_summary_falls_back_to_untitled(self) -> None:
        event = google._parse_event(
            {"id": "evt-4", "start": {"dateTime": "2026-03-03T18:00:00Z"}, "end": {"dateTime": "2026-03-03T19:00:00Z"}}
        )
        assert event.title == "(untitled)"


class TestSharedTokenResponseParsing:
    """Both providers' token endpoints share the same response shape - see
    `app.calendar_sync.providers.base.parse_token_response`.
    """

    def test_error_response_raises_provider_error(self) -> None:
        response = httpx.Response(401, json={"error": "invalid_grant"}, request=httpx.Request("POST", "https://x"))
        with pytest.raises(ProviderError):
            parse_token_response(response, provider_label="Google")

    def test_success_response_is_parsed(self) -> None:
        response = httpx.Response(
            200,
            json={"access_token": "abc", "refresh_token": "def", "expires_in": 3600},
            request=httpx.Request("POST", "https://x"),
        )
        tokens = parse_token_response(response, provider_label="Google")
        assert tokens.access_token == "abc"
        assert tokens.refresh_token == "def"

    def test_missing_refresh_token_falls_back_to_the_existing_one(self) -> None:
        response = httpx.Response(
            200, json={"access_token": "abc", "expires_in": 3600}, request=httpx.Request("POST", "https://x")
        )
        tokens = parse_token_response(response, provider_label="Microsoft", fallback_refresh_token="still-valid")
        assert tokens.refresh_token == "still-valid"


class TestOutlookEventParsing:
    def test_timed_busy_event(self) -> None:
        event = outlook._parse_event(
            {
                "id": "evt-1",
                "subject": "1:1",
                "start": {"dateTime": "2026-03-03T18:00:00.0000000", "timeZone": "UTC"},
                "end": {"dateTime": "2026-03-03T19:00:00.0000000", "timeZone": "UTC"},
                "isAllDay": False,
                "showAs": "busy",
            }
        )
        assert event.provider_event_id == "evt-1"
        assert event.title == "1:1"
        assert event.is_all_day is False
        assert event.is_transparent is False

    def test_free_event_is_transparent(self) -> None:
        event = outlook._parse_event(
            {
                "id": "evt-2",
                "subject": "Optional sync",
                "start": {"dateTime": "2026-03-03T18:00:00.0000000", "timeZone": "UTC"},
                "end": {"dateTime": "2026-03-03T19:00:00.0000000", "timeZone": "UTC"},
                "isAllDay": False,
                "showAs": "free",
            }
        )
        assert event.is_transparent is True

    def test_all_day_flag_is_respected(self) -> None:
        event = outlook._parse_event(
            {
                "id": "evt-3",
                "subject": "Holiday",
                "start": {"dateTime": "2026-03-03T00:00:00.0000000", "timeZone": "UTC"},
                "end": {"dateTime": "2026-03-04T00:00:00.0000000", "timeZone": "UTC"},
                "isAllDay": True,
                "showAs": "free",
            }
        )
        assert event.is_all_day is True

    def test_excess_fractional_seconds_are_trimmed(self) -> None:
        """Graph can return 7-digit fractional seconds; `datetime.fromisoformat` only
        accepts up to 6 - this must not raise."""
        parsed = outlook._parse_graph_datetime("2026-03-03T18:00:00.1234567")
        assert parsed.year == 2026

    def test_missing_subject_falls_back_to_untitled(self) -> None:
        event = outlook._parse_event(
            {
                "id": "evt-4",
                "start": {"dateTime": "2026-03-03T18:00:00.0000000", "timeZone": "UTC"},
                "end": {"dateTime": "2026-03-03T19:00:00.0000000", "timeZone": "UTC"},
                "isAllDay": False,
            }
        )
        assert event.title == "(untitled)"


class TestSendWithRetry:
    """Issue #26: a transient provider failure is retried a couple of times before the
    poll gives up and waits for its next interval.
    """

    @pytest.fixture(autouse=True)
    def _no_real_waits(self, monkeypatch: pytest.MonkeyPatch) -> list[float]:
        waits: list[float] = []
        monkeypatch.setattr(base, "_sleep", waits.append)
        return waits

    @staticmethod
    def _responses(*items: httpx.Response | Exception) -> tuple[list[int], Callable[[], httpx.Response]]:
        calls: list[int] = []
        queue = list(items)

        def send() -> httpx.Response:
            calls.append(1)
            item = queue.pop(0)
            if isinstance(item, Exception):
                raise item
            return item

        return calls, send

    def test_a_success_is_returned_without_retrying(self) -> None:
        calls, send = self._responses(httpx.Response(200))
        assert base.send_with_retry(send, provider_label="Test").status_code == 200
        assert len(calls) == 1

    def test_a_transient_5xx_is_retried_until_it_succeeds(self, _no_real_waits: list[float]) -> None:
        calls, send = self._responses(httpx.Response(503), httpx.Response(200))
        assert base.send_with_retry(send, provider_label="Test").status_code == 200
        assert len(calls) == 2
        assert _no_real_waits == [base.RETRY_DELAYS_SECONDS[0]]

    def test_a_network_error_is_retried(self) -> None:
        calls, send = self._responses(httpx.ConnectError("boom"), httpx.Response(200))
        assert base.send_with_retry(send, provider_label="Test").status_code == 200
        assert len(calls) == 2

    def test_a_non_transient_error_is_not_retried(self) -> None:
        calls, send = self._responses(httpx.Response(401))
        assert base.send_with_retry(send, provider_label="Test").status_code == 401
        assert len(calls) == 1

    def test_gives_up_after_three_attempts_and_returns_the_last_response(self) -> None:
        calls, send = self._responses(httpx.Response(503), httpx.Response(502), httpx.Response(500))
        assert base.send_with_retry(send, provider_label="Test").status_code == 500
        assert len(calls) == 3

    def test_a_persistent_network_error_becomes_a_provider_error(self) -> None:
        calls, send = self._responses(httpx.ConnectError("a"), httpx.ConnectError("b"), httpx.ConnectError("c"))
        with pytest.raises(ProviderError):
            base.send_with_retry(send, provider_label="Test")
        assert len(calls) == 3

    def test_fetch_events_retries_through_the_real_client(self, monkeypatch: pytest.MonkeyPatch) -> None:
        responses = [httpx.Response(503), httpx.Response(200, json={"items": []})]
        monkeypatch.setattr(httpx, "get", lambda *args, **kwargs: responses.pop(0))
        client = google.GoogleCalendarProvider(client_id="id", client_secret="secret")

        events = client.fetch_events(
            access_token="token", horizon_start=datetime(2026, 3, 1, tzinfo=UTC), horizon_end=datetime(2026, 6, 1, tzinfo=UTC)
        )
        assert events == ()
        assert responses == []
