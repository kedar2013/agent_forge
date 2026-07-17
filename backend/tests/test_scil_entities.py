"""Entity resolution: the SCIL failure class neither the SQL validator nor
the hallucination validator can see -- valid SQL, a real tool call, zero
rows because the literal was misspelled. Pure-unit coverage for literal
extraction and the structural zero/nonempty detection, then integration
against real Postgres (scil_entity_memory read/write) and the retry loop
driven by monkeypatched scripted outcomes, same convention as
test_scil_correction.py / test_scil_hallucination.py."""

import asyncio
import uuid
from types import SimpleNamespace

from google.adk.sessions import InMemorySessionService
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

import app.playground_api.router as playground_router
from app.embeddings import embed_text
from app.models.agents import Agent
from app.models.scil import ScilCorrectionMemory, ScilEntityMemory, ScilSemanticCache
from app.playground_api.router import _RunOutcome, _run_turn
from app.schemas.playground import ToolCallTrace
from app.scil.entities import (
    extract_literal_values,
    remember_entities_fire_and_forget,
    resolve_entity_mismatch,
)

_FLUSH_WAIT_S = 1.5


# --- extract_literal_values: pure unit coverage -----------------------------


def test_extracts_like_literal_stripped_of_wildcards():
    assert extract_literal_values("SELECT * FROM companies WHERE company_name LIKE '%Tesslla%'") == ["Tesslla"]


def test_extracts_multiple_equality_literals():
    values = extract_literal_values("SELECT * FROM companies WHERE company_name = 'Tesla Inc' AND gfcid = 'abc123'")
    assert set(values) == {"Tesla Inc", "abc123"}


def test_short_literals_filtered_out():
    assert extract_literal_values("SELECT * FROM companies WHERE gfcid = 'x1'") == []


def test_no_where_clause_returns_empty():
    assert extract_literal_values("SELECT * FROM companies") == []


def test_invalid_sql_returns_empty_not_raises():
    assert extract_literal_values("not even sql (((") == []


# --- resolve_entity_mismatch: integration against real Postgres -------------


def _zero_row_call(sql: str) -> ToolCallTrace:
    return ToolCallTrace(name="query_companies", input={"sql": sql}, output={"row_count": 0, "columns": [], "data": []})


def _nonempty_call(sql: str) -> ToolCallTrace:
    return ToolCallTrace(
        name="query_companies", input={"sql": sql}, output={"row_count": 1, "columns": ["company_name"], "data": [{"company_name": "Tesla Inc"}]}
    )


async def _seed_entity(db_session, agent_id, text: str, use_count: int = 1) -> None:
    await db_session.execute(
        pg_insert(ScilEntityMemory).values(
            agent_id=agent_id, entity_text=text, entity_embedding=embed_text(text), use_count=use_count
        )
    )
    await db_session.commit()


async def test_resolve_finds_known_entity_for_a_typo(client, unique_name, db_session):
    agent = await client.post(
        "/api/agents",
        json={"name": unique_name("scil_entity_agent"), "base_instruction": "You answer questions."},
    )
    agent_id = uuid.UUID(agent.json()["id"])
    await _seed_entity(db_session, agent_id, "Tesla Inc")

    result = await resolve_entity_mismatch(
        agent_id, [_zero_row_call("SELECT * FROM companies WHERE company_name LIKE '%Tesslla%'")]
    )
    assert not result.ok
    assert result.error_signature == "Entity:NoMatch"
    assert "Tesla Inc" in result.error_detail


async def test_resolve_cold_start_no_memory_passes_through(client, unique_name):
    agent = await client.post(
        "/api/agents",
        json={"name": unique_name("scil_entity_agent"), "base_instruction": "You answer questions."},
    )
    agent_id = uuid.UUID(agent.json()["id"])

    result = await resolve_entity_mismatch(
        agent_id, [_zero_row_call("SELECT * FROM companies WHERE company_name LIKE '%Tesslla%'")]
    )
    assert result.ok


async def test_resolve_ignores_nonempty_results():
    result = await resolve_entity_mismatch(uuid.uuid4(), [_nonempty_call("SELECT * FROM companies WHERE company_name = 'Tesla Inc'")])
    assert result.ok


async def test_resolve_ignores_error_results():
    call = ToolCallTrace(name="query_companies", input={"sql": "SELECT 1"}, output={"error": "no visibility"})
    result = await resolve_entity_mismatch(uuid.uuid4(), [call])
    assert result.ok


# --- remember_entities_fire_and_forget: integration --------------------------


