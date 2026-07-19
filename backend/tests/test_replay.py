import uuid
from collections import deque
from types import SimpleNamespace

from app.agent_runtime.builder import _build_before_tool_callback
from app.models.logs import InvocationLog, ToolCallLog
from app.replay.service import ReplayError, _load_replay_map, replay_invocation


def _fake_tool_context(invocation_id: str = "turn-1") -> SimpleNamespace:
    return SimpleNamespace(state={}, invocation_id=invocation_id, function_call_id="fc-1")


# --- before_tool_callback replay interception (no DB, no LLM) --------------


async def test_replay_queue_returns_recorded_output_instead_of_real_call():
    replay_by_tool_name = {"get_weather": deque([{"temp_f": 72}])}
    callback = _build_before_tool_callback([], {}, replay_by_tool_name=replay_by_tool_name)
    tool = SimpleNamespace(name="get_weather")

    result = await callback(tool, {"city": "some city the model asked about this time"}, _fake_tool_context())

    assert result == {"temp_f": 72}
    # Popped -- a second call to the same tool this replay falls through
    # (queue now empty) rather than replaying the same output twice.
    assert len(replay_by_tool_name["get_weather"]) == 0


async def test_replay_falls_through_to_real_execution_when_queue_exhausted():
    replay_by_tool_name = {"get_weather": deque()}  # already exhausted
    callback = _build_before_tool_callback([], {}, replay_by_tool_name=replay_by_tool_name)
    tool = SimpleNamespace(name="get_weather")

    # No policy/context_params configured for this tool -> normal (non-replay)
    # path returns None, meaning "let the real tool run".
    result = await callback(tool, {}, _fake_tool_context())
    assert result is None


async def test_replay_ignores_tools_with_no_recorded_queue():
    replay_by_tool_name = {"get_weather": deque([{"temp_f": 72}])}
    callback = _build_before_tool_callback([], {}, replay_by_tool_name=replay_by_tool_name)
    other_tool = SimpleNamespace(name="some_other_tool")

    result = await callback(other_tool, {}, _fake_tool_context())
    assert result is None
    assert len(replay_by_tool_name["get_weather"]) == 1  # untouched


async def test_transfer_to_agent_is_never_intercepted_by_replay():
    # transfer_to_agent is deliberately excluded from ToolCallLog (see
    # builder._build_after_tool_callback), so it should never appear in a
    # replay_by_tool_name map -- confirm the hop-limit logic underneath
    # still runs normally when replay is active but doesn't cover this tool.
    replay_by_tool_name: dict = {}
    callback = _build_before_tool_callback([], {}, replay_by_tool_name=replay_by_tool_name)
    tool = SimpleNamespace(name="transfer_to_agent")

    result = await callback(tool, {"agent_name": "specialist"}, _fake_tool_context())
    assert result is None  # first transfer this turn -- under the hop cap


# --- _load_replay_map (real DB, no LLM) -------------------------------------


async def test_load_replay_map_groups_by_agent_and_tool_in_call_order(client, unique_name, db_session):
    agent_resp = await client.post(
        "/api/agents",
        json={"name": unique_name("replay_map_agent"), "base_instruction": "You are a helpful assistant."},
    )
    agent = agent_resp.json()

    tool_resp = await client.post(
        "/api/tools",
        json={
            "name": unique_name("replay_map_tool"),
            "tool_type": "http_tool",
            "config": {"base_url": "https://example.com", "method": "GET", "path_template": "/x"},
            "input_schema": {"type": "object", "properties": {}},
        },
    )
    tool = tool_resp.json()

    inv = InvocationLog(
        id=uuid.uuid4(),
        agent_id=uuid.UUID(agent["id"]),
        agent_version=1,
        status="success",
        latency_ms=100,
        transcript={"message": "what's the weather", "response_text": "It's sunny."},
    )
    db_session.add(inv)
    await db_session.flush()
    db_session.add_all(
        [
            ToolCallLog(
                invocation_id=inv.id,
                tool_id=uuid.UUID(tool["id"]),
                agent_name=agent["name"],
                call_index=0,
                status="success",
                latency_ms=50,
                output={"temp_f": 72},
            ),
            ToolCallLog(
                invocation_id=inv.id,
                tool_id=uuid.UUID(tool["id"]),
                agent_name=agent["name"],
                call_index=1,
                status="success",
                latency_ms=50,
                output={"temp_f": 75},
            ),
            # A failed call must never be replayed as if it succeeded.
            ToolCallLog(
                invocation_id=inv.id,
                tool_id=uuid.UUID(tool["id"]),
                agent_name=agent["name"],
                call_index=2,
                status="error",
                latency_ms=10,
                output=None,
                error_message="boom",
            ),
        ]
    )
    await db_session.commit()

    replay_map, total = await _load_replay_map(db_session, inv.id)

    assert total == 2  # the error row is excluded
    queue = replay_map[agent["name"]][tool["name"]]
    assert list(queue) == [{"temp_f": 72}, {"temp_f": 75}]  # call_index order preserved


