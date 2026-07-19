"""Pluggable sliding-window rate-limit backends — the storage layer
app/rate_limit.py's `_check` calls into. "memory" (default) is a bare
per-process dict, correct for the single-instance deployment this platform
actually is; "redis" is the opt-in shared-store backend a multi-instance
deployment needs (see app/rate_limit.py's module docstring for why this
was previously just a noted-but-unbuilt gap). Selected by
`Settings.rate_limit_backend`; the `redis` package is only imported
lazily, inside RedisBackend, so a fresh checkout that never sets
RATE_LIMIT_BACKEND=redis doesn't need it installed at all.
"""

import time
import uuid
from abc import ABC, abstractmethod
from collections import defaultdict, deque


class RateLimitBackend(ABC):
    @abstractmethod
    async def hit(self, key: str, max_requests: int, window_seconds: int) -> tuple[bool, int]:
        """Records one request against `key`'s sliding window and returns
        `(allowed, retry_after_seconds)`. `retry_after_seconds` is only
        meaningful when `allowed` is False."""


class InMemoryBackend(RateLimitBackend):
    """Exactly today's behavior, extracted unchanged from what was
    app/rate_limit.py's module-level `_hits`/`_check` — a bare per-process
    dict of deques. Correct for a single instance; two backend processes
    each enforce their own independent budget, same caveat as always."""

    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    async def hit(self, key: str, max_requests: int, window_seconds: int) -> tuple[bool, int]:
        now = time.monotonic()
        bucket = self._hits[key]
        while bucket and now - bucket[0] > window_seconds:
            bucket.popleft()
        if len(bucket) >= max_requests:
            retry_after = int(window_seconds - (now - bucket[0]))
            return False, max(retry_after, 1)
        bucket.append(now)
        return True, 0


class RedisBackend(RateLimitBackend):
    """Shared-store backend for a multi-instance deployment — every process
    enforces the SAME budget against the SAME Redis, instead of each
    silently giving every caller its own per-process allowance (the actual
    bug a multi-instance deploy would have with InMemoryBackend). Sliding
    window via a Redis sorted set (ZADD the request's timestamp, ZREMRANGEBYSCORE
    to expire anything older than the window, ZCARD to count what's left) —
    the same algorithm InMemoryBackend's deque implements, just against
    shared state. One extra round-trip cost per request versus the
    in-memory backend; that's the correctness/latency trade a multi-instance
    deployment is explicitly opting into by setting RATE_LIMIT_BACKEND=redis.
    """

    def __init__(self, redis_url: str) -> None:
        import redis.asyncio as redis

        self._client = redis.from_url(redis_url, decode_responses=True)

    async def hit(self, key: str, max_requests: int, window_seconds: int) -> tuple[bool, int]:
        now = time.time()
        window_start = now - window_seconds
        redis_key = f"agent_forge:rate_limit:{key}"

        async with self._client.pipeline(transaction=True) as pipe:
            pipe.zremrangebyscore(redis_key, 0, window_start)
            pipe.zcard(redis_key)
            _, count = await pipe.execute()

        if count >= max_requests:
            oldest = await self._client.zrange(redis_key, 0, 0, withscores=True)
            oldest_ts = oldest[0][1] if oldest else now
            retry_after = int(window_seconds - (now - oldest_ts))
            return False, max(retry_after, 1)

        # The sorted-set member must be unique per request, not just per
        # timestamp -- two calls landing in the same float tick of time.time()
        # (routine under real load, and reliably reproduced by a tight test
        # loop) would otherwise ZADD the same member twice and silently
        # collapse into one entry instead of two, undercounting the window.
        member = f"{now}:{uuid.uuid4()}"
        async with self._client.pipeline(transaction=True) as pipe:
            pipe.zadd(redis_key, {member: now})
            pipe.expire(redis_key, window_seconds)
            await pipe.execute()
        return True, 0
