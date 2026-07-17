async def _create_agent(client, unique_name, name_prefix="agent"):
    resp = await client.post(
        "/api/agents",
        json={
            "name": unique_name(name_prefix),
            "description": "test agent",
            "base_instruction": "You are a test agent.",
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def test_create_agent_default_model_config(client, unique_name):
    agent = await _create_agent(client, unique_name)
    assert agent["status"] == "draft"
    assert agent["current_version"] == 1
    assert agent["model_config"]["model"] == "gemini-3.5-flash"
    assert agent["tools"] == []
    assert agent["skills"] == []


async def test_attach_tool_and_skill(client, unique_name):
    agent = await _create_agent(client, unique_name)

    tool_resp = await client.post(
        "/api/tools",
        json={
            "name": unique_name("tool"),
            "tool_type": "http_tool",
            "config": {"base_url": "https://example.com", "method": "GET", "path_template": "/x"},
            "input_schema": {"type": "object", "properties": {}},
        },
    )
    tool_id = tool_resp.json()["id"]

    skill_resp = await client.post(
        "/api/skills",
        json={"name": unique_name("skill"), "instruction_text": "Be concise."},
    )
    skill_id = skill_resp.json()["id"]

    resp = await client.post(f"/api/agents/{agent['id']}/tools", json={"tool_id": tool_id})
    assert resp.status_code == 204

    resp = await client.post(
        f"/api/agents/{agent['id']}/skills", json={"skill_id": skill_id, "attach_order": 0}
    )
    assert resp.status_code == 204

    resp = await client.get(f"/api/agents/{agent['id']}")
    body = resp.json()
    assert [t["id"] for t in body["tools"]] == [tool_id]
    assert [s["id"] for s in body["skills"]] == [skill_id]


async def test_publish_creates_version_and_bumps_status(client, unique_name):
    agent = await _create_agent(client, unique_name)

    resp = await client.post(f"/api/agents/{agent['id']}/publish", json={"published_by": "tester"})
    assert resp.status_code == 200, resp.text
    result = resp.json()
    assert result["status"] == "published"
    assert result["version"]["version"] == 1

    resp = await client.get(f"/api/agents/{agent['id']}")
    assert resp.json()["status"] == "published"
    assert resp.json()["current_version"] == 1

    # Republishing (e.g. after an edit) should bump the version.
    resp = await client.post(f"/api/agents/{agent['id']}/publish", json={"published_by": "tester"})
    assert resp.json()["version"]["version"] == 2

    resp = await client.get(f"/api/agents/{agent['id']}/versions")
    versions = resp.json()
    assert sorted(v["version"] for v in versions) == [1, 2]


async def test_circular_subagent_rejected(client, unique_name):
    agent_a = await _create_agent(client, unique_name, "agent_a")
    agent_b = await _create_agent(client, unique_name, "agent_b")

    # A -> B is fine.
    resp = await client.post(
        f"/api/agents/{agent_a['id']}/subagents", json={"child_agent_id": agent_b["id"]}
    )
    assert resp.status_code == 204

    # B -> A would close a cycle (A already delegates to B) and must be rejected.
    resp = await client.post(
        f"/api/agents/{agent_b['id']}/subagents", json={"child_agent_id": agent_a["id"]}
    )
    assert resp.status_code == 400

    # Self-reference is also rejected.
    resp = await client.post(
        f"/api/agents/{agent_a['id']}/subagents", json={"child_agent_id": agent_a["id"]}
    )
    assert resp.status_code == 400


async def test_transitive_circular_subagent_rejected(client, unique_name):
    a = await _create_agent(client, unique_name, "a")
    b = await _create_agent(client, unique_name, "b")
    c = await _create_agent(client, unique_name, "c")

    # a -> b -> c
    assert (
        await client.post(f"/api/agents/{a['id']}/subagents", json={"child_agent_id": b["id"]})
    ).status_code == 204
    assert (
        await client.post(f"/api/agents/{b['id']}/subagents", json={"child_agent_id": c["id"]})
    ).status_code == 204

    # c -> a would close a 3-hop cycle.
    resp = await client.post(f"/api/agents/{c['id']}/subagents", json={"child_agent_id": a["id"]})
    assert resp.status_code == 400


async def test_archive_agent(client, unique_name):
    agent = await _create_agent(client, unique_name)
    resp = await client.post(f"/api/agents/{agent['id']}/archive")
    assert resp.status_code == 200
    assert resp.json()["status"] == "archived"
