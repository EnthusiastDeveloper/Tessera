"""Provider-agnostic OAuth + event-fetch interface. See design doc §3.5, §7; architecture-plan
§6 (OAuth env vars, mandatory `state`).

`app.calendar_sync.service` talks to providers only through this interface - the concrete
`google.py`/`outlook.py` clients are never imported anywhere else, and CI substitutes a
mock implementation (`tests/fixtures/calendar_providers.py`) rather than ever calling a
real provider (implementation-plan §7's "Tests required": "OAuth flow against a mocked
provider (never a real one in CI)").
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class ProviderTokenSet:
    """What a code exchange or refresh call returns. `refresh_token` is `None` on a refresh
    response for providers that don't rotate it - the caller keeps the existing one.
    """

    access_token: str
    refresh_token: str | None
    expires_at: datetime


@dataclass(frozen=True)
class ProviderEvent:
    """One fetched calendar event, already normalized to design doc §3.11's `ExternalEvent`
    shape - `is_all_day`/`is_transparent` are §7's filter inputs, computed here from
    whatever provider-specific representation each concrete client parses.
    """

    provider_event_id: str
    start: datetime
    end: datetime
    title: str
    is_all_day: bool
    is_transparent: bool


class ProviderError(Exception):
    """Raised by a concrete client on an upstream failure (bad code, expired refresh
    token, non-2xx response). `app.calendar_sync.service` translates this into its own
    `CalendarSyncError`; nothing about a specific provider's wire format leaks past it.
    """


class CalendarProviderClient(ABC):
    """One instance per OAuth flow/poll - concrete clients are constructed with whatever
    operator-supplied client id/secret `app.calendar_sync.providers.registry` resolved.
    """

    @abstractmethod
    def build_authorize_url(self, *, state: str, redirect_uri: str) -> str:
        """The URL to send the user's browser to. `state` must be echoed back unmodified
        by the provider on redirect (architecture-plan §6's mandatory `state` check)."""

    @abstractmethod
    def exchange_code(self, *, code: str, redirect_uri: str) -> ProviderTokenSet:
        """Trade an authorization code for tokens. `redirect_uri` must match what was sent
        to `build_authorize_url` - every OAuth2 provider validates this."""

    @abstractmethod
    def refresh_access_token(self, *, refresh_token: str) -> ProviderTokenSet:
        """Trade a refresh token for a fresh access token."""

    @abstractmethod
    def fetch_events(self, *, access_token: str, horizon_start: datetime, horizon_end: datetime) -> tuple[ProviderEvent, ...]:
        """Every event in `[horizon_start, horizon_end)` - §7's 90-day rolling horizon."""


__all__ = ["CalendarProviderClient", "ProviderError", "ProviderEvent", "ProviderTokenSet"]
