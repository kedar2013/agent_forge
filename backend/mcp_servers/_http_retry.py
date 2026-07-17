"""Shared retry-with-backoff for the MCP servers' outbound calls to free,
unauthenticated public data APIs (Yahoo Finance, CoinGecko, frankfurter.app,
gold-api.com, mfapi.in, Open-Meteo) — none of these come with an SLA, and a
bare `except Exception: return None` around a single attempt treats a
one-off network blip identically to a genuinely bad query, needlessly
surfacing "couldn't find that" to a user for something that would have
succeeded on a retry a second later.

Each mcp_servers/*.py file runs as a standalone stdio subprocess (see
tool_registry/mcp_tool.py), not a package, so this is imported as a flat
sibling module (`from _http_retry import get_with_retry`) — Python adds a
directly-run script's own directory to sys.path[0], which is enough for
that to resolve without an __init__.py.
"""

import asyncio

import httpx

_MAX_ATTEMPTS = 3
_BASE_DELAY_SECONDS = 0.5


async def get_with_retry(client: httpx.AsyncClient, url: str, **kwargs) -> httpx.Response:
    """Drop-in replacement for `client.get(url, **kwargs)` with exponential
    backoff (0.5s, 1s) on transient failures: connection errors, timeouts,
    and 5xx responses. A 2xx or 4xx response is returned immediately, same
    as a plain client.get() call — callers keep their existing
    `response.raise_for_status()` / `except Exception: return None` handling
    completely unchanged; only the call site itself changes."""
    delay = _BASE_DELAY_SECONDS
    response: httpx.Response | None = None
    for attempt in range(_MAX_ATTEMPTS):
        try:
            response = await client.get(url, **kwargs)
        except httpx.TransportError:
            if attempt == _MAX_ATTEMPTS - 1:
                raise
            await asyncio.sleep(delay)
            delay *= 2
            continue
        if response.status_code >= 500 and attempt < _MAX_ATTEMPTS - 1:
            await asyncio.sleep(delay)
            delay *= 2
            continue
        return response
    assert response is not None  # loop always returns or raises above
    return response
