import uuid
from types import SimpleNamespace

import pytest

from app.rate_limit_backends import InMemoryBackend
from app.tenancy import require_model_allowed, require_tool_type_allowed


# --- InMemoryBackend (extracted, unchanged behavior) -------------------------


async def test_in_memory_backend_allows_within_limit():
    backend = InMemoryBackend()
    for _ in range(5):
        allowed, _ = await backend.hit("key-a", max_requests=5, window_seconds=60)
        assert allowed is True


async def test_in_memory_backend_blocks_over_limit():
    backend = InMemoryBackend()
    for _ in range(5):
        await backend.hit("key-b", max_requests=5, window_seconds=60)
    allowed, retry_after = await backend.hit("key-b", max_requests=5, window_seconds=60)
    assert allowed is False
    assert retry_after > 0


async def test_in_memory_backend_keys_are_independent():
    backend = InMemoryBackend()
    for _ in range(5):
        await backend.hit("key-c", max_requests=5, window_seconds=60)
    allowed, _ = await backend.hit("key-d", max_requests=5, window_seconds=60)
    assert allowed is True


# --- RedisBackend (via fakeredis, a real in-memory Redis-protocol double) ---


@pytest.fixture
def redis_backend():
    fakeredis = pytest.importorskip("fakeredis")
    from app.rate_limit_backends import RedisBackend

    backend = RedisBackend.__new__(RedisBackend)  # skip __init__'s real redis.from_url
    backend._client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    return backend


async def test_redis_backend_allows_within_limit(redis_backend):
    for _ in range(5):
        allowed, _ = await redis_backend.hit("ws-a", max_requests=5, window_seconds=60)
        assert allowed is True


async def test_redis_backend_blocks_over_limit(redis_backend):
    for _ in range(5):
        await redis_backend.hit("ws-b", max_requests=5, window_seconds=60)
    allowed, retry_after = await redis_backend.hit("ws-b", max_requests=5, window_seconds=60)
    assert allowed is False
    assert retry_after > 0


async def test_redis_backend_shares_state_across_backend_instances(redis_backend):
    """The whole point of the Redis backend over the in-memory one: two
    SEPARATE backend objects (standing in for two separate app processes)
    against the same store enforce the SAME budget."""
    from app.rate_limit_backends import RedisBackend

    second = RedisBackend.__new__(RedisBackend)
    second._client = redis_backend._client  # same underlying fake store

    for _ in range(5):
        await redis_backend.hit("ws-c", max_requests=5, window_seconds=60)
    allowed, _ = await second.hit("ws-c", max_requests=5, window_seconds=60)
    assert allowed is False


# --- app.tenancy: config-write-time enforcement -----------------------------


async def test_require_model_allowed_permits_when_no_workspace_config(client, unique_name, db_session):
    # No WorkspaceConfig row at all for this workspace -> unrestricted.
    resp = await client.get("/api/workspace-config")
    assert resp.status_code == 200
    assert resp.json()["allowed_models"] is None

    await require_model_allowed(db_session, None, "gemini-3.5-flash")  # no workspace -> always allowed


async def test_workspace_config_round_trips_through_the_api(client):
    resp = await client.put(
        "/api/workspace-config",
        json={
            "allowed_models": ["gemini-3.5-flash"],
            "allowed_tool_types": ["http_tool"],
            "max_requests_per_minute": 50,
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["allowed_models"] == ["gemini-3.5-flash"]
    assert body["allowed_tool_types"] == ["http_tool"]
    assert body["max_requests_per_minute"] == 50

    resp = await client.get("/api/workspace-config")
    assert resp.json()["allowed_models"] == ["gemini-3.5-flash"]

    # Reset back to unrestricted so this test doesn't leak state into every
    # other test in the suite sharing the same (default) workspace.
    reset = await client.put(
        "/api/workspace-config",
        json={"allowed_models": None, "allowed_tool_types": None, "max_requests_per_minute": None},
    )
    assert reset.json()["allowed_models"] is None


async def test_agent_creation_rejects_a_model_outside_the_workspace_allowlist(client, unique_name):
    await client.put("/api/workspace-config", json={"allowed_models": ["gemini-3.5-flash"]})
    try:
        resp = await client.post(
            "/api/agents",
            json={
                "name": unique_name("tenancy_agent"),
                "base_instruction": "You are helpful.",
                "model_config": {"model": "gemini-2.5-pro"},
            },
        )
        assert resp.status_code == 422
        assert "allowed_models" in resp.text
    finally:
        await client.put("/api/workspace-config", json={"allowed_models": None})


async def test_agent_creation_allows_a_model_inside_the_workspace_allowlist(client, unique_name):
    await client.put("/api/workspace-config", json={"allowed_models": ["gemini-3.5-flash"]})
    try:
        resp = await client.post(
            "/api/agents",
            json={
                "name": unique_name("tenancy_agent"),
                "base_instruction": "You are helpful.",
                "model_config": {"model": "gemini-3.5-flash"},
            },
        )
        assert resp.status_code == 201, resp.text
    finally:
        await client.put("/api/workspace-config", json={"allowed_models": None})


async def test_tool_creation_rejects_a_tool_type_outside_the_workspace_allowlist(client, unique_name):
    await client.put("/api/workspace-config", json={"allowed_tool_types": ["mcp_tool"]})
    try:
        resp = await client.post(
            "/api/tools",
            json={
                "name": unique_name("tenancy_tool"),
                "tool_type": "http_tool",
                "config": {"base_url": "https://example.com", "method": "GET", "path_template": "/x"},
                "input_schema": {"type": "object", "properties": {}},
            },
        )
        assert resp.status_code == 422
        assert "allowed_tool_types" in resp.text
    finally:
        await client.put("/api/workspace-config", json={"allowed_tool_types": None})


async def test_require_tool_type_allowed_pure_function_permits_unrestricted(db_session):
    await require_tool_type_allowed(db_session, None, "http_tool")  # no workspace -> always allowed
