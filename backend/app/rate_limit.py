"""Per-principal AND per-workspace sliding-window rate limiting for the
request-triggering, cost-incurring routes (/chat/message, /invoke) — stops
one caller, or one tenant's caller population in aggregate, from exhausting
the shared LLM/tool budget.

Backed by app/rate_limit_backends.py's pluggable backend (in-process dict
by default, correct for the single-instance deployment this platform
actually is; Redis when RATE_LIMIT_BACKEND=redis, for a multi-instance
deployment where every process must share the same budget).
"""

from functools import lru_cache

from fastapi import Depends, HTTPException, Request, status

from app.config import get_settings
from app.db import get_db
from app.models.workspaces import WorkspaceConfig
from app.principal import Principal, get_current_principal
from app.rate_limit_backends import InMemoryBackend, RateLimitBackend, RedisBackend
from sqlalchemy.ext.asyncio import AsyncSession

_WINDOW_SECONDS = 60
_MAX_REQUESTS_PER_WINDOW = 20

# Pre-auth endpoints (register/login) have no Principal to key on yet, and
# are classic brute-force/spam-registration targets — a tighter, IP-keyed
# window (see rate_limit_by_ip below).
_AUTH_WINDOW_SECONDS = 60
_AUTH_MAX_REQUESTS_PER_WINDOW = 10

_WORKSPACE_WINDOW_SECONDS = 60


@lru_cache
def _backend() -> RateLimitBackend:
    """Built once per process and reused — a fresh RedisBackend per call
    would reopen a connection pool every request. Cached on the resolved
    Settings, so this can't silently serve a stale backend choice across a
    settings change within one process (there isn't one; Settings itself
    is @lru_cache'd for the process lifetime, same contract)."""
    settings = get_settings()
    if settings.rate_limit_backend == "redis":
        return RedisBackend(settings.redis_url)
    return InMemoryBackend()


async def _check(key: str, max_requests: int, window_seconds: int) -> None:
    allowed, retry_after = await _backend().hit(key, max_requests, window_seconds)
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Rate limit exceeded — try again in about {retry_after}s.",
            headers={"Retry-After": str(retry_after)},
        )


async def rate_limit_principal(principal: Principal = Depends(get_current_principal)) -> Principal:
    """Limits by user_id (or the static token's role, if using the break-glass
    credential) — every named account gets its own budget."""
    key = str(principal.user_id) if principal.user_id else f"static:{principal.role}"
    await _check(key, _MAX_REQUESTS_PER_WINDOW, _WINDOW_SECONDS)
    return principal


async def rate_limit_by_ip(request: Request) -> None:
    """IP-keyed limit for /auth/register and /auth/login, which run before
    any Principal exists. Deliberately tighter than the per-principal
    budget above — 10 attempts/minute is generous for a real user mistyping
    a password, tight enough to blunt scripted brute-force/spam signups."""
    client_host = request.client.host if request.client else "unknown"
    await _check(f"ip:{client_host}", _AUTH_MAX_REQUESTS_PER_WINDOW, _AUTH_WINDOW_SECONDS)


async def rate_limit_workspace(
    principal: Principal = Depends(rate_limit_principal), db: AsyncSession = Depends(get_db)
) -> Principal:
    """Aggregate budget across EVERY principal in one workspace — catches
    "this whole tenant is unusually busy" (a burst across many of its
    users/agents/keys) independent of any single one of them individually
    staying under rate_limit_principal's own per-user budget. A no-op
    (unlimited) for requests with no workspace (the static break-glass
    token, or a workspace-less legacy row) — there's no tenant to
    aggregate against. Depends on rate_limit_principal so both checks
    always run together in the order that matters (a rejected principal
    never reaches the workspace check at all)."""
    if principal.workspace_id is None:
        return principal
    config = await db.get(WorkspaceConfig, principal.workspace_id)
    max_requests = (
        config.max_requests_per_minute
        if config and config.max_requests_per_minute is not None
        else get_settings().workspace_max_requests_per_minute
    )
    await _check(f"workspace:{principal.workspace_id}", max_requests, _WORKSPACE_WINDOW_SECONDS)
    return principal
