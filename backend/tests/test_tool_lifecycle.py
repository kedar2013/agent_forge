import uuid
from types import SimpleNamespace

from app.agent_runtime.builder import _build_after_tool_callback, _load_live_tools
from app.tool_registry.egress import check_egress_allowed
from app.tool_registry.http_tool import HttpTool
from app.tool_registry.output_validation import validate_tool_output


# --- tool versioning ---------------------------------------------------------


async def test_create_tool_gets_version_1(client, unique_name):
    resp = await client.post(
        "/api/tools",
        json={
            "name": unique_name("versioned_tool"),
            "tool_type": "http_tool",
            "config": {"base_url": "https://example.com", "method": "GET", "path_template": "/x"},
            "input_schema": {"type": "object", "properties": {}},
        },
    )
    tool = resp.json()
    assert tool["current_version"] == 1

    versions = (await client.get(f"/api/tools/{tool['id']}/versions")).json()
    assert len(versions) == 1
    assert versions[0]["version"] == 1
    assert versions[0]["snapshot"]["config"]["base_url"] == "https://example.com"


async def test_updating_config_creates_a_new_version(client, unique_name):
    resp = await client.post(
        "/api/tools",
        json={
            "name": unique_name("versioned_tool"),
            "tool_type": "http_tool",
            "config": {"base_url": "https://example.com", "method": "GET", "path_template": "/x"},
            "input_schema": {"type": "object", "properties": {}},
        },
    )
    tool_id = resp.json()["id"]

    resp = await client.patch(
        f"/api/tools/{tool_id}",
        json={"config": {"base_url": "https://updated.example.com", "method": "GET", "path_template": "/y"}},
    )
    assert resp.status_code == 200
    assert resp.json()["current_version"] == 2

    versions = (await client.get(f"/api/tools/{tool_id}/versions")).json()
    assert [v["version"] for v in versions] == [2, 1]
    assert versions[0]["snapshot"]["config"]["base_url"] == "https://updated.example.com"
    assert versions[1]["snapshot"]["config"]["base_url"] == "https://example.com"


async def test_updating_only_name_does_not_create_a_new_version(client, unique_name):
    resp = await client.post(
        "/api/tools",
        json={
            "name": unique_name("versioned_tool"),
            "tool_type": "http_tool",
            "config": {"base_url": "https://example.com", "method": "GET", "path_template": "/x"},
            "input_schema": {"type": "object", "properties": {}},
        },
    )
    tool_id = resp.json()["id"]

    resp = await client.patch(f"/api/tools/{tool_id}", json={"name": unique_name("renamed_tool")})
    assert resp.status_code == 200
    assert resp.json()["current_version"] == 1

    versions = (await client.get(f"/api/tools/{tool_id}/versions")).json()
    assert len(versions) == 1


async def test_rollback_restores_a_past_version_as_a_new_version(client, unique_name):
    resp = await client.post(
        "/api/tools",
        json={
            "name": unique_name("versioned_tool"),
            "tool_type": "http_tool",
            "config": {"base_url": "https://original.example.com", "method": "GET", "path_template": "/x"},
            "input_schema": {"type": "object", "properties": {}},
        },
    )
    tool_id = resp.json()["id"]

    await client.patch(
        f"/api/tools/{tool_id}",
        json={"config": {"base_url": "https://broken.example.com", "method": "GET", "path_template": "/y"}},
    )

    resp = await client.post(f"/api/tools/{tool_id}/versions/1/rollback")
    assert resp.status_code == 200
    body = resp.json()
    assert body["current_version"] == 3
    assert body["config"]["base_url"] == "https://original.example.com"

    versions = (await client.get(f"/api/tools/{tool_id}/versions")).json()
    assert [v["version"] for v in versions] == [3, 2, 1]


async def test_rollback_to_nonexistent_version_404s(client, unique_name):
    resp = await client.post(
        "/api/tools",
        json={
            "name": unique_name("versioned_tool"),
            "tool_type": "http_tool",
            "config": {"base_url": "https://example.com", "method": "GET", "path_template": "/x"},
            "input_schema": {"type": "object", "properties": {}},
        },
    )
    tool_id = resp.json()["id"]

    resp = await client.post(f"/api/tools/{tool_id}/versions/99/rollback")
    assert resp.status_code == 404


