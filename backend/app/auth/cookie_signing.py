"""HMAC signing for the session cookie value. See architecture-plan §6 ("signed cookie").

The session id itself is already a high-entropy random token (§6.1) looked up
server-side, but the cookie value is additionally signed with `SECRET_KEY` so a tampered
or guessed value is rejected before it ever reaches the database.
"""

from __future__ import annotations

import hmac
from hashlib import sha256


def sign(session_id: str, secret_key: str) -> str:
    """Produce the cookie value: `<session_id>.<hex hmac-sha256 signature>`."""
    signature = hmac.new(secret_key.encode(), session_id.encode(), sha256).hexdigest()
    return f"{session_id}.{signature}"


def unsign(cookie_value: str, secret_key: str) -> str | None:
    """Return the session id if the signature is valid, else `None`."""
    try:
        session_id, signature = cookie_value.rsplit(".", 1)
    except ValueError:
        return None
    expected = hmac.new(secret_key.encode(), session_id.encode(), sha256).hexdigest()
    if not hmac.compare_digest(expected, signature):
        return None
    return session_id
