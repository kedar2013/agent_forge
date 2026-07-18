"""In-memory, per-key circuit breaker for tool call sites.

In-process only, same caveat as app/rate_limit.py: correct for the single
backend instance this deployment actually is (see the design doc's "MUST run
as a single instance" note). A multi-instance deployment would need a shared
store (Redis) instead of this module-level dict. Unlike the durable-execution
checkpoint state in invocation_log/tool_call_log, a breaker resetting on
redeploy is *correct* behavior, not a gap — "try the downstream again after a
restart" is exactly what you want, so this is deliberately not persisted.

Three states per key: closed (normal), open (short-circuiting, downstream is
presumed broken), half_open (cooldown elapsed, next call is a trial). This is
a simplified single-process breaker, not a strict textbook implementation —
under concurrent asyncio calls, more than one trial call may slip through
during half_open; acceptable here because the cost of an extra trial call is
low and there's no cross-process coordination to get right in the first
place.
"""

import time
from dataclasses import dataclass

_DEFAULT_FAILURE_THRESHOLD = 5
_DEFAULT_COOLDOWN_SECONDS = 30.0


@dataclass
class _BreakerState:
    consecutive_failures: int = 0
    state: str = "closed"  # "closed" | "open" | "half_open"
    opened_at: float | None = None  # time.monotonic() timestamp
    last_failure_at: float | None = None
    last_success_at: float | None = None


_breakers: dict[str, _BreakerState] = {}


def call_allowed(key: str, *, cooldown_seconds: float = _DEFAULT_COOLDOWN_SECONDS) -> bool:
    """Whether a call keyed by `key` should be attempted at all. Transitions
    open -> half_open once the cooldown has elapsed, allowing a trial call
    through; record_success/record_failure resolve that trial."""
    breaker = _breakers.get(key)
    if breaker is None or breaker.state == "closed":
        return True
    if breaker.state == "half_open":
        return True
    # state == "open"
    assert breaker.opened_at is not None
    if time.monotonic() - breaker.opened_at >= cooldown_seconds:
        breaker.state = "half_open"
        return True
    return False


def record_success(key: str) -> None:
    breaker = _breakers.setdefault(key, _BreakerState())
    breaker.consecutive_failures = 0
    breaker.state = "closed"
    breaker.opened_at = None
    breaker.last_success_at = time.monotonic()


def record_failure(
    key: str,
    *,
    failure_threshold: int = _DEFAULT_FAILURE_THRESHOLD,
    cooldown_seconds: float = _DEFAULT_COOLDOWN_SECONDS,
) -> None:
    breaker = _breakers.setdefault(key, _BreakerState())
    breaker.consecutive_failures += 1
    breaker.last_failure_at = time.monotonic()
    if breaker.state == "half_open" or breaker.consecutive_failures >= failure_threshold:
        breaker.state = "open"
        breaker.opened_at = time.monotonic()


def snapshot() -> list[dict]:
    """Admin-panel view of current breaker state, one row per key that has
    ever recorded a failure or success."""
    now = time.monotonic()
    rows = []
    for key, breaker in sorted(_breakers.items()):
        cooldown_remaining = None
        if breaker.state == "open" and breaker.opened_at is not None:
            cooldown_remaining = max(0.0, _DEFAULT_COOLDOWN_SECONDS - (now - breaker.opened_at))
        rows.append(
            {
                "key": key,
                "state": breaker.state,
                "consecutive_failures": breaker.consecutive_failures,
                "cooldown_remaining_seconds": cooldown_remaining,
            }
        )
    return rows