# --- per-tool RBAC (access_scope + tool_grants) -----------------------------


async def test_restricted_tool_cannot_be_attached_without_a_grant(client, unique_name):
    tool_resp = await client.post(
        "/api/tools",
        json={
            "name": unique_name("restricted_tool"),
            "tool_type": "http_tool",
            "access_scope": "restricted",
            "config": {"base_url": "https://example.com", "method": "GET", "path_template": "/x"},
            "input_schema": {"type": "object", "properties": {}},
        },
    )
    tool_id = tool_resp.json()["id"]

    agent_resp = await client.post(
        "/api/agents",
        json={"name": unique_name("rbac_agent"), "base_instruction": "You are a helpful assistant."},
    )
    agent_id = agent_resp.json()["id"]

    resp = await client.post(f"/api/agents/{agent_id}/tools", json={"tool_id": tool_id})
    assert resp.status_code == 403


async def test_restricted_tool_can_be_attached_after_a_grant(client, unique_name, db_session):
    tool_resp = await client.post(
        "/api/tools",
        json={
            "name": unique_name("restricted_tool"),
            "tool_type": "http_tool",
            "access_scope": "restricted",
            "config": {"base_url": "https://example.com", "method": "GET", "path_template": "/x"},
            "input_schema": {"type": "object", "properties": {}},
        },
    )
    tool = tool_resp.json()

    agent_resp = await client.post(
        "/api/agents",
        json={"name": unique_name("rbac_agent"), "base_instruction": "You are a helpful assistant."},
    )
    agent = agent_resp.json()

    grant_resp = await client.post(f"/api/tools/{tool['id']}/grants", json={"agent_id": agent["id"]})
    assert grant_resp.status_code == 201
    assert grant_resp.json()["agent_id"] == agent["id"]

    attach_resp = await client.post(f"/api/agents/{agent['id']}/tools", json={"tool_id": tool["id"]})
    assert attach_resp.status_code == 204

    # Runtime defense-in-depth: the granted agent's live tool list includes
    # it (not just the attach-time check above).
    tools_rows = await _load_live_tools(db_session, uuid.UUID(agent["id"]), uuid.UUID(agent["workspace_id"]))
    assert any(t.id == uuid.UUID(tool["id"]) for t in tools_rows)

    # Revoke -> even though still attached, the live tool list excludes it
    # on the next build (defense in depth against a grant revoked after
    # attachment, per the runtime filter's own docstring).
    revoke_resp = await client.delete(f"/api/tools/{tool['id']}/grants/{agent['id']}")
    assert revoke_resp.status_code == 204
    tools_rows = await _load_live_tools(db_session, uuid.UUID(agent["id"]), uuid.UUID(agent["workspace_id"]))
    assert not any(t.id == uuid.UUID(tool["id"]) for t in tools_rows)


async def test_workspace_scope_tool_needs_no_grant(client, unique_name):
    """The default access_scope -- confirms restricting is opt-in, not a
    behavior change for every tool that doesn't ask for it."""
    tool_resp = await client.post(
        "/api/tools",
        json={
            "name": unique_name("open_tool"),
            "tool_type": "http_tool",
            "config": {"base_url": "https://example.com", "method": "GET", "path_template": "/x"},
            "input_schema": {"type": "object", "properties": {}},
        },
    )
    tool_id = tool_resp.json()["id"]
    assert tool_resp.json()["access_scope"] == "workspace"

    agent_resp = await client.post(
        "/api/agents",
        json={"name": unique_name("open_agent"), "base_instruction": "You are a helpful assistant."},
    )
    agent_id = agent_resp.json()["id"]

    resp = await client.post(f"/api/agents/{agent_id}/tools", json={"tool_id": tool_id})
    assert resp.status_code == 204


# --- egress allowlist (http_tool sandboxing) --------------------------------


def test_check_egress_allowed_permits_unrestricted_by_default():
    assert check_egress_allowed("https://anything.example.com/path", {}) is None


