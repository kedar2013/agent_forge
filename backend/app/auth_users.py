"""Password hashing and chat-session tokens for approved end users.

Deliberately dependency-free (stdlib hashlib/hmac only) rather than pulling in
passlib/PyJWT for what's currently a single-role, chat-only login path. If
this grows real multi-role permissions later, that's the point to switch to a
maintained JWT library instead of hand-rolling more of this.
"""

import base64
import hashlib
import hmac
import json
import os
import time

from app.config import get_settings

_PBKDF2_ITERATIONS = 200_000
_TOKEN_TTL_SECONDS = 60 * 60 * 24 * 30  # 30 days


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    derived = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, _PBKDF2_ITERATIONS)
    return base64.b64encode(salt + derived).decode()


def verify_password(password: str, stored_hash: str) -> bool:
    raw = base64.b64decode(stored_hash)
    salt, derived = raw[:16], raw[16:]
    candidate = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, _PBKDF2_ITERATIONS)
    return hmac.compare_digest(derived, candidate)


def issue_user_token(user_id: str) -> str:
    secret = get_settings().user_token_secret
    payload = {"user_id": user_id, "exp": int(time.time()) + _TOKEN_TTL_SECONDS}
    payload_b64 = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode()
    signature = hmac.new(secret.encode(), payload_b64.encode(), hashlib.sha256).hexdigest()
    return f"{payload_b64}.{signature}"


def verify_user_token(token: str) -> str | None:
    """Returns the user_id if the token is validly signed and unexpired, else None."""
    secret = get_settings().user_token_secret
    try:
        payload_b64, signature = token.split(".", 1)
        expected = hmac.new(secret.encode(), payload_b64.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected):
            return None
        payload = json.loads(base64.urlsafe_b64decode(payload_b64.encode()))
        if payload["exp"] < time.time():
            return None
        return payload["user_id"]
    except Exception:
        return None
