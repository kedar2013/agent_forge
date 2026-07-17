"""Hallucination-detection extension to SCIL: the deterministic zero-tool-
call validator (pure unit), its wiring into the existing self-correction
retry loop (integration against real Postgres, _execute_run scripted for
determinism — same convention as test_scil_correction.py), the unresolved-
hallucination event written on retry exhaustion, and the LLM-judge
groundedness check (one genuinely live Gemini call, matching
test_playground.py's precedent for new LLM-touching code)."""

import asyncio
import uuid
from types import SimpleNamespace

from google.adk.sessions import InMemorySessionService
from sqlalchemy import select

import app.playground_api.router as playground_router
from app.models.agents import Agent
from app.models.logs import AgentEventLog, InvocationLog
from app.models.scil import ScilCorrectionMemory, ScilMetrics, ScilSemanticCache
from app.playground_api.router import _RunOutcome, _run_turn
from app.schemas.playground import ToolCallTrace
from app.scil.hallucination import check_groundedness
from app.scil.validators import validate_hallucination, validate_output

_FLUSH_WAIT_S = 1.5


# --- validate_hallucination: pure unit coverage -----------------------------


def test_zero_tool_call_flagged_when_tools_attached():
    agent = SimpleNamespace(output_schema=None)
    result = validate_hallucination("Sure, the answer is 42.", agent, tool_calls=[], tools_attached=True)
    assert not result.ok
    assert result.error_signature == "Hallucination:NoToolCall"


def test_tool_call_present_passes():
    agent = SimpleNamespace(output_schema=None)
    call = ToolCallTrace(name="query_orders", input={}, output={"rows": []})
    result = validate_hallucination("Here you go.", agent, tool_calls=[call], tools_attached=True)
    assert result.ok


def test_no_tools_attached_never_flags():
    agent = SimpleNamespace(output_schema=None)
    result = validate_hallucination("Sure, the answer is 42.", agent, tool_calls=[], tools_attached=False)
    assert result.ok


def test_hallucination_registered_in_validate_output_dispatch():
    agent = SimpleNamespace(output_schema=None)
    result = validate_output("invented answer", ["hallucination"], agent, tool_calls=[], tools_attached=True)
    assert not result.ok
    assert result.error_signature == "Hallucination:NoToolCall"


# --- the retry loop, with scripted outcomes (mirrors test_scil_correction.py) ---


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


def _agent_with_tool() -> SimpleNamespace:
    """A fake ADK agent whose .tools is non-empty, so validate_hallucination's
    `tools_attached` gate is True — matches what adk_agent.tools looks like
    for any real agent that has at least one tool attached."""
    return SimpleNamespace(name="fake_agent", tools=[object()])


