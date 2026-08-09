"""Provider registry resolution tests. See design doc §3.5 (`"other"` has no POC
implementation), architecture-plan §7.1 (operator-supplied credential env vars).
"""

from __future__ import annotations

import pytest

from app.calendar_sync.providers.google import GoogleCalendarProvider
from app.calendar_sync.providers.outlook import OutlookCalendarProvider
from app.calendar_sync.providers.registry import ProviderNotConfiguredError, get_provider_client
from app.core.config import Settings


def _settings(**overrides: object) -> Settings:
    defaults: dict[str, object] = {"secret_key": "k"}
    defaults.update(overrides)
    return Settings(**defaults)  # type: ignore[arg-type]


def test_google_resolves_when_configured() -> None:
    client = get_provider_client("google", settings=_settings(google_client_id="id", google_client_secret="secret"))
    assert isinstance(client, GoogleCalendarProvider)


def test_outlook_resolves_when_configured() -> None:
    client = get_provider_client("outlook", settings=_settings(outlook_client_id="id", outlook_client_secret="secret"))
    assert isinstance(client, OutlookCalendarProvider)


def test_google_without_credentials_raises() -> None:
    with pytest.raises(ProviderNotConfiguredError):
        get_provider_client("google", settings=_settings())


def test_outlook_without_credentials_raises() -> None:
    with pytest.raises(ProviderNotConfiguredError):
        get_provider_client("outlook", settings=_settings())


def test_other_provider_is_rejected() -> None:
    with pytest.raises(ProviderNotConfiguredError):
        get_provider_client("other", settings=_settings())
