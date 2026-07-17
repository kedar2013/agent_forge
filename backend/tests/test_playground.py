import uuid


async def test_playground_run_end_to_end(client, unique_name):
    skill_resp = await client.post(
        "/api/skills",
        json={"name": unique_name("skill"), "instruction_text": "Always mention the word 'tool-result' in your answer."},
    )
    skill_id = skill_resp.json()["id"]

    # api.github.com/zen is a trivial, highly-reliable public GET endpoint —
    # used here purely to prove the real ADK + Gemini + tool-calling loop
    # works end to end, not to exercise HTTP semantics (that's covered by
    # the hermetic MockTransport tests in test_tool_registry.py).
    tool_resp = await client.post(
        "/api/tools",
        json={
            "name": unique_name("tool"),
            "tool_type": "http_tool",
            "description": "Fetches a random one-line saying. Takes no arguments.",
            "config": {"base_url": "https://api.github.com", "method": "GET", "path_template": "/zen"},
            "input_schema": {"type": "object", "properties": {}},
        },
    )
    tool_id = tool_resp.json()["id"]

    agent_resp = await client.post(
        "/api/agents",
        json={
            "name": unique_name("playground_agent"),
            "base_instruction": (
                "You are a test agent. Always call the lookup tool (it takes no arguments) "
                "before answering, then mention what it returned."
            ),
        },
    )
    agent = agent_resp.json()

    await client.post(f"/api/agents/{agent['id']}/skills", json={"skill_id": skill_id, "attach_order": 0})
    await client.post(f"/api/agents/{agent['id']}/tools", json={"tool_id": tool_id})

    resp = await client.post(
        "/api/playground/run",
        json={"agent_id": agent["id"], "message": "Call your tool now and tell me what it says."},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["response_text"]
    assert len(body["tool_calls"]) >= 1
    assert "status_code" in body["tool_calls"][0]["output"]


async def test_playground_reuses_session_across_turns(client, unique_name):
    """Regression test: the playground must not reset session state on every
    call, or multi-turn chat in the frontend would lose context each turn."""
    agent_resp = await client.post(
        "/api/agents",
        json={
            "name": unique_name("multiturn_agent"),
            "base_instruction": "You are a helpful assistant with a good memory for details the user shares.",
        },
    )
    agent_id = agent_resp.json()["id"]
    session_id = f"test-session-{uuid.uuid4()}"

    first = await client.post(
        "/api/playground/run",
        json={
            "agent_id": agent_id,
            "session_id": session_id,
            "message": "Remember this secret code: 'purple-otter-42'. Just acknowledge it briefly.",
        },
    )
    assert first.status_code == 200, first.text

    second = await client.post(
        "/api/playground/run",
        json={
            "agent_id": agent_id,
            "session_id": session_id,
            "message": "What was the secret code I just told you? Reply with only the code.",
        },
    )
    assert second.status_code == 200, second.text
    assert "purple-otter-42" in second.json()["response_text"]