async def test_remember_writes_and_dedupes(client, unique_name, db_session):
    agent = await client.post(
        "/api/agents",
        json={"name": unique_name("scil_entity_agent"), "base_instruction": "You answer questions."},
    )
    agent_id = uuid.UUID(agent.json()["id"])

    remember_entities_fire_and_forget(agent_id, [_nonempty_call("SELECT * FROM companies WHERE company_name = 'Tesla Inc'")])
    await asyncio.sleep(_FLUSH_WAIT_S)
    remember_entities_fire_and_forget(agent_id, [_nonempty_call("SELECT * FROM companies WHERE company_name = 'Tesla Inc'")])
    await asyncio.sleep(_FLUSH_WAIT_S)

    rows = (
        (await db_session.execute(select(ScilEntityMemory).where(ScilEntityMemory.agent_id == agent_id)))
        .scalars()
        .all()
    )
    assert len(rows) == 1
    assert rows[0].entity_text == "Tesla Inc"
    assert rows[0].use_count == 2


# --- integration: the retry loop, scripted outcomes (mirrors test_scil_correction.py) ---


def _outcome(text: str, status: str = "success", tool_calls: list[ToolCallTrace] | None = None) -> _RunOutcome:
    outcome = _RunOutcome()
    outcome.status = status
    outcome.final_text_parts = [text]
    outcome.tool_calls = tool_calls or []
    return outcome


def _scripted_execute_run(outcomes: list[_RunOutcome]):
    calls: list[dict] = []

    async def fake(**kwargs):
        calls.append(kwargs)
        return outcomes.pop(0)

    return fake, calls


async def _make_entity_agent(client, unique_name) -> dict:
    resp = await client.post(
        "/api/agents",
        json={
            "name": unique_name("scil_entity_agent"),
            "base_instruction": "You answer questions using your data tool.",
            "model_config": {"scil": {"enabled": True, "max_retries": 2, "validators": ["entity_resolution"]}},
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def test_entity_retry_self_corrects(client, unique_name, db_session, monkeypatch):
    agent = await _make_entity_agent(client, unique_name)
    agent_id = uuid.UUID(agent["id"])
    agent_row = await db_session.get(Agent, agent_id)
    await _seed_entity(db_session, agent_id, "Tesla Inc")

    typo_sql = "SELECT * FROM companies WHERE company_name LIKE '%Tesslla%'"
    fixed_sql = "SELECT * FROM companies WHERE company_name LIKE '%Tesla Inc%'"
    no_match = "I couldn't find any companies matching \"Tesslla\". Did you mean Tesla?"
    found = "Here is the data for Tesla Inc: ..."
    fake, calls = _scripted_execute_run(
        [
            _outcome(no_match, tool_calls=[_zero_row_call(typo_sql)]),
            _outcome(found, tool_calls=[_nonempty_call(fixed_sql)]),
        ]
    )
    monkeypatch.setattr(playground_router, "_execute_run", fake)

    message = f"give me credit facility data for Tesslla {unique_name('q')}"
    result = await _run_turn(
        db=db_session,
        adk_agent=SimpleNamespace(name="fake_agent", tools=[]),
        agent_row=agent_row,
        session_service=InMemorySessionService(),
        app_name="scil_test",
        user_id="scil-test-user",
        session_id=f"scil-test-{uuid.uuid4()}",
        message=message,
        state_delta=None,
    )

    assert result.response_text == found
    assert len(calls) == 2
    correction_prompt = calls[1]["message"]
    assert "Entity:NoMatch" in correction_prompt
    assert "Tesla Inc" in correction_prompt

    await asyncio.sleep(_FLUSH_WAIT_S)

    corrections = (
        (await db_session.execute(select(ScilCorrectionMemory).where(ScilCorrectionMemory.agent_id == agent_id)))
        .scalars()
        .all()
    )
    assert len(corrections) == 1
    assert corrections[0].error_signature == "Entity:NoMatch"

    cached = (
        (await db_session.execute(select(ScilSemanticCache).where(ScilSemanticCache.agent_id == agent_id)))
        .scalars()
        .all()
    )
    assert len(cached) == 1
    assert cached[0].output_payload["response_text"] == found


async def test_entity_cold_start_never_forces_a_retry(client, unique_name, db_session, monkeypatch):
    """No prior memory for this agent -- the zero-row result passes through
    unflagged (route stays "llm", not "llm_retry"), matching the agent's own
    "ask the user to confirm" fallback exactly as before this feature."""
    agent = await _make_entity_agent(client, unique_name)
    agent_id = uuid.UUID(agent["id"])
    agent_row = await db_session.get(Agent, agent_id)

    no_match = "I couldn't find any companies matching \"Zzyzx Corp\"."
    fake, calls = _scripted_execute_run(
        [_outcome(no_match, tool_calls=[_zero_row_call("SELECT * FROM companies WHERE company_name LIKE '%Zzyzx Corp%'")])]
    )
    monkeypatch.setattr(playground_router, "_execute_run", fake)

    result = await _run_turn(
        db=db_session,
        adk_agent=SimpleNamespace(name="fake_agent", tools=[]),
        agent_row=agent_row,
        session_service=InMemorySessionService(),
        app_name="scil_test",
        user_id="scil-test-user",
        session_id=f"scil-test-{uuid.uuid4()}",
        message=f"give me data for Zzyzx Corp {unique_name('q')}",
        state_delta=None,
    )

    assert result.response_text == no_match
    assert len(calls) == 1  # no retry attempted