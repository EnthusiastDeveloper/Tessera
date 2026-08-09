"""Resolves a `CalendarProvider` literal to a concrete client, from operator-supplied
credentials (architecture-plan §6/§7.1). See design doc §3.5 - `"other"` is in the
`CalendarProvider` enum but has no POC implementation or credential env vars, so it is
rejected here rather than silently accepted and failing later at the OAuth redirect.
"""

from __future__ import annotations

from app.calendar_sync.providers.base import CalendarProviderClient
from app.calendar_sync.providers.google import GoogleCalendarProvider
from app.calendar_sync.providers.outlook import OutlookCalendarProvider
from app.core.config import Settings
from app.db.schemas import CalendarProvider


class ProviderNotConfiguredError(Exception):
    """Raised when a provider is unsupported, or its client id/secret env vars are unset."""


def get_provider_client(provider: CalendarProvider, *, settings: Settings) -> CalendarProviderClient:
    if provider == "google":
        if not settings.google_client_id or not settings.google_client_secret:
            raise ProviderNotConfiguredError(
                "GOOGLE_CLIENT_ID/GOOGLE_CLIENT_SECRET are not set - Google calendar sync is not available."
            )
        return GoogleCalendarProvider(client_id=settings.google_client_id, client_secret=settings.google_client_secret)
    if provider == "outlook":
        if not settings.outlook_client_id or not settings.outlook_client_secret:
            raise ProviderNotConfiguredError(
                "OUTLOOK_CLIENT_ID/OUTLOOK_CLIENT_SECRET are not set - Outlook calendar sync is not available."
            )
        return OutlookCalendarProvider(client_id=settings.outlook_client_id, client_secret=settings.outlook_client_secret)
    raise ProviderNotConfiguredError(f"Provider {provider!r} has no POC implementation (design doc §3.5, §7).")


__all__ = ["ProviderNotConfiguredError", "get_provider_client"]
