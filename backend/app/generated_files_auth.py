"""HMAC-signed, expiring access tokens for the /generated-images and
/generated-files routes (see app/main.py).

These serve files that can contain real business/financial data — PPTX
decks and PDFs built from live SQL queries against sales/customer data
(mcp_servers/slide_reporting_server.py, document_export_server.py), and
charts of the same (mcp_servers/chart_server.py) — not just generic
content. They're consumed by the frontend as plain markdown-rendered
`<img src>`/`<a href>` tags (see MessageRendering.tsx), which the browser
fetches directly with no way to attach an `Authorization` header — so the
existing Bearer-token auth (app/principal.py) can't gate them. A signed,
expiring token embedded in the URL's query string is the standard
substitute for that case (the same shape as an S3/GCS pre-signed URL):
unguessable without the secret, self-expiring, and needs no new
session/cookie infrastructure.

mcp_servers/_signed_urls.py duplicates this (rather than importing it) —
those files run as standalone subprocesses that load .env directly and
don't have the `app` package on their path (see that module's docstring).
Both read the same USER_TOKEN_SECRET env var, so tokens either one mints
verify correctly against this module.
"""

import hashlib
import hmac
import time

from app.config import get_settings

_TOKEN_TTL_SECONDS = 60 * 60 * 24 * 7  # 7 days: generous enough that a user
# revisiting chat history days later still finds a working link; short
# enough that a leaked URL doesn't stay valid forever.

# Domain-separates this token's HMAC from auth_users.py's session-token HMAC
# even though both may read the same underlying secret — a signature
# computed for one purpose must never double as a valid signature for the
# other.
_PURPOSE = "generated-file-v1"


def sign_filename(mount: str, filename: str) -> str:
    """`mount` is "generated-images" or "generated-files" — included in the
    signed message so a token minted for one mount can't be replayed
    against the other."""
    secret = get_settings().user_token_secret
    expiry = int(time.time()) + _TOKEN_TTL_SECONDS
    message = f"{_PURPOSE}:{mount}:{filename}:{expiry}"
    signature = hmac.new(secret.encode(), message.encode(), hashlib.sha256).hexdigest()
    return f"{expiry}.{signature}"


def verify_filename_token(mount: str, filename: str, token: str) -> bool:
    secret = get_settings().user_token_secret
    try:
        expiry_str, signature = token.split(".", 1)
        expiry = int(expiry_str)
    except (ValueError, AttributeError):
        return False
    if expiry < time.time():
        return False
    message = f"{_PURPOSE}:{mount}:{filename}:{expiry}"
    expected = hmac.new(secret.encode(), message.encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(signature, expected)
