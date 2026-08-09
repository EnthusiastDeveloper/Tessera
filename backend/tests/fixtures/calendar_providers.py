"""Test double for `app.calendar_sync.providers.base.CalendarProviderClient` - the mocked
provider implementation-plan §7's "Tests required" mandates for CI ("OAuth flow against a
mocked provider (never a real one in CI)").
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.calendar_sync.providers.base import CalendarProviderClient, ProviderError, ProviderEvent, ProviderTokenSet


class MockCalendarProvider(CalendarProviderClient):
    """Records calls it receives and returns canned responses - `events` and
    `raise_on_fetch` are mutable after construction so a test can change what the "next"
    poll returns without rebuilding the whole connection/token fixture chain.
    """

    def __init__(
        self,
        *,
        events: tuple[ProviderEvent, ...] = (),
        access_token: str = "mock-access-token",
        refresh_token: str | None = "mock-refresh-token",
        token_ttl: timedelta = timedelta(hours=1),
    ) -> None:
        self.events = events
        self._access_token = access_token
        self._refresh_token = refresh_token
        self._token_ttl = token_ttl
        self.exchanged_codes: list[str] = []
        self.refreshed_tokens: list[str] = []
        self.fetch_calls: list[tuple[datetime, datetime]] = []
        self.raise_on_fetch: ProviderError | None = None

    def build_authorize_url(self, *, state: str, redirect_uri: str) -> str:
        return f"https://mock-provider.example/authorize?state={state}&redirect_uri={redirect_uri}"

    def exchange_code(self, *, code: str, redirect_uri: str) -> ProviderTokenSet:
        self.exchanged_codes.append(code)
        return ProviderTokenSet(
            access_token=self._access_token, refresh_token=self._refresh_token, expires_at=datetime.now(UTC) + self._token_ttl
        )

    def refresh_access_token(self, *, refresh_token: str) -> ProviderTokenSet:
        self.refreshed_tokens.append(refresh_token)
        return ProviderTokenSet(
            access_token=self._access_token, refresh_token=self._refresh_token, expires_at=datetime.now(UTC) + self._token_ttl
        )

    def fetch_events(self, *, access_token: str, horizon_start: datetime, horizon_end: datetime) -> tuple[ProviderEvent, ...]:
        self.fetch_calls.append((horizon_start, horizon_end))
        if self.raise_on_fetch is not None:
            raise self.raise_on_fetch
        return self.events


__all__ = ["MockCalendarProvider"]
