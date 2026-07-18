import logging
import os

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy import text

from app.agent_runtime.byok import register as register_byok_models
from app.auth_api.router import router as auth_router
from app.chat_api.router import router as chat_router
from app.config import get_settings
from app.generated_files_auth import verify_filename_token
from app.config_api.access_policies import router as access_policies_router
from app.config_api.agent_transfer import router as agent_transfer_router
from app.config_api.agents import router as agents_router
from app.config_api.data_entities import router as data_entities_router
from app.config_api.publish_requests import router as publish_requests_router
from app.config_api.skills import router as skills_router
from app.config_api.tools import router as tools_router
from app.dashboards_api.audit import router as audit_router
from app.dashboards_api.monitoring import router as monitoring_router
from app.dashboards_api.retention import router as retention_router
from app.dashboards_api.usage import router as usage_router
from app.db import async_session_factory
from app.debug_api.router import router as debug_router
from app.observability.tracing import setup_tracing
from app.playground_api.router import invoke_router, router as playground_router
from app.prompt_eval_api.router import router as prompt_eval_router
from app.reliability_api.router import router as reliability_router
from app.scil_api.router import router as scil_router

# The root logger has no handler by default, so every `logger.info`/`.debug`
# call across the app (this module and anything it imports) is silently
# dropped — only uvicorn's own access/error loggers, which configure
# themselves independently, were ever reaching the console. This gives every
# `logging.getLogger(__name__)` call site in the app a console handler.
logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

logger = logging.getLogger(__name__)

# Must run before any request is served, not lazily — see byok.register()'s
# docstring: LLMRegistry.resolve() is @lru_cache'd, so a request that
# resolves a gemini-* model string before this call would keep resolving
# to ADK's stock Gemini class for this process's entire lifetime. Module
# import happens before uvicorn binds the port, so this is early enough.
register_byok_models()

app = FastAPI(
    title="Agent Forge",
    description="The control plane for governed, auditable agentic AI — built for regulated enterprises.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

setup_tracing(app)

app.include_router(tools_router, prefix="/api")
app.include_router(access_policies_router, prefix="/api")
app.include_router(data_entities_router, prefix="/api")
app.include_router(skills_router, prefix="/api")
# Registered before agents_router: /agents/import and /agents/publish-requests
# are literal paths that would otherwise be swallowed by agents_router's
# /agents/{agent_id} pattern (Starlette matches routes in registration order
# for such ambiguous cases).
app.include_router(agent_transfer_router, prefix="/api")
app.include_router(publish_requests_router, prefix="/api")
app.include_router(agents_router, prefix="/api")
app.include_router(playground_router, prefix="/api")
app.include_router(invoke_router, prefix="/api")
app.include_router(monitoring_router, prefix="/api")
app.include_router(usage_router, prefix="/api")
app.include_router(audit_router, prefix="/api")
app.include_router(retention_router, prefix="/api")
app.include_router(debug_router, prefix="/api")
app.include_router(scil_router, prefix="/api")
app.include_router(reliability_router, prefix="/api")
app.include_router(prompt_eval_router, prefix="/api")
app.include_router(auth_router, prefix="/api")
app.include_router(chat_router, prefix="/api")

_generated_images_dir = os.path.join(os.path.dirname(__file__), "..", "generated_images")
os.makedirs(_generated_images_dir, exist_ok=True)

_generated_files_dir = os.path.join(os.path.dirname(__file__), "..", "generated_files")
os.makedirs(_generated_files_dir, exist_ok=True)


def _serve_generated(directory: str, mount: str, filename: str, token: str) -> FileResponse:
    """Backs both /generated-images/{filename} and /generated-files/{filename}
    below. Deliberately NOT a plain `StaticFiles` mount (what this replaced):
    these directories can hold real business/financial data (see
    generated_files_auth.py's docstring), and the frontend consumes their
    URLs as plain <img>/<a> tags with no Authorization header — so access is
    gated by a signed, expiring `token` query param instead (verified
    below), the same shape as an S3/GCS pre-signed URL.

    `filename` is a single path segment (FastAPI's `{filename}` route
    param can't itself contain "/"), but reject any residual "..'"/separator
    unconditionally rather than relying on that alone — os.path.join with an
    absolute-looking segment can still escape `directory` on some platforms."""
    if "/" in filename or "\\" in filename or filename in (".", ".."):
        raise HTTPException(status_code=400, detail="Invalid filename.")
    if not verify_filename_token(mount, filename, token):
        raise HTTPException(status_code=403, detail="Invalid or expired access link.")
    path = os.path.join(directory, filename)
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="Not found.")
    return FileResponse(path)


@app.get("/generated-images/{filename}")
async def get_generated_image(filename: str, token: str = Query(...)) -> FileResponse:
    return _serve_generated(_generated_images_dir, "generated-images", filename, token)


@app.get("/generated-files/{filename}")
async def get_generated_file(filename: str, token: str = Query(...)) -> FileResponse:
    return _serve_generated(_generated_files_dir, "generated-files", filename, token)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Last-resort catch-all for a genuinely unexpected exception that
    slipped past every endpoint's own handling (FastAPI's normal
    HTTPException flow is untouched by this — it only fires for something
    that would otherwise be an unhandled 500 with a raw traceback). Logs the
    full exception server-side so it's still debuggable, but returns a
    generic message to the caller: an unhandled exception's str() can leak
    internal details (file paths, query fragments, library internals) that
    have no business reaching an external client, especially for a platform
    meant to run in regulated enterprise environments.

    CORS headers are added by hand: this handler runs at Starlette's
    ServerErrorMiddleware layer, OUTSIDE the CORSMiddleware wrapping — so
    without them, a browser on another origin (the Vite dev frontend)
    blocks the 500 response entirely and fetch() rejects with the opaque
    "Failed to fetch" instead of showing the error to the user."""
    logger.exception("Unhandled exception on %s %s", request.method, request.url.path)
    headers = {}
    origin = request.headers.get("origin")
    if origin and origin in get_settings().cors_origins:
        headers["Access-Control-Allow-Origin"] = origin
    return JSONResponse(status_code=500, content={"detail": "An unexpected error occurred."}, headers=headers)


@app.get("/healthz")
async def healthz() -> dict:
    """Liveness — just confirms the process is up and serving. Deliberately
    checks nothing external: an orchestrator (k8s or otherwise) restarting
    the whole process because a downstream dependency hiccuped would be the
    wrong response to that failure — that's what readiness (below) is for."""
    return {"status": "ok"}


@app.get("/readyz")
async def readyz() -> JSONResponse:
    """Readiness — can this instance actually serve real traffic right now.
    Checks the one hard dependency every request needs: Postgres. A load
    balancer/orchestrator should stop routing traffic here (not restart the
    process) on a 503 — the process itself is fine, the database just isn't
    reachable yet (e.g. mid-restart, or a network blip)."""
    try:
        async with async_session_factory() as session:
            await session.execute(text("SELECT 1"))
        return JSONResponse(status_code=200, content={"status": "ok", "database": "ok"})
    except Exception as exc:  # noqa: BLE001 — reported as a 503, not raised
        logger.warning("Readiness check failed: %s", exc)
        return JSONResponse(status_code=503, content={"status": "not_ready", "database": "unreachable"})
