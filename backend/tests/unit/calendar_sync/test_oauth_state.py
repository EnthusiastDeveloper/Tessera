"""OAuth `state` parameter tests. See architecture-plan §6 ("mandatory, verified on return")."""

from __future__ import annotations

import pytest

from app.calendar_sync import oauth_state
from app.calendar_sync.oauth_state import STATE_MAX_AGE_SECONDS, generate_state, verify_state


def test_valid_state_round_trips_the_refresh_interval() -> None:
    state = generate_state(session_id="sess-1", provider="google", refresh_interval_minutes=30, secret_key="k")
    assert verify_state(state, session_id="sess-1", provider="google", secret_key="k") == 30


def test_wrong_session_id_is_rejected() -> None:
    state = generate_state(session_id="sess-1", provider="google", refresh_interval_minutes=30, secret_key="k")
    assert verify_state(state, session_id="sess-2", provider="google", secret_key="k") is None


def test_wrong_provider_is_rejected() -> None:
    """The callback binds `state` to a specific provider path - a state minted for
    `google` must not validate against an `outlook` callback."""
    state = generate_state(session_id="sess-1", provider="google", refresh_interval_minutes=30, secret_key="k")
    assert verify_state(state, session_id="sess-1", provider="outlook", secret_key="k") is None


def test_wrong_secret_key_is_rejected() -> None:
    state = generate_state(session_id="sess-1", provider="google", refresh_interval_minutes=30, secret_key="k1")
    assert verify_state(state, session_id="sess-1", provider="google", secret_key="k2") is None


def test_tampered_refresh_interval_is_rejected() -> None:
    """An attacker flipping the embedded interval must invalidate the signature - it isn't
    a separate unsigned field. `state` is `<provider>:<session_id>:<interval>:<issued_at>.<signature>`
    (`app.core.hmac_signing.sign`'s `<value>.<signature>` shape)."""
    state = generate_state(session_id="sess-1", provider="google", refresh_interval_minutes=30, secret_key="k")
    payload, signature = state.rsplit(".", 1)
    provider, session_id, _interval, issued_at = payload.split(":", 3)
    tampered = f"{provider}:{session_id}:999:{issued_at}.{signature}"
    assert verify_state(tampered, session_id="sess-1", provider="google", secret_key="k") is None


def test_malformed_state_is_rejected() -> None:
    assert verify_state("not-a-valid-state", session_id="sess-1", provider="google", secret_key="k") is None
    assert verify_state("", session_id="sess-1", provider="google", secret_key="k") is None


def test_expired_state_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    real_time = oauth_state.time.time
    monkeypatch.setattr(oauth_state.time, "time", lambda: real_time() - STATE_MAX_AGE_SECONDS - 1)
    state = generate_state(session_id="sess-1", provider="google", refresh_interval_minutes=30, secret_key="k")
    monkeypatch.undo()

    assert verify_state(state, session_id="sess-1", provider="google", secret_key="k") is None


def test_fresh_state_within_window_is_accepted(monkeypatch: pytest.MonkeyPatch) -> None:
    real_time = oauth_state.time.time
    monkeypatch.setattr(oauth_state.time, "time", lambda: real_time() - STATE_MAX_AGE_SECONDS + 1)
    state = generate_state(session_id="sess-1", provider="google", refresh_interval_minutes=30, secret_key="k")
    monkeypatch.undo()

    assert verify_state(state, session_id="sess-1", provider="google", secret_key="k") == 30
