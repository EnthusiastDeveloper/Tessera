"""OAuth `state` parameter generation/verification. See architecture-plan §6 ("OAuth `state`
parameter *(Rev 3)* - Mandatory. Generated per authorisation request, verified on return.
Unmentioned in Revisions 1 and 2; without it the callback accepts an attacker-initiated
authorisation code").

Stateless by design - HMAC-signed and time-limited, bound to the initiating session and
provider, the same pattern as `app.auth.cookie_signing`. No server-side row to store or
clean up; a forged or replayed-past-its-window value fails verification outright.
`refresh_interval_minutes` (the connect flow's one caller-supplied setting) rides inside
the signed payload rather than needing a second round trip to recover after the provider
redirect - it can't be tampered with without invalidating the signature.
"""

from __future__ import annotations

import hmac
import time
from hashlib import sha256

#: How long a `state` value remains valid after issue - only needs to survive the
#: provider's own consent-screen round trip, not a long-lived session.
STATE_MAX_AGE_SECONDS = 600


def generate_state(*, session_id: str, provider: str, refresh_interval_minutes: int, secret_key: str) -> str:
    issued_at = int(time.time())
    payload = f"{provider}:{session_id}:{refresh_interval_minutes}:{issued_at}"
    signature = hmac.new(secret_key.encode(), payload.encode(), sha256).hexdigest()
    return f"{refresh_interval_minutes}.{issued_at}.{signature}"


def verify_state(state: str, *, session_id: str, provider: str, secret_key: str) -> int | None:
    """Returns the embedded `refresh_interval_minutes` if `state` is genuine, fresh, and
    matches the current session/provider - `None` otherwise (forged, expired, or for a
    different session/provider than the one presenting it).
    """
    try:
        interval_str, issued_at_str, signature = state.split(".", 2)
        refresh_interval_minutes = int(interval_str)
        issued_at = int(issued_at_str)
    except ValueError:
        return None

    payload = f"{provider}:{session_id}:{refresh_interval_minutes}:{issued_at}"
    expected = hmac.new(secret_key.encode(), payload.encode(), sha256).hexdigest()
    if not hmac.compare_digest(expected, signature):
        return None
    if time.time() - issued_at > STATE_MAX_AGE_SECONDS:
        return None
    return refresh_interval_minutes


__all__ = ["STATE_MAX_AGE_SECONDS", "generate_state", "verify_state"]