def test_check_egress_allowed_blocks_a_host_outside_the_tool_allowlist():
    config = {"egress_allowlist": ["api.allowed.com"]}
    reason = check_egress_allowed("https://not-allowed.com/path", config)
    assert reason is not None
    assert "not-allowed.com" in reason


def test_check_egress_allowed_permits_an_exact_match():
    config = {"egress_allowlist": ["api.allowed.com"]}
    assert check_egress_allowed("https://api.allowed.com/path", config) is None


def test_check_egress_allowed_permits_a_subdomain_wildcard():
    config = {"egress_allowlist": [".allowed.com"]}
    assert check_egress_allowed("https://api.allowed.com/path", config) is None
    assert check_egress_allowed("https://allowed.com/path", config) is None
    assert check_egress_allowed("https://evil-allowed.com/path", config) is not None


async def test_http_tool_blocks_disallowed_host_without_making_a_network_call():
    tool = HttpTool(
        name="blocked_tool",
        description="",
        input_schema={"type": "object", "properties": {}},
        config={
            "base_url": "https://not-on-the-list.com",
            "method": "GET",
            "path_template": "/x",
            "egress_allowlist": ["api.allowed.com"],
        },
        # No transport provided -- if egress checking didn't short-circuit
        # before _do_request, this would attempt a REAL network call and
        # likely error/hang rather than cleanly returning; getting a clean
        # {"error": ...} back proves the check ran first.
    )
    result = await tool.run_async(args={}, tool_context=SimpleNamespace(state={}))
    assert "error" in result
    assert "not-on-the-list.com" in result["error"]


# --- output schema validation -----------------------------------------------


def test_validate_tool_output_accepts_matching_response():
    schema = {"type": "object", "properties": {"temp_f": {"type": "number"}}, "required": ["temp_f"]}
    assert validate_tool_output({"temp_f": 72}, schema) is None


def test_validate_tool_output_rejects_malformed_response():
    schema = {"type": "object", "properties": {"temp_f": {"type": "number"}}, "required": ["temp_f"]}
    error = validate_tool_output({"wrong_key": "oops"}, schema)
    assert error is not None


def test_validate_tool_output_treats_a_malformed_schema_as_nothing_to_validate():
    assert validate_tool_output({"anything": True}, {"type": "not-a-real-type"}) is None


async def test_after_tool_callback_replaces_a_response_that_fails_output_schema():
    tool_row = SimpleNamespace(
        id=uuid.uuid4(),
        name="get_weather",
        output_schema={"type": "object", "properties": {"temp_f": {"type": "number"}}, "required": ["temp_f"]},
    )
    callback = _build_after_tool_callback([tool_row])
    tool = SimpleNamespace(name="get_weather")
    ctx = SimpleNamespace(state={}, invocation_id="turn-1", function_call_id="fc-1")

    result = await callback(tool, {}, ctx, {"unexpected_shape": True})
    assert result is not None
    assert "doesn't match its declared output_schema" in result["error"]


async def test_after_tool_callback_passes_through_a_valid_response():
    tool_row = SimpleNamespace(
        id=uuid.uuid4(),
        name="get_weather",
        output_schema={"type": "object", "properties": {"temp_f": {"type": "number"}}, "required": ["temp_f"]},
    )
    callback = _build_after_tool_callback([tool_row])
    tool = SimpleNamespace(name="get_weather")
    ctx = SimpleNamespace(state={}, invocation_id="turn-1", function_call_id="fc-1")

    result = await callback(tool, {}, ctx, {"temp_f": 72})
    assert result is None


async def test_after_tool_callback_is_a_noop_for_a_tool_with_no_output_schema():
    tool_row = SimpleNamespace(id=uuid.uuid4(), name="get_weather", output_schema=None)
    callback = _build_after_tool_callback([tool_row])
    tool = SimpleNamespace(name="get_weather")
    ctx = SimpleNamespace(state={}, invocation_id="turn-1", function_call_id="fc-1")

    result = await callback(tool, {}, ctx, {"anything": "goes"})
    assert result is None
