"""Phase-3 SCIL tests: validator taxonomy (pure unit) and the
self-correction retry loop in _run_turn (integration against real Postgres,
with _execute_run monkeypatched to scripted outcomes so validation failures
are deterministic instead of hoping a live Gemini call misbehaves)."""

import asyncio
import uuid
from types import SimpleNamespace

from google.adk.sessions import InMemorySessionService
from sqlalchemy import select

import app.playground_api.router as playground_router
from app.models.agents import Agent
from app.models.scil import ScilCorrectionMemory, ScilMetrics, ScilSemanticCache
from app.playground_api.router import _RunOutcome, _run_turn
from app.scil.validators import validate_output

_FLUSH_WAIT_S = 1.5


# --- validators: pure unit coverage of the error-signature taxonomy --------


def test_validator_taxonomy():
    agent = SimpleNamespace(
        output_schema={"type": "object", "properties": {"answer": {"type": "string"}}, "required": ["answer"]}
    )
    cases = [
        ("SELECT * FROM sales LIMIT 5", ["sql"], None),
        ("```sql\nSELECT name FROM users\n```", ["sql"], None),
        ("DROP TABLE users", ["sql"], "SQL:GuardrailViolation"),
        ("SELECT 1; SELECT 2", ["sql"], "SQL:NotSingleSelect"),
        ("this is not sql at all !!!", ["sql"], "SQL:Syntax"),
        ('{"answer": "Paris"}', ["json_schema"], None),
        ('{"wrong_key": 1}', ["json_schema"], "JSON:SchemaMismatch"),
        ("not json", ["json_schema"], "JSON:ParseError"),
        ("anything", [], None),
        ("anything", ["unknown_validator"], None),
    ]
    for text, validators, expected_signature in cases:
        result = validate_output(text, validators, agent)
        assert result.ok == (expected_signature is None), (text, validators, result)
        assert result.error_signature == expected_signature


def test_json_schema_validator_accepts_when_agent_has_no_schema():
    agent = SimpleNamespace(output_schema=None)
    assert validate_output("free text, not json", ["json_schema"], agent).ok


# --- the retry loop itself, with scripted outcomes --------------------------


def _outcome(text: str, status: str = "success") -> _RunOutcome:
    outcome = _RunOutcome()
    outcome.status = status
    outcome.final_text_parts = [text]
    return outcome


def _scripted_execute_run(outcomes: list[_RunOutcome]):
    calls: list[dict] = []

    async def fake(**kwargs):
        calls.append(kwargs)
        return outcomes.pop(0)

    return fake, calls


async def _make_sql_validated_agent(client, unique_name) -> dict:
    resp = await client.post(
        "/api/agents",
        json={
            "name": unique_name("scil_retry_agent"),
            "base_instruction": "You translate questions to SQL.",
            "model_config": {"scil": {"enabled": True, "max_retries": 2, "validators": ["sql"]}},
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def test_retry_loop_corrects_remembers_and_caches(client, unique_name, db_session, monkeypatch):
    agent = await _make_sql_validated_agent(client, unique_name)
    agent_id = uuid.UUID(agent["id"])
    agent_row = await db_session.get(Agent, agent_id)

    bad, good = "sorry, I can't write SQL here !!!", "SELECT region, SUM(amount) FROM sales GROUP BY region"
    fake, calls = _scripted_execute_run([_outcome(bad), _outcome(good)])
    monkeypatch.setattr(playground_router, "_execute_run", fake)

    message = f"give me the sales query {unique_name('q')}"
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

    assert result.response_text == good
    assert len(calls) == 2
    # The second call must be the correction turn, carrying the validation
    # error and the failed output back to the model — not a blind resend.
    correction_prompt = calls[1]["message"]
    assert "SQL:Syntax" in correction_prompt
    assert bad in correction_prompt
    assert message in correction_prompt

    await asyncio.sleep(_FLUSH_WAIT_S)

    metrics = (
        (await db_session.execute(select(ScilMetrics).where(ScilMetrics.agent_id == agent_id))).scalars().all()
    )
    assert len(metrics) == 1
    assert metrics[0].route == "llm_retry"
    assert metrics[0].retries == 1
    assert metrics[0].llm_calls == 2

    corrections = (
        (await db_session.execute(select(ScilCorrectionMemory).where(ScilCorrectionMemory.agent_id == agent_id)))
        .scalars()
        .all()
    )
    assert len(corrections) == 1
    assert corrections[0].error_signature == "SQL:Syntax"
    assert corrections[0].correction_source == "auto_retry"
    assert corrections[0].failed_output["response_text"] == bad
    assert corrections[0].corrected_output["response_text"] == good

    cached = (
        (await db_session.execute(select(ScilSemanticCache).where(ScilSemanticCache.agent_id == agent_id)))
        .scalars()
        .all()
    )
    assert len(cached) == 1
    assert cached[0].output_payload["response_text"] == good
    assert cached[0].validated is True


async def test_retry_exhaustion_returns_but_never_caches(client, unique_name, db_session, monkeypatch):
    agent = await _make_sql_validated_agent(client, unique_name)
    agent_id = uuid.UUID(agent["id"])
    agent_row = await db_session.get(Agent, agent_id)

    still_bad = "I really cannot produce SQL, apologies !!!"
    fake, calls = _scripted_execute_run([_outcome(still_bad), _outcome(still_bad), _outcome(still_bad)])
    monkeypatch.setattr(playground_router, "_execute_run", fake)

    result = await _run_turn(
        db=db_session,
        adk_agent=SimpleNamespace(name="fake_agent", tools=[]),
        agent_row=agent_row,
        session_service=InMemorySessionService(),
        app_name="scil_test",
        user_id="scil-test-user",
        session_id=f"scil-test-{uuid.uuid4()}",
        message=f"give me the sales query {unique_name('q')}",
        state_delta=None,
    )

    # Best-available answer still returned to the user...
    assert result.response_text == still_bad
    assert len(calls) == 3  # initial + max_retries(2)

    await asyncio.sleep(_FLUSH_WAIT_S)

    metrics = (
        (await db_session.execute(select(ScilMetrics).where(ScilMetrics.agent_id == agent_id))).scalars().all()
    )
    assert len(metrics) == 1
    assert metrics[0].route == "llm_retry"
    assert metrics[0].retries == 2
    assert metrics[0].llm_calls == 3

    # ...but nothing gets remembered as a success: no correction pair
    # (nothing recovered) and, critically, no cache row (an invalid answer
    # must never become a future "validated" hit).
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