async def _make_hallucination_agent(client, unique_name) -> dict:
    resp = await client.post(
        "/api/agents",
        json={
            "name": unique_name("scil_hallucination_agent"),
            "base_instruction": "You answer questions using your data tool.",
            "model_config": {"scil": {"enabled": True, "max_retries": 2, "validators": ["hallucination"]}},
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def test_hallucination_retry_self_corrects(client, unique_name, db_session, monkeypatch):
    agent = await _make_hallucination_agent(client, unique_name)
    agent_id = uuid.UUID(agent["id"])
    agent_row = await db_session.get(Agent, agent_id)

    invented = "The total is roughly $4,200, based on typical order volumes."
    real_call = ToolCallTrace(name="query_orders", input={}, output={"total": 3891})
    grounded = "The total is $3,891."
    fake, calls = _scripted_execute_run([_outcome(invented, tool_calls=[]), _outcome(grounded, tool_calls=[real_call])])
    monkeypatch.setattr(playground_router, "_execute_run", fake)

    message = f"what's the order total {unique_name('q')}"
    result = await _run_turn(
        db=db_session,
        adk_agent=_agent_with_tool(),
        agent_row=agent_row,
        session_service=InMemorySessionService(),
        app_name="scil_test",
        user_id="scil-test-user",
        session_id=f"scil-test-{uuid.uuid4()}",
        message=message,
        state_delta=None,
    )

    assert result.response_text == grounded
    assert len(calls) == 2
    correction_prompt = calls[1]["message"]
    assert "Hallucination:NoToolCall" in correction_prompt
    assert invented in correction_prompt

    await asyncio.sleep(_FLUSH_WAIT_S)

    corrections = (
        (await db_session.execute(select(ScilCorrectionMemory).where(ScilCorrectionMemory.agent_id == agent_id)))
        .scalars()
        .all()
    )
    assert len(corrections) == 1
    assert corrections[0].error_signature == "Hallucination:NoToolCall"
    assert corrections[0].correction_source == "auto_retry"

    cached = (
        (await db_session.execute(select(ScilSemanticCache).where(ScilSemanticCache.agent_id == agent_id)))
        .scalars()
        .all()
    )
    assert len(cached) == 1
    assert cached[0].output_payload["response_text"] == grounded


async def test_hallucination_retry_exhaustion_logs_unresolved_event(client, unique_name, db_session, monkeypatch):
    agent = await _make_hallucination_agent(client, unique_name)
    agent_id = uuid.UUID(agent["id"])
    agent_row = await db_session.get(Agent, agent_id)

    still_invented = "I believe the total is around $5,000."
    fake, calls = _scripted_execute_run(
        [_outcome(still_invented, tool_calls=[]), _outcome(still_invented, tool_calls=[]), _outcome(still_invented, tool_calls=[])]
    )
    monkeypatch.setattr(playground_router, "_execute_run", fake)

    result = await _run_turn(
        db=db_session,
        adk_agent=_agent_with_tool(),
        agent_row=agent_row,
        session_service=InMemorySessionService(),
        app_name="scil_test",
        user_id="scil-test-user",
        session_id=f"scil-test-{uuid.uuid4()}",
        message=f"what's the order total {unique_name('q')}",
        state_delta=None,
    )

    # Best-available (still-invented) answer is returned to the user...
    assert result.response_text == still_invented
    assert len(calls) == 3  # initial + max_retries(2)

    await asyncio.sleep(_FLUSH_WAIT_S)

    # ...never cached or remembered as a fix...
    corrections = (
        (await db_session.execute(select(ScilCorrectionMemory).where(ScilCorrectionMemory.agent_id == agent_id)))
        .scalars()
        .all()
    )
    assert corrections == []
    cached = (
        (await db_session.execute(select(ScilSemanticCache).where(ScilSemanticCache.agent_id == agent_id)))
        .scalars()
        .all()
    )
    assert cached == []

    # ...but IS visible as an unresolved-hallucination event for RCA/Debug Console.
    events = (
        await db_session.execute(
            select(AgentEventLog)
            .join(InvocationLog, InvocationLog.id == AgentEventLog.invocation_id)
            .where(InvocationLog.agent_id == agent_id, AgentEventLog.event_type == "hallucination_unresolved")
        )
    ).scalars().all()
    assert len(events) == 1
    assert events[0].detail["error_signature"] == "Hallucination:NoToolCall"


# --- check_groundedness: one genuinely live Gemini call, both verdicts -----


async def test_groundedness_check_flags_an_ungrounded_answer():
    agent_row = SimpleNamespace(model_config_json={"model": "gemini-3.5-flash"})
    tool_calls = [ToolCallTrace(name="query_orders", input={}, output={"total": 3891})]
    # The response invents a figure ($4,200) that appears nowhere in the tool
    # output ($3,891) — an unambiguous case for the judge to catch.
    response_text = "Based on your orders, the total comes to approximately $4,200, a strong quarter overall."
    result = await check_groundedness(response_text, tool_calls, agent_row)
    assert not result.ok
    assert result.error_signature == "Hallucination:Ungrounded"


async def test_groundedness_check_accepts_a_grounded_answer():
    agent_row = SimpleNamespace(model_config_json={"model": "gemini-3.5-flash"})
    tool_calls = [ToolCallTrace(name="query_orders", input={}, output={"total": 3891})]
    response_text = "The total is $3,891."
    result = await check_groundedness(response_text, tool_calls, agent_row)
    assert result.ok


async def test_groundedness_check_skips_when_no_tool_calls():
    # Nothing to ground against — the zero-tool-call check already covers
    # this case for free; check_groundedness must not spend a second call.
    agent_row = SimpleNamespace(model_config_json={"model": "gemini-3.5-flash"})
    result = await check_groundedness("anything", [], agent_row)
    assert result.ok
