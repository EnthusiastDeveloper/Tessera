"""Unit tests for the Google/Outlook event-parsing logic - pure functions, no real HTTP.
See design doc §7 (`is_all_day`/`is_transparent` filter inputs).
"""

from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest

from app.calendar_sync.providers import google, outlook
from app.calendar_sync.providers.base import ProviderError


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

    def test_error_response_raises_provider_error(self) -> None:
        response = httpx.Response(401, json={"error": "invalid_grant"}, request=httpx.Request("POST", "https://x"))
        with pytest.raises(ProviderError):
            google._parse_token_response(response)


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
