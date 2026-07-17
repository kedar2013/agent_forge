# Secrets and environment separation

`backend/.env` is a **local development** file only. Every value in it
(and every value that has appeared in an AI coding session's tool output
while working in this codebase) must be treated as already compromised —
never copy it verbatim into a hosted environment's config.

`app/config.py`'s `Settings` validator enforces part of this
automatically: once `ENV` is set to anything other than `development`, the
app refuses to boot if `USER_TOKEN_SECRET`/`AGENT_FORGE_API_TOKEN` are
missing, still the placeholder default, or under 32 characters, or if
`CORS_ORIGINS` still contains a `localhost`/`127.0.0.1` entry. `ENV=development`
(the default) skips all of this, so a fresh local checkout always boots
with the placeholder values in `.env.example`.

What that validator *can't* check — a database password or an LLM API key
looks the same whether it's weak or strong, reused or fresh — is this
checklist. Work through it before the first deploy to any non-development
environment, and again any time a value has been exposed (e.g. pasted into
a chat, a log, a screen share).

## Rotate before every deploy to a hosted environment

| Variable | How to rotate |
|---|---|
| `AGENT_FORGE_API_TOKEN` | `python -c "import secrets; print(secrets.token_urlsafe(32))"` |
| `USER_TOKEN_SECRET` | Same command. Rotating this invalidates every currently-issued end-user chat session token (`app/auth_users.py`) — expected, not a bug. |
| `DATABASE_URL` password, `MYSQL_*`/`SALES_DB_*`/`CREDIT_FACILITY_MYSQL_*`/`REVENUE_RETURNS_MYSQL_*` passwords | Generate a fresh password in whatever manages that database (a hosting provider's managed DB usually does this for you on provisioning); update the corresponding env var. |

## Can't be automated — rotate manually in the provider's own console

| Variable | Where |
|---|---|
| `GEMINI_API_KEY` | Google AI Studio / Google Cloud Console — revoke the old key, issue a new one. |
| `ANTHROPIC_API_KEY` | console.anthropic.com → Settings → API Keys — same. |

Both are provider-issued credentials; nothing in this repo can revoke or
reissue them. If either has been exposed, rotating it is the only fix —
changing `.env` alone doesn't invalidate the old key.

## Also set correctly on any hosted environment

- `ENV` — anything other than `development` (`production`, `staging`, ...) to
  turn on the checks above.
- `CORS_ORIGINS` — the real frontend origin(s), not `localhost`.
- `BACKEND_PUBLIC_URL` — the backend's real reachable URL, not
  `http://127.0.0.1:8000`. Used to build download links for generated
  files/images (`app/generated_files_auth.py`, `mcp_servers/*.py`) — left
  at the loopback default, those links 404 for anyone but the host itself.

## Data retention

`POST /api/data-retention/purge` (admin-only, `app/dashboards_api/retention.py`)
deletes conversation/PII-bearing data older than `DATA_RETENTION_DAYS`
(default 90 — set your own policy) for the caller's workspace: invocation
transcripts, SCIL cache/correction/entity/eval data, and ADK chat sessions.
See `app/retention.py`'s module docstring for exactly what's covered and
what's deliberately excluded (the hash-chained audit log; `/invoke`'s ADK
sessions, which have no reliable per-workspace attribution).

Defaults to `dry_run=true` (counts only, deletes nothing) — pass
`dry_run=false` to actually purge. Nothing calls this automatically; this
app has no scheduler. Run it by hand, or point your hosting provider's own
cron feature at it once you've settled on a retention period.
