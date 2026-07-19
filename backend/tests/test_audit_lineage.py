import uuid
from datetime import datetime, timezone

from app.event_chain import next_chain_link, verify_event_chain
from app.models.guardrails import GuardrailEvent, PolicyEvent
from app.models.logs import InvocationLog, ToolCallLog
from app.tool_registry.policy_audit import record_policy_denial

_GUARDRAIL_HASH_FIELDS = [
    "workspace_id",
    "agent_id",
    "agent_name",
    "adk_invocation_id",
    "direction",
    "check_name",
    "action",
    "reason",
    "matched_preview",
    "created_at",
]
_POLICY_HASH_FIELDS = [
    "workspace_id",
    "agent_id",
    "agent_name",
    "adk_invocation_id",
    "tool_name",
    "policy_id",
    "engine",
    "persona",
    "reason",
    "created_at",
]


# --- PolicyEvent write path --------------------------------------------------


async def test_record_policy_denial_writes_a_chained_row(client, unique_name, db_session):
    agent_resp = await client.post(
        "/api/agents",
        json={"name": unique_name("policy_audit_agent"), "base_instruction": "You are a helpful assistant."},
    )
    agent = agent_resp.json()

    invocation_id = f"policy-test-{uuid.uuid4().hex[:8]}"
    await record_policy_denial(
        workspace_id=uuid.UUID(agent["workspace_id"]) if agent.get("workspace_id") else None,
        agent_id=uuid.UUID(agent["id"]),
        agent_name=agent["name"],
        adk_invocation_id=invocation_id,
        tool_name="query_companies",
        policy_id=None,
        engine="python",
        persona="CCB",
        reason="CCB access requires an exact gfcid.",
    )

    from sqlalchemy import select

    row = (
        await db_session.execute(select(PolicyEvent).where(PolicyEvent.adk_invocation_id == invocation_id))
    ).scalar_one()
    assert row.tool_name == "query_companies"
    assert row.engine == "python"
    assert row.seq > 0
    assert row.row_hash


# --- generic hash-chain verification ----------------------------------------


async def test_verify_event_chain_confirms_an_untampered_chain(db_session):
    for i in range(3):
        await record_policy_denial(
            workspace_id=None,
            agent_id=None,
            agent_name=None,
            adk_invocation_id=f"verify-chain-test-{uuid.uuid4().hex[:8]}",
            tool_name=f"tool_{i}",
            policy_id=None,
            engine="python",
            persona="CCB",
            reason="denied",
        )

    result = await verify_event_chain(db_session, PolicyEvent, _POLICY_HASH_FIELDS)
    assert result["verified"] is True


async def test_verify_event_chain_detects_tampering(db_session):
    from sqlalchemy import select

    await record_policy_denial(
        workspace_id=None,
        agent_id=None,
        agent_name=None,
        adk_invocation_id=f"tamper-test-{uuid.uuid4().hex[:8]}",
        tool_name="query_companies",
        policy_id=None,
        engine="python",
        persona="CCB",
        reason="original reason",
    )

    # Simulate tampering: alter a stored row's `reason` after the fact,
    # without recomputing its hash -- exactly what a hash chain exists to
    # detect (an attacker/bug rewriting history without owning the chain).
    # Restored at the end of this test either way -- this table's chain is
    # real, shared, persisted state (record_policy_denial writes through
    # its own session, not a fixture-rolled-back one), so leaving a
    # dangling broken chain behind would fail every OTHER test/manual call
    # that verifies it afterward, not just this one.
    last_row = (
        await db_session.execute(select(PolicyEvent).order_by(PolicyEvent.seq.desc()).limit(1))
    ).scalar_one()
    original_reason = last_row.reason
    try:
        last_row.reason = "tampered reason"
        await db_session.commit()

        result = await verify_event_chain(db_session, PolicyEvent, _POLICY_HASH_FIELDS)
        assert result["verified"] is False
        assert result["broken_at_seq"] == last_row.seq
    finally:
        last_row.reason = original_reason
        await db_session.commit()

    restored = await verify_event_chain(db_session, PolicyEvent, _POLICY_HASH_FIELDS)
    assert restored["verified"] is True


# --- lineage endpoint --------------------------------------------------------


