"""Per-principal sliding-window rate limiting for the request-triggering,
cost-incurring routes (/chat/message, /invoke) — stops one caller from
exhausting the shared LLM/tool budget.

In-process only: correct for a single backend instance, which is what this
deployment is. A multi-instance deployment would need a shared store (Redis)
instead of this in-memory dict — noted here rather than silently assumed away.
"""

import time
from collections import defaultdict, deque

from fastapi import Depends, HTTPException, Request, status

from app.principal import Principal, get_current_principal

_WINDOW_SECONDS = 60
_MAX_REQUESTS_PER_WINDOW = 20

# Pre-auth endpoints (register/login) have no Principal to key on yet, and
# are classic brute-force/spam-registration targets — a tighter, IP-keyed
# window (see rate_limit_by_ip below).
_AUTH_WINDOW_SECONDS = 60
_AUTH_MAX_REQUESTS_PER_WINDOW = 10

_hits: dict[str, deque[float]] = defaultdict(deque)


def _check(key: str, max_requests: int, window_seconds: int) -> None:
    now = time.monotonic()
    bucket = _hits[key]
    while bucket and now - bucket[0] > window_seconds:
        bucket.popleft()
    if len(bucket) >= max_requests:
        retry_after = int(window_seconds - (now - bucket[0]))
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Rate limit exceeded — try again in about {max(retry_after, 1)}s.",
            headers={"Retry-After": str(max(retry_after, 1))},
        )
    bucket.append(now)


async def rate_limit_principal(principal: Principal = Depends(get_current_principal)) -> Principal:
    """Limits by user_id (or the static token's role, if using the break-glass
    credential) — every named account gets its own budget."""
    key = str(principal.user_id) if principal.user_id else f"static:{principal.role}"
    _check(key, _MAX_REQUESTS_PER_WINDOW, _WINDOW_SECONDS)
    return principal


async def rate_limit_by_ip(request: Request) -> None:
    """IP-keyed limit for /auth/register and /auth/login, which run before
    any Principal exists. Deliberately tighter than the per-principal
    budget above — 10 attempts/minute is generous for a real user mistyping
    a password, tight enough to blunt scripted brute-force/spam signups.
    Same in-process caveat as rate_limit_principal: correct for a single
    backend instance, would need a shared store behind a load balancer."""
    client_host = request.client.host if request.client else "unknown"
    _check(f"ip:{client_host}", _AUTH_MAX_REQUESTS_PER_WINDOW, _AUTH_WINDOW_SECONDS)
