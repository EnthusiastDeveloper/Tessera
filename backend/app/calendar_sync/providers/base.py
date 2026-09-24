"""Provider-agnostic OAuth + event-fetch interface. See design doc §3.5, §7; architecture-plan
§6 (OAuth env vars, mandatory `state`).

`app.calendar_sync.service` talks to providers only through this interface - the concrete
`google.py`/`outlook.py` clients are never imported anywhere else, and CI substitutes a
mock implementation (`tests/fixtures/calendar_providers.py`) rather than ever calling a
real provider (implementation-plan §7's "Tests required": "OAuth flow against a mocked
provider (never a real one in CI)").
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import httpx


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


def parse_token_response(
    response: httpx.Response, *, provider_label: str, fallback_refresh_token: str | None = None
) -> ProviderTokenSet:
    """Shared OAuth2 token-endpoint response parsing - Google's and Microsoft's token
    endpoints return the same `{access_token, refresh_token?, expires_in}` shape, so
    `google.py`/`outlook.py` both call this rather than each keeping its own copy.
    `fallback_refresh_token` covers a refresh call: some providers omit `refresh_token`
    entirely when it isn't rotated, in which case the caller keeps the one it already had.
    """
    if response.is_error:
        raise ProviderError(f"{provider_label} OAuth token request failed: {response.status_code} {response.text}")
    body = response.json()
    expires_in = int(body.get("expires_in", 3600))
    return ProviderTokenSet(
        access_token=body["access_token"],
        refresh_token=body.get("refresh_token", fallback_refresh_token),
        expires_at=datetime.now(UTC) + timedelta(seconds=expires_in),
    )


#: Waits between attempts - three attempts in total. Short on purpose: this rides out a
#: momentary blip, and anything longer is left to the next scheduled poll (GitHub issue #26).
RETRY_DELAYS_SECONDS = (0.5, 1.5)
#: Responses worth another attempt: rate limiting and upstream/gateway failures. Any other
#: error (401, 400, ...) won't change on a retry.
_RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})
#: Indirection so tests can skip the real waits.
_sleep = time.sleep


def send_with_retry(send: Callable[[], httpx.Response], *, provider_label: str) -> httpx.Response:
    """Run `send` with a small bounded retry on transient failures - a network error or a
    429/5xx response. Returns the last response (the caller still checks `is_error`); a
    network error that outlasts every attempt becomes a `ProviderError`, so the service's
    existing error handling covers it instead of a raw httpx exception escaping.

    Only for idempotent calls. Exchanging an authorization code is not one: the code is
    single-use, so a retry after an ambiguous failure can only fail.
    """
    attempts = (*RETRY_DELAYS_SECONDS, None)
    for delay in attempts:
        try:
            response = send()
        except httpx.TransportError as exc:
            if delay is None:
                raise ProviderError(f"{provider_label} request failed after {len(attempts)} attempts: {exc}") from exc
        else:
            if delay is None or response.status_code not in _RETRYABLE_STATUS_CODES:
                return response
        _sleep(delay)
    raise AssertionError("unreachable: the final attempt always returns or raises")


__all__ = [
    "RETRY_DELAYS_SECONDS",
    "CalendarProviderClient",
    "ProviderError",
    "ProviderEvent",
    "ProviderTokenSet",
    "parse_token_response",
    "send_with_retry",
]
