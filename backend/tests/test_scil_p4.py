"""Phase-4 SCIL tests: template-based deterministic routing and
correction-exemplar injection into first attempts. Same approach as
test_scil_correction.py — _execute_run monkeypatched with scripted outcomes
so everything is deterministic (the template test additionally asserts the
model is never called at all)."""

import asyncio
import uuid
from types import SimpleNamespace

from google.adk.sessions import InMemorySessionService
from sqlalchemy import select

import app.playground_api.router as playground_router
from sqlalchemy import delete
from app.models.agents import Agent
from app.models.scil import ScilCorrectionMemory, ScilMetrics, ScilSemanticCache
from app.playground_api.router import _RunOutcome, _run_turn
from app.scil.exemplars import format_exemplar_block, Exemplar
from app.scil.templates import match_template

_FLUSH_WAIT_S = 1.5


# --- pure unit: template matching semantics ---------------------------------


def test_template_matching():
    templates = [
        {"pattern": "^ping$", "response_text": "pong"},
        {"pattern": r"convert (?P<amount>\d+) (?P<src>[a-z]{3}) to (?P<dst>[a-z]{3})", "response_text": "{amount} {src}->{dst}"},
        {"pattern": "[invalid(regex", "response_text": "never"},
        {"pattern": "^broken slots$", "response_text": "{missing_slot}"},
    ]
    assert match_template("ping", templates) == "pong"
    assert match_template("convert 100 usd to inr", templates) == "100 usd->inr"
    # fullmatch only — a template must never answer a longer, different question
    assert match_template("ping and also explain quantum physics", templates) is None
    # invalid regex and unresolvable slots skip cleanly instead of raising
    assert match_template("broken slots", templates) is None
    assert match_template("no match at all", templates) is None


def test_exemplar_block_budget_keeps_most_similar():
    def ex(i: int, similarity: float) -> Exemplar:
        return Exemplar(
            id=i, input_text=f"input {i}", error_signature="SQL:Syntax",
            error_detail="detail " + "x" * 400, corrected_text="fix " + "y" * 400, similarity=similarity,
        )

    block = format_exemplar_block([ex(1, 0.86), ex(2, 0.99), ex(3, 0.90)], budget_tokens=250)
    # 250 tokens ~= 1000 chars: only the highest-similarity exemplar fits whole
    assert "input 2" in block
    assert "input 1" not in block


# --- integration: template hit means the model is NEVER invoked -------------


async def test_template_hit_skips_llm_entirely(client, unique_name, db_session, monkeypatch):
    resp = await client.post(
        "/api/agents",
        json={
            "name": unique_name("scil_template_agent"),
            "base_instruction": "You answer questions.",
            "model_config": {
                "scil": {
                    "enabled": True,
                    "templates_enabled": True,
                    "templates": [{"pattern": "^what are your support hours\\??$", "response_text": "We're available 24/7."}],
                }
            },
        },
    )
    assert resp.status_code == 201, resp.text
    agent = resp.json()
    agent_row = await db_session.get(Agent, uuid.UUID(agent["id"]))

    async def explode(**kwargs):
        raise AssertionError("_execute_run must not be called on a template hit")

    monkeypatch.setattr(playground_router, "_execute_run", explode)

    result = await _run_turn(
        db=db_session,
        adk_agent=SimpleNamespace(name="fake"),
        agent_row=agent_row,
        session_service=InMemorySessionService(),
        app_name="scil_test",
        user_id="scil-test-user",
        session_id=f"scil-test-{uuid.uuid4()}",
        message="  What are your support HOURS?  ",
        state_delta=None,
    )
    assert result.response_text == "We're available 24/7."
    assert result.tool_calls == []

    await asyncio.sleep(_FLUSH_WAIT_S)
    metrics = (
        (await db_session.execute(select(ScilMetrics).where(ScilMetrics.agent_id == uuid.UUID(agent["id"]))))
        .scalars()
        .all()
    )
    assert len(metrics) == 1
    assert metrics[0].route == "deterministic"
    assert metrics[0].llm_calls == 0


# --- integration: a stored correction reaches the model's FIRST attempt -----


async def test_exemplar_injected_into_first_attempt(client, unique_name, db_session, monkeypatch):
    resp = await client.post(
        "/api/agents",
        json={
            "name": unique_name("scil_exemplar_agent"),
            "base_instruction": "You translate questions to SQL.",
            "model_config": {"scil": {"enabled": True, "validators": ["sql"], "max_retries": 2}},
        },
    )
    assert resp.status_code == 201, resp.text
    agent = resp.json()
    agent_id = uuid.UUID(agent["id"])
    agent_row = await db_session.get(Agent, agent_id)

    good = "SELECT region, SUM(amount) FROM sales GROUP BY region"
    message = f"give me the sales query {unique_name('q')}"

    # First: run a fail->recover turn so a correction pair gets stored.
    def outcome(text: str) -> _RunOutcome:
        o = _RunOutcome()
        o.final_text_parts = [text]
        return o

    calls: list[dict] = []
    outcomes = [outcome("not sql, sorry !!!"), outcome(good)]

    async def scripted(**kwargs):
        calls.append(kwargs)
        return outcomes.pop(0)

    monkeypatch.setattr(playground_router, "_execute_run", scripted)
    await _run_turn(
        db=db_session,
        adk_agent=SimpleNamespace(name="fake", tools=[]),
        agent_row=agent_row,
        session_service=InMemorySessionService(),
        app_name="scil_test",
        user_id="scil-test-user",
        session_id=f"scil-test-{uuid.uuid4()}",
        message=message,
        state_delta=None,
    )
    await asyncio.sleep(_FLUSH_WAIT_S)
    stored = (
        (await db_session.execute(select(ScilCorrectionMemory).where(ScilCorrectionMemory.agent_id == agent_id)))
        .scalars()
        .all()
    )
    assert len(stored) == 1

    # Second: a similar request. Purge the semantic cache first — whether
    # the first turn's fire-and-forget cache write landed in time (embedder
    # warmth varies by test order) must not decide whether this request
    # cache-hits or exercises the exemplar path under test.
    await db_session.execute(delete(ScilSemanticCache).where(ScilSemanticCache.agent_id == agent_id))
    await db_session.commit()
    calls.clear()
    outcomes.append(outcome(good))
    similar_message = f"give me the sales query again please {unique_name('q')}"
    result = await _run_turn(
        db=db_session,
        adk_agent=SimpleNamespace(name="fake", tools=[]),
        agent_row=agent_row,
        session_service=InMemorySessionService(),
        app_name="scil_test",
        user_id="scil-test-user",
        session_id=f"scil-test-{uuid.uuid4()}",
        message=similar_message,
        state_delta=None,
    )
    assert result.response_text == good
    assert len(calls) == 1  # validated first try, no retry needed
    first_prompt = calls[0]["message"]
    assert "Known corrections from similar past requests" in first_prompt
    assert similar_message in first_prompt

    await db_session.refresh(stored[0])
    assert stored[0].reuse_count >= 1
