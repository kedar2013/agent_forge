import asyncio
import uuid

from sqlalchemy import select

from app.models.scil import ScilMetrics, ScilSemanticCache

# Fire-and-forget cache/metrics writes (app/scil/runner.py) land on their own
# asyncio task shortly after the HTTP response returns -- these tests give
# them a moment to land before asserting on the DB side effects, same
# tradeoff app/logging_hooks.py's invocation logging already accepts.
_FLUSH_WAIT_S = 1.5


async def test_scil_disabled_is_passthrough(client, unique_name, db_session):
    agent_resp = await client.post(
        "/api/agents",
        json={
            "name": unique_name("scil_disabled_agent"),
            "base_instruction": "You are a helpful assistant. Keep answers to one sentence.",
        },
    )
    agent = agent_resp.json()
    assert agent["model_config"].get("scil") is None

    resp = await client.post(
        "/api/playground/run",
        json={"agent_id": agent["id"], "message": "Say hello in exactly three words."},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["response_text"]

    await asyncio.sleep(_FLUSH_WAIT_S)
    rows = (
        (await db_session.execute(select(ScilMetrics).where(ScilMetrics.agent_id == uuid.UUID(agent["id"]))))
        .scalars()
        .all()
    )
    assert len(rows) == 1
    assert rows[0].route == "disabled"
    assert rows[0].llm_calls == 1

    cache_rows = (
        (
            await db_session.execute(
                select(ScilSemanticCache).where(ScilSemanticCache.agent_id == uuid.UUID(agent["id"]))
            )
        )
        .scalars()
        .all()
    )
    assert cache_rows == []


async def test_scil_cache_hit_avoids_llm_call(client, unique_name, db_session):
    agent_resp = await client.post(
        "/api/agents",
        json={
            "name": unique_name("scil_cache_agent"),
            "base_instruction": "You are a helpful assistant. Keep answers to one sentence.",
            "model_config": {"scil": {"enabled": True, "cache_similarity_threshold": 0.80}},
        },
    )
    agent = agent_resp.json()
    assert agent["model_config"]["scil"]["enabled"] is True
    agent_id = uuid.UUID(agent["id"])

    message = "What is the capital of France? Answer in one word."

    first = await client.post("/api/playground/run", json={"agent_id": agent["id"], "message": message})
    assert first.status_code == 200, first.text
    first_body = first.json()
    assert first_body["response_text"]

    await asyncio.sleep(_FLUSH_WAIT_S)

    cache_rows = (
        (await db_session.execute(select(ScilSemanticCache).where(ScilSemanticCache.agent_id == agent_id)))
        .scalars()
        .all()
    )
    assert len(cache_rows) == 1
    assert cache_rows[0].validated is True

    metrics_rows = (
        (
            await db_session.execute(
                select(ScilMetrics).where(ScilMetrics.agent_id == agent_id).order_by(ScilMetrics.created_at)
            )
        )
        .scalars()
        .all()
    )
    assert len(metrics_rows) == 1
    assert metrics_rows[0].route == "llm"
    assert metrics_rows[0].llm_calls == 1

    # Same message again -- should be served straight from the cache, zero
    # additional LLM calls.
    second = await client.post("/api/playground/run", json={"agent_id": agent["id"], "message": message})
    assert second.status_code == 200, second.text
    second_body = second.json()
    assert second_body["response_text"] == first_body["response_text"]

    await asyncio.sleep(_FLUSH_WAIT_S)

    metrics_rows_after = (
        (
            await db_session.execute(
                select(ScilMetrics).where(ScilMetrics.agent_id == agent_id).order_by(ScilMetrics.created_at)
            )
        )
        .scalars()
        .all()
    )
    assert len(metrics_rows_after) == 2
    assert metrics_rows_after[1].route == "cache_hit"
    assert metrics_rows_after[1].llm_calls == 0

    # The cache row's hit_count should reflect the second call's read.
    await db_session.refresh(cache_rows[0])
    assert cache_rows[0].hit_count == 1
