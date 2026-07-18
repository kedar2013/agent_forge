"""Generic timeout + exponential-backoff retry + circuit-breaker gate around
one awaitable call. Generalizes the pattern already proven in
`mcp_servers/_http_retry.py` (hand-rolled, no new dependency) from
HTTP-`client.get` specifically to any tool I/O call — SQL, Mongo, HTTP,
whatever a tool_registry tool needs to protect.

Every tool_registry call site that had zero timeout/retry/breaker protection
(http_tool, sql_tool, mysql_tool, mongo_tool, nl2sql_tool, retrieval_tool)
wraps its actual I/O call with this. Tools that already have their own retry
story (self_healing_sql_tool's model-driven query correction, mcp_tool's
server-side `_http_retry.get_with_retry`) are NOT wrapped here to avoid a
redundant/compounding retry loop.
"""

import asyncio
from collections.abc import Awaitable, Callable
from typing import TypeVar

from app.reliability import circuit_breaker

T = TypeVar("T")


class CircuitOpenError(RuntimeError):
    """Raised instead of attempting a call when that call's breaker is open."""


async def resilient_call(
    key: str,
    fn: Callable[[], Awaitable[T]],
    *,
    timeout_seconds: float = 10.0,
    max_attempts: int = 3,
    base_backoff_seconds: float = 0.5,
    failure_threshold: int = 5,
    cooldown_seconds: float = 30.0,
) -> T:
    """`key` identifies the downstream for circuit-breaker purposes — callers
    pass their own tool id/name so breaker state is per-tool, not global.
    `fn` is a zero-arg async callable (wrap the real call in a closure/
    partial at the call site)."""
    if not circuit_breaker.call_allowed(key, cooldown_seconds=cooldown_seconds):
        raise CircuitOpenError(
            f"'{key}' is temporarily unavailable — too many recent failures, "
            f"cooling down for up to {cooldown_seconds:.0f}s before retrying."
        )

    delay = base_backoff_seconds
    for attempt in range(max_attempts):
        try:
            result = await asyncio.wait_for(fn(), timeout=timeout_seconds)
        except Exception:
            circuit_breaker.record_failure(
                key, failure_threshold=failure_threshold, cooldown_seconds=cooldown_seconds
            )
            if attempt == max_attempts - 1:
                raise
            await asyncio.sleep(delay)
            delay *= 2
            continue
        circuit_breaker.record_success(key)
        return result
    raise AssertionError("unreachable — loop above always returns or raises")