async def test_lineage_endpoint_consolidates_tool_calls_and_governance_events(client, unique_name, db_session):
    agent_resp = await client.post(
        "/api/agents",
        json={"name": unique_name("lineage_agent"), "base_instruction": "You are a helpful assistant."},
    )
    agent = agent_resp.json()

    tool_resp = await client.post(
        "/api/tools",
        json={
            "name": unique_name("lineage_tool"),
            "tool_type": "http_tool",
            "config": {"base_url": "https://example.com", "method": "GET", "path_template": "/x"},
            "input_schema": {"type": "object", "properties": {}},
        },
    )
    tool = tool_resp.json()

    adk_invocation_id = f"lineage-test-{uuid.uuid4().hex[:8]}"
    inv = InvocationLog(
        id=uuid.uuid4(),
        agent_id=uuid.UUID(agent["id"]),
        agent_version=1,
        workspace_id=uuid.UUID(agent["workspace_id"]) if agent.get("workspace_id") else None,
        status="success",
        latency_ms=100,
        adk_invocation_id=adk_invocation_id,
        transcript={"message": "What's Tesla's utilization?", "response_text": "42%."},
    )
    db_session.add(inv)
    await db_session.flush()

    db_session.add(
        ToolCallLog(
            invocation_id=inv.id,
            tool_id=uuid.UUID(tool["id"]),
            agent_name=agent["name"],
            call_index=0,
            status="success",
            latency_ms=20,
            input={"company": "Tesla"},
            output={"utilization_pct": 42},
        )
    )
    await db_session.commit()

    # A guardrail event and a policy denial recorded for the SAME
    # adk_invocation_id, via the real write paths (not hand-inserted), so
    # this also exercises the hash-chain writers end to end.
    next_seq, prev_hash, row_hash = await next_chain_link(
        db_session,
        GuardrailEvent,
        workspace_id=None,
        agent_id=str(agent["id"]),
        agent_name=agent["name"],
        adk_invocation_id=adk_invocation_id,
        direction="output",
        check_name="pii:email",
        action="redact",
        reason="Output contains an email address.",
        matched_preview="[redacted, never logged]",
        created_at=datetime.now(timezone.utc).isoformat(),
    )
    db_session.add(
        GuardrailEvent(
            seq=next_seq,
            workspace_id=None,
            agent_id=uuid.UUID(agent["id"]),
            agent_name=agent["name"],
            adk_invocation_id=adk_invocation_id,
            direction="output",
            check_name="pii:email",
            action="redact",
            reason="Output contains an email address.",
            matched_preview="[redacted, never logged]",
            prev_hash=prev_hash,
            row_hash=row_hash,
        )
    )
    await db_session.commit()

    await record_policy_denial(
        workspace_id=None,
        agent_id=uuid.UUID(agent["id"]),
        agent_name=agent["name"],
        adk_invocation_id=adk_invocation_id,
        tool_name="query_facility_data",
        policy_id=None,
        engine="python",
        persona="NON_GSG",
        reason="No coverage for this company.",
    )

    resp = await client.get(f"/api/debug/traces/{inv.id}/lineage")
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body["message"] == "What's Tesla's utilization?"
    assert body["response_text"] == "42%."
    assert len(body["grounding_tool_calls"]) == 1
    assert body["grounding_tool_calls"][0]["output"] == {"utilization_pct": 42}

    assert len(body["guardrail_events"]) == 1
    assert body["guardrail_events"][0]["check_name"] == "pii:email"
    assert body["guardrail_events"][0]["action"] == "redact"

    assert len(body["policy_events"]) == 1
    assert body["policy_events"][0]["tool_name"] == "query_facility_data"
    assert body["policy_events"][0]["persona"] == "NON_GSG"


async def test_lineage_endpoint_is_empty_but_not_broken_for_an_invocation_with_no_adk_invocation_id(
    client, unique_name, db_session
):
    """An invocation predating adk_invocation_id capture (or one from a
    still-'running' durable turn that crashed before it was set) has no
    reliable join key -- lineage degrades to just the tool calls, not an
    error."""
    agent_resp = await client.post(
        "/api/agents",
        json={"name": unique_name("lineage_no_key_agent"), "base_instruction": "You are a helpful assistant."},
    )
    agent = agent_resp.json()

    inv = InvocationLog(
        id=uuid.uuid4(),
        agent_id=uuid.UUID(agent["id"]),
        agent_version=1,
        workspace_id=uuid.UUID(agent["workspace_id"]) if agent.get("workspace_id") else None,
        status="success",
        latency_ms=10,
        adk_invocation_id=None,
        transcript={"message": "hi", "response_text": "hello"},
    )
    db_session.add(inv)
    await db_session.commit()

    resp = await client.get(f"/api/debug/traces/{inv.id}/lineage")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["guardrail_events"] == []
    assert body["policy_events"] == []
    assert body["grounding_tool_calls"] == []
