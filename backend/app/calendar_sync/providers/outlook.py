"""Outlook (Microsoft Graph) provider client. See design doc §7, architecture-plan §6.

Real HTTP calls against the Microsoft identity platform and Graph APIs - never exercised
in CI, same rationale as `google.py`.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime

import httpx

from app.calendar_sync.providers.base import (
    CalendarProviderClient,
    ProviderError,
    ProviderEvent,
    ProviderTokenSet,
    parse_token_response,
)

AUTHORIZE_URL = "https://login.microsoftonline.com/common/oauth2/v2.0/authorize"
TOKEN_URL = "https://login.microsoftonline.com/common/oauth2/v2.0/token"
CALENDAR_VIEW_URL = "https://graph.microsoft.com/v1.0/me/calendarView"
SCOPE = "openid offline_access Calendars.Read"

#: Graph returns fractional seconds with up to 7 digits; `datetime.fromisoformat` only
#: accepts up to 6 - trim rather than reject a well-formed Graph timestamp.
_EXCESS_FRACTION = re.compile(r"(\.\d{6})\d+")


class OutlookCalendarProvider(CalendarProviderClient):
    def __init__(self, *, client_id: str, client_secret: str) -> None:
        self._client_id = client_id
        self._client_secret = client_secret

    def build_authorize_url(self, *, state: str, redirect_uri: str) -> str:
        params = {
            "client_id": self._client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": SCOPE,
            "response_mode": "query",
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
                "scope": SCOPE,
            },
        )
        return parse_token_response(response, provider_label="Microsoft")

    def refresh_access_token(self, *, refresh_token: str) -> ProviderTokenSet:
        response = httpx.post(
            TOKEN_URL,
            data={
                "refresh_token": refresh_token,
                "client_id": self._client_id,
                "client_secret": self._client_secret,
                "grant_type": "refresh_token",
                "scope": SCOPE,
            },
        )
        return parse_token_response(response, provider_label="Microsoft", fallback_refresh_token=refresh_token)

    def fetch_events(self, *, access_token: str, horizon_start: datetime, horizon_end: datetime) -> tuple[ProviderEvent, ...]:
        response = httpx.get(
            CALENDAR_VIEW_URL,
            headers={"Authorization": f"Bearer {access_token}", "Prefer": 'outlook.timezone="UTC"'},
            params={
                "startDateTime": horizon_start.astimezone(UTC).isoformat(),
                "endDateTime": horizon_end.astimezone(UTC).isoformat(),
                "$top": "999",
            },
        )
        if response.is_error:
            raise ProviderError(f"Graph calendarView fetch failed: {response.status_code} {response.text}")
        body = response.json()
        return tuple(_parse_event(item) for item in body.get("value", []))


def _parse_event(item: dict[str, object]) -> ProviderEvent:
    start_field = item["start"]
    end_field = item["end"]
    assert isinstance(start_field, dict) and isinstance(end_field, dict)
    return ProviderEvent(
        provider_event_id=str(item["id"]),
        start=_parse_graph_datetime(str(start_field["dateTime"])),
        end=_parse_graph_datetime(str(end_field["dateTime"])),
        title=str(item.get("subject") or "(untitled)"),
        is_all_day=bool(item.get("isAllDay", False)),
        # Graph's "free"/busy status enum - only "free" means "not actually busy" (§7).
        is_transparent=item.get("showAs") == "free",
    )


def _parse_graph_datetime(value: str) -> datetime:
    trimmed = _EXCESS_FRACTION.sub(r"\1", value)
    parsed = datetime.fromisoformat(trimmed)
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


__all__ = ["OutlookCalendarProvider"]
