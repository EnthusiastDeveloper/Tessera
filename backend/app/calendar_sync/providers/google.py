"""Google Calendar provider client. See design doc §7, architecture-plan §6.

Real HTTP calls against Google's OAuth2 and Calendar v3 APIs - never exercised in CI
(implementation-plan §7: "OAuth flow against a mocked provider, never a real one in CI").
Manual smoke-testing against a real account is this stage's own exit criterion.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import httpx

from app.calendar_sync.providers.base import CalendarProviderClient, ProviderError, ProviderEvent, ProviderTokenSet

AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
EVENTS_URL = "https://www.googleapis.com/calendar/v3/calendars/primary/events"
SCOPE = "https://www.googleapis.com/auth/calendar.readonly"


class GoogleCalendarProvider(CalendarProviderClient):
    def __init__(self, *, client_id: str, client_secret: str) -> None:
        self._client_id = client_id
        self._client_secret = client_secret

    def build_authorize_url(self, *, state: str, redirect_uri: str) -> str:
        params = {
            "client_id": self._client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": SCOPE,
            "access_type": "offline",  # required to receive a refresh_token
            "prompt": "consent",  # forces a refresh_token on every connect, not just the first
            "state": state,
        }
        return str(httpx.URL(AUTHORIZE_URL, params=params))

    def exchange_code(self, *, code: str, redirect_uri: str) -> ProviderTokenSet:
        response = httpx.post(
            TOKEN_URL,
            data={
                "code": code,
                "client_id": self._client_id,
                "client_secret": self._client_secret,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            },
        )
        return _parse_token_response(response)

    def refresh_access_token(self, *, refresh_token: str) -> ProviderTokenSet:
        response = httpx.post(
            TOKEN_URL,
            data={
                "refresh_token": refresh_token,
                "client_id": self._client_id,
                "client_secret": self._client_secret,
                "grant_type": "refresh_token",
            },
        )
        return _parse_token_response(response, fallback_refresh_token=refresh_token)

    def fetch_events(self, *, access_token: str, horizon_start: datetime, horizon_end: datetime) -> tuple[ProviderEvent, ...]:
        response = httpx.get(
            EVENTS_URL,
            headers={"Authorization": f"Bearer {access_token}"},
            params={
                "timeMin": horizon_start.astimezone(UTC).isoformat(),
                "timeMax": horizon_end.astimezone(UTC).isoformat(),
                "singleEvents": "true",  # expand recurring events into individual instances
                "maxResults": "2500",
            },
        )
        if response.is_error:
            raise ProviderError(f"Google Calendar events fetch failed: {response.status_code} {response.text}")
        body = response.json()
        return tuple(_parse_event(item) for item in body.get("items", []) if "start" in item and "end" in item)


def _parse_token_response(response: httpx.Response, *, fallback_refresh_token: str | None = None) -> ProviderTokenSet:
    if response.is_error:
        raise ProviderError(f"Google OAuth token request failed: {response.status_code} {response.text}")
    body = response.json()
    expires_in = int(body.get("expires_in", 3600))
    return ProviderTokenSet(
        access_token=body["access_token"],
        refresh_token=body.get("refresh_token", fallback_refresh_token),
        expires_at=datetime.now(UTC) + timedelta(seconds=expires_in),
    )


def _parse_event(item: dict[str, object]) -> ProviderEvent:
    start_field = item["start"]
    end_field = item["end"]
    assert isinstance(start_field, dict) and isinstance(end_field, dict)
    is_all_day = "date" in start_field
    start = _parse_date_or_datetime(start_field)
    end = _parse_date_or_datetime(end_field)
    return ProviderEvent(
        provider_event_id=str(item["id"]),
        start=start,
        end=end,
        title=str(item.get("summary", "(untitled)")),
        is_all_day=is_all_day,
        # Google omits `transparency` entirely for the default "opaque" (busy) case.
        is_transparent=item.get("transparency") == "transparent",
    )


def _parse_date_or_datetime(field: dict[str, object]) -> datetime:
    if "dateTime" in field:
        return datetime.fromisoformat(str(field["dateTime"]))
    return datetime.combine(date.fromisoformat(str(field["date"])), datetime.min.time(), tzinfo=UTC)


__all__ = ["GoogleCalendarProvider"]
