"""HMAC-signed, expiring access tokens for the /generated-images and
/generated-files URLs this subprocess mints (see chart_server.py,
document_export_server.py, slide_reporting_server.py).

Duplicates app/generated_files_auth.py rather than importing it: this file
is loaded by standalone MCP server subprocesses (see _db.py's docstring —
same reasoning) that don't have the `app` package on their path. Reads
USER_TOKEN_SECRET directly from backend/.env, the same env var
app/config.py's Settings.user_token_secret reads (pydantic-settings'
env-var matching is case-insensitive by default) — so a token minted here
verifies correctly against app/generated_files_auth.verify_filename_token
in the main FastAPI process that actually serves the file.
"""

import hashlib
import hmac
import os
import time

from dotenv import load_dotenv

_ENV_PATH = os.path.join(os.path.dirname(__file__), "..", ".env")
load_dotenv(_ENV_PATH)

_TOKEN_TTL_SECONDS = 60 * 60 * 24 * 7  # keep in sync with app/generated_files_auth.py
_PURPOSE = "generated-file-v1"  # keep in sync with app/generated_files_auth.py


def sign_filename(mount: str, filename: str) -> str:
    """`mount` is "generated-images" or "generated-files"."""
    secret = os.environ.get("USER_TOKEN_SECRET", "dev-only-insecure-secret-change-me")
    expiry = int(time.time()) + _TOKEN_TTL_SECONDS
    message = f"{_PURPOSE}:{mount}:{filename}:{expiry}"
    signature = hmac.new(secret.encode(), message.encode(), hashlib.sha256).hexdigest()
    return f"{expiry}.{signature}"
