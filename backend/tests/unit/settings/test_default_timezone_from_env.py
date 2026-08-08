"""Unit test for app.settings.service.default_timezone_from_env. See design doc §14.1."""

from app.settings.service import default_timezone_from_env


def test_unset_falls_back_to_utc() -> None:
    assert default_timezone_from_env(None) == "UTC"
    assert default_timezone_from_env("") == "UTC"


def test_valid_iana_name_is_used_as_is() -> None:
    assert default_timezone_from_env("America/New_York") == "America/New_York"


def test_invalid_name_falls_back_to_utc() -> None:
    assert default_timezone_from_env("Not/A/Real/Zone") == "UTC"