async def test_replay_invocation_rejects_missing_message(client, unique_name, db_session):
    agent_resp = await client.post(
        "/api/agents",
        json={"name": unique_name("replay_no_message_agent"), "base_instruction": "You are a helpful assistant."},
    )
    agent = agent_resp.json()

    inv = InvocationLog(
        id=uuid.uuid4(),
        agent_id=uuid.UUID(agent["id"]),
        agent_version=1,
        status="success",
        latency_ms=10,
        transcript=None,  # nothing to replay
    )
    db_session.add(inv)
    await db_session.commit()

    try:
        await replay_invocation(db_session, inv.id, None)
        assert False, "expected ReplayError"
    except ReplayError as exc:
        assert "recorded input message" in str(exc)


async def test_replay_invocation_rejects_pruned_agent_version(client, unique_name, db_session):
    agent_resp = await client.post(
        "/api/agents",
        json={"name": unique_name("replay_no_version_agent"), "base_instruction": "You are a helpful assistant."},
    )
    agent = agent_resp.json()

    inv = InvocationLog(
        id=uuid.uuid4(),
        agent_id=uuid.UUID(agent["id"]),
        agent_version=999,  # never published
        status="success",
        latency_ms=10,
        transcript={"message": "hi", "response_text": "hello"},
    )
    db_session.add(inv)
    await db_session.commit()

    try:
        await replay_invocation(db_session, inv.id, None)
        assert False, "expected ReplayError"
    except ReplayError as exc:
        assert "no longer available" in str(exc)


# --- full stack, via the real HTTP endpoint ---------------------------------


async def test_replay_endpoint_end_to_end_with_a_published_agent_and_recorded_tool_call(
    client, unique_name, db_session
):
    """Exercises POST /debug/traces/{id}/replay against a REAL published
    agent with a real tool attached and one synthetic recorded ToolCallLog
    (standing in for a real prior run) -- confirms the whole wire-up
    (auth, agent rebuild from the published snapshot, replay-map loading,
    tool interception) end to end. The final answer synthesis is a real
    LLM call (ADK always calls the model, even to just relay a tool's
    result back in words) -- if the environment's model quota is
    exhausted, `replayed_status` legitimately comes back "error" rather
    than "success", so this only asserts on what's true either way: the
    endpoint doesn't 500, and the recorded tool call was correctly loaded
    and offered to the replay."""
    agent_resp = await client.post(
        "/api/agents",
        json={
            "name": unique_name("replay_e2e_agent"),
            "base_instruction": "You are a helpful weather assistant. Always call get_weather for weather questions.",
        },
    )
    agent = agent_resp.json()

    tool_resp = await client.post(
        "/api/tools",
        json={
            "name": "get_weather",
            "tool_type": "http_tool",
            "description": "Gets the current weather for a city.",
            "config": {"base_url": "https://example.invalid", "method": "GET", "path_template": "/weather"},
            "input_schema": {
                "type": "object",
                "properties": {"city": {"type": "string"}},
                "required": ["city"],
            },
        },
    )
    tool = tool_resp.json()

    attach_resp = await client.post(f"/api/agents/{agent['id']}/tools", json={"tool_id": tool["id"]})
    assert attach_resp.status_code == 204, attach_resp.text

    publish_resp = await client.post(f"/api/agents/{agent['id']}/publish", json={})
    assert publish_resp.status_code == 200, publish_resp.text
    published_version = publish_resp.json()["version"]["version"]

    inv = InvocationLog(
        id=uuid.uuid4(),
        agent_id=uuid.UUID(agent["id"]),
        agent_version=published_version,
        workspace_id=uuid.UUID(agent["workspace_id"]) if agent.get("workspace_id") else None,
        status="success",
        latency_ms=100,
        transcript={
            "message": "What's the weather in Paris?",
            "response_text": "It's 72F and sunny in Paris.",
        },
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
            latency_ms=50,
            input={"city": "Paris"},
            output={"temp_f": 72, "conditions": "sunny"},
        )
    )
    await db_session.commit()

    resp = await client.post(f"/api/debug/traces/{inv.id}/replay")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["invocation_id"] == str(inv.id)
    assert body["original_response_text"] == "It's 72F and sunny in Paris."
    assert body["total_recorded_tool_call_count"] == 1
    assert body["replayed_status"] in ("success", "error")
