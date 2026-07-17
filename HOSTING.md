# Hosting Agent Forge — step-by-step

This covers taking the app from your local machine to a public URL. The
Dockerfiles and compose file this guide uses already exist in the repo
(`backend/Dockerfile`, `backend/docker-entrypoint.sh`, `frontend/Dockerfile`,
`frontend/Caddyfile`, `docker-compose.yml`) — nothing here needs to be
written from scratch, only configured and deployed.

## 0. What you're deploying

Two services, two databases:

- **backend** — FastAPI + Google ADK, `backend/Dockerfile`. Needs Postgres
  (with the `pgvector` extension) and MySQL. Spawns MCP server subprocesses
  and writes to two local directories (`generated_files/`,
  `generated_images/`) that must persist across restarts.
- **frontend** — a static Vite build served by Caddy, `frontend/Dockerfile`.
  No database, no secrets baked in (the admin token used to be — that's
  fixed; see `backend/SECURITY.md`).

**Constraint: the backend must run as a single instance**, not
horizontally scaled. Two in-process pieces of state
(`app/rate_limit.py`'s hit counter, the Playground's
`InMemorySessionService`) are explicitly single-instance-only — a second
replica would silently give each user inconsistent rate-limiting and
Playground session behavior. If you need more capacity, scale vertically
(bigger instance), not horizontally, unless those two pieces are rearchitected first.

## 1. Pick a host

**Recommended: Railway.** Reasoning, for when you outgrow the free tier or
reconsider: this app needs managed Postgres *and* MySQL in one place
(Render/Vercel have no managed MySQL), Dockerfile-based deploys (not
serverless — this app spawns real OS subprocesses for MCP servers, which
fights serverless request-scoping), and a persistent Volume for
`generated_files`/`generated_images` (Cloud Run's per-instance ephemeral
disk doesn't share across instances). Railway gives you all three plus a
free `*.up.railway.app` subdomain, so the steps below assume Railway. The
same Dockerfiles work on any Docker-based host with persistent volumes and
Postgres+MySQL — substitute your host's equivalents for "Railway
Postgres/MySQL plugin" and "Railway Volume" below.

## 2. Rotate every secret first — don't reuse your local `.env`

Read `backend/SECURITY.md` in full before doing anything else. In short:
every value currently in your local `backend/.env` must be treated as
already compromised (it's been visible in your local dev environment,
possibly in AI tool output, terminal history, etc.) and must **not** be
copied into the hosted environment's config. Generate fresh values:

```
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

Use this for `AGENT_FORGE_API_TOKEN` and `USER_TOKEN_SECRET`. Rotate
`GEMINI_API_KEY`/`ANTHROPIC_API_KEY` in their own provider consoles
(Google AI Studio / console.anthropic.com) — nothing in this repo can do
that for you. New database passwords come from whatever provisions the
databases in step 3.

## 3. Provision the databases

1. In Railway, add a **Postgres** plugin. Use the `pgvector/pgvector`
   image if Railway lets you pick a custom image, or run
   `CREATE EXTENSION IF NOT EXISTS vector;` once by hand against the
   provisioned database if it doesn't — this app's SCIL semantic
   cache/entity memory and `retrieval_tool` both need it.
2. Add a **MySQL** plugin. All of `MYSQL_*`, `SALES_DB_*`,
   `CREDIT_FACILITY_MYSQL_*`, `REVENUE_RETURNS_MYSQL_*` can point at this
   same server, different database names (see `backend/.env.example` for
   what each one is for and how to seed it).
3. Note the connection strings Railway generates — you'll set these as env
   vars in step 5, not in any file in the repo.

## 4. Deploy the backend

1. Create a new Railway service from `backend/Dockerfile` (build context =
   `backend/`).
2. Attach a **Volume** mounted at `/app/generated_files` and another at
   `/app/generated_images` — without this, every exported PPTX/PDF/chart
   disappears on the next restart or redeploy.
3. Set the environment variables (full list in section 6 below).
4. Deploy. `docker-entrypoint.sh` runs `alembic upgrade head` automatically
   on boot, then starts uvicorn on Railway's injected `$PORT`. Watch the
   logs for the migration to complete cleanly and confirm no errors.
5. Once it's up, hit `https://<your-backend>.up.railway.app/healthz` (should
   return `{"status":"ok"}`) and `/readyz` (confirms it can reach Postgres).

## 5. Seed the domain data

The MySQL-backed demo domains need seeding once, against the new database.
From a shell with the new `MYSQL_*`/`CREDIT_FACILITY_MYSQL_*`/
`REVENUE_RETURNS_MYSQL_*` env vars pointed at the hosted MySQL instance
(Railway lets you run one-off commands against a deployed service, or run
these from your machine with the vars exported locally):

