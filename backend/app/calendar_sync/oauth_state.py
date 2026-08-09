"""OAuth `state` parameter generation/verification. See architecture-plan §6 ("OAuth `state`
parameter *(Rev 3)* - Mandatory. Generated per authorisation request, verified on return.
Unmentioned in Revisions 1 and 2; without it the callback accepts an attacker-initiated
authorisation code").

Stateless by design - HMAC-signed and time-limited, bound to the initiating session and
provider. No server-side row to store or clean up; a forged or replayed-past-its-window
value fails verification outright. `refresh_interval_minutes` (the connect flow's one
caller-supplied setting) rides inside the signed payload rather than needing a second
round trip to recover after the provider redirect - it can't be tampered with without
invalidating the signature.

Reuses `app.core.hmac_signing.sign`/`unsign` for the actual HMAC sign/verify step rather
than a second hand-rolled copy of the identical pattern - that module (not
`app.auth.cookie_signing`, which uses the same pattern for the session cookie) is the
shared home for it specifically because `app.auth` and `app.calendar_sync` are
independent siblings under the import-linter "Layering" contract and neither may import
the other.
"""

from __future__ import annotations

import time

from app.core.hmac_signing import sign, unsign

#: How long a `state` value remains valid after issue - only needs to survive the
#: provider's own consent-screen round trip, not a long-lived session.
STATE_MAX_AGE_SECONDS = 600


def generate_state(*, session_id: str, provider: str, refresh_interval_minutes: int, secret_key: str) -> str:
    issued_at = int(time.time())
    payload = f"{provider}:{session_id}:{refresh_interval_minutes}:{issued_at}"
    return sign(payload, secret_key)


def verify_state(state: str, *, session_id: str, provider: str, secret_key: str) -> int | None:
    """Returns the embedded `refresh_interval_minutes` if `state` is genuine, fresh, and
    matches the current session/provider - `None` otherwise (forged, expired, or for a
    different session/provider than the one presenting it).
    """
    payload = unsign(state, secret_key)
    if payload is None:
        return None
    try:
        payload_provider, payload_session_id, interval_str, issued_at_str = payload.split(":", 3)
        refresh_interval_minutes = int(interval_str)
        issued_at = int(issued_at_str)
    except ValueError:
        return None

    if payload_provider != provider or payload_session_id != session_id:
        return None
    if time.time() - issued_at > STATE_MAX_AGE_SECONDS:
        return None
    return refresh_interval_minutes


__all__ = ["STATE_MAX_AGE_SECONDS", "generate_state", "verify_state"]
