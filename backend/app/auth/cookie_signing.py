"""HMAC signing for the session cookie value. See architecture-plan §6 ("signed cookie").

The session id itself is already a high-entropy random token (§6.1) looked up
server-side, but the cookie value is additionally signed with `SECRET_KEY` so a tampered
or guessed value is rejected before it ever reaches the database.

The actual HMAC sign/verify is `app.core.hmac_signing` - shared with
`app.calendar_sync.oauth_state`'s `state` parameter, which needs the identical pattern but
can't import this module directly (`app.auth`/`app.calendar_sync` are independent siblings
under the layering contract).
"""

from __future__ import annotations

from app.core.hmac_signing import sign as _sign
from app.core.hmac_signing import unsign as _unsign


def sign(session_id: str, secret_key: str) -> str:
    """Produce the cookie value: `<session_id>.<hex hmac-sha256 signature>`."""
    return _sign(session_id, secret_key)


def unsign(cookie_value: str, secret_key: str) -> str | None:
    """Return the session id if the signature is valid, else `None`."""
    return _unsign(cookie_value, secret_key)