```
python -m app.domains.credit_facility.seed_data
python -m app.domains.credit_facility.seed_agent
python -m app.domains.revenue_and_returns.seed_data
python -m app.domains.revenue_and_returns.seed_agent
```

Plus whatever seeds `sales_analytics` (the `SALES_DB_*` schema) if you're
using the slide-reporting/chart demo agents.

## 6. Backend environment variables

| Variable | Value |
|---|---|
| `DATABASE_URL` | Railway Postgres plugin's connection string |
| `MYSQL_HOST`/`PORT`/`USER`/`PASSWORD`/`DATABASE` | Railway MySQL plugin's connection details |
| `SALES_DB_*`, `CREDIT_FACILITY_MYSQL_*`, `REVENUE_RETURNS_MYSQL_*` | Same MySQL server, different database names — see `.env.example` |
| `GEMINI_API_KEY` | Freshly rotated (step 2) |
| `ANTHROPIC_API_KEY` | Freshly rotated (step 2) — optional, only needed for Claude-model agents' Playground/`/invoke` fallback (see below) |
| `AGENT_FORGE_API_TOKEN` | Freshly generated, ≥32 chars |
| `USER_TOKEN_SECRET` | Freshly generated, ≥32 chars |
| `CORS_ORIGINS` | `["https://<your-frontend-domain>"]` — the real frontend URL, not localhost |
| `BACKEND_PUBLIC_URL` | `https://<your-backend>.up.railway.app` — used to build generated-file download links |
| `ENV` | `production` |
| `DATA_RETENTION_DAYS` | Optional, defaults to 90 — see `backend/SECURITY.md`'s Data Retention section |

Setting `ENV=production` isn't optional decoration — `app/config.py`
refuses to boot if `USER_TOKEN_SECRET`/`AGENT_FORGE_API_TOKEN` are still
weak/default or `CORS_ORIGINS` still contains `localhost`. If the backend
won't start, check the startup log for exactly which of those it's
rejecting.

## 7. Deploy the frontend

1. Create a second Railway service from `frontend/Dockerfile` (build
   context = `frontend/`).
2. Set the build arg `VITE_API_BASE_URL` to
   `https://<your-backend>.up.railway.app/api`.
3. Deploy. This is a static build served by Caddy on port 80 — no runtime
   env vars needed (everything is baked in at build time via the ARG).
4. Once deployed, go back to the backend service and set `CORS_ORIGINS` to
   this frontend's actual URL, then redeploy the backend so the change
   takes effect.

## 8. Bring-your-own-key (BYOK) — what to expect

Public chat traffic (`/api/chat/*`) requires each visitor to supply their
own `X-Gemini-Api-Key`/`X-Anthropic-Api-Key` header for whichever provider
the agent they're talking to uses — your own `GEMINI_API_KEY`/
`ANTHROPIC_API_KEY` are never spent on public traffic. The frontend
prompts for this automatically (a modal titled "API key required") the
first time a visitor hits an agent needing a key it doesn't have yet, kept
in `sessionStorage` only (wiped on tab close, never sent to your backend's
database). Playground and `/invoke` (both admin/role-gated, not public)
fall back to your own operator keys, so those keep working without every
internal user needing their own key.

## 9. Verify end-to-end

Walk through this from a real browser, not curl, before calling it done:

1. Open the frontend URL. Confirm it loads.
2. Log in via the admin token flow with your new `AGENT_FORGE_API_TOKEN`.
3. Chat with a Gemini-model agent — should work immediately (operator
   fallback key configured).
4. Chat with a Claude-model agent *without* entering a key first — confirm
   the "API key required" modal appears (not a raw error). Enter a real
   Anthropic key, confirm it retries successfully.
5. Trigger a PPTX/PDF/chart export from an agent that supports it, confirm
   the download link works and the file actually opens (validates
   `BACKEND_PUBLIC_URL`, the signed-URL auth on `/generated-files`, and the
   Volume mount all at once).
6. Check the backend's logs: confirm the `alembic upgrade head` line
   succeeded on boot, and that a deliberately-triggered error (e.g. a bad
   request) returns a generic message to the browser with no stack trace
   leaked, while the full detail shows up server-side in the logs.

## 10. After you're live

- **Rotate secrets periodically and immediately after any suspected
  exposure** — see `backend/SECURITY.md`.
- **Data retention**: nothing purges old conversation data automatically
  (this app has no scheduler). Once you've settled on a retention policy,
  either call `POST /api/data-retention/purge` by hand periodically, or
  point your host's own cron/scheduled-task feature at it. Always dry-run
  first (`dry_run: true`, the default) to see counts before actually
  deleting.
- **Dependency updates**: run `pip-audit` (backend) and `npm audit`
  (frontend) periodically and after any dependency bump.
