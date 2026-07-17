import httpx
import pytest

from app.tool_registry.http_tool import HttpTool
from app.tool_registry.mcp_tool import build_mcp_toolset
from app.tool_registry.retrieval_tool import _assert_safe_identifier
from app.tool_registry.sql_tool import SqlTool


def _mock_transport(handler):
    return httpx.MockTransport(handler)


async def test_http_tool_builds_url_and_query_params():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        return httpx.Response(200, json={"echo": dict(request.url.params)})

    tool = HttpTool(
        name="get_tool",
        description="test",
        input_schema={"type": "object", "properties": {"topic": {"type": "string"}}},
        config={"base_url": "https://api.example.com", "method": "GET", "path_template": "/lookup"},
        transport=_mock_transport(handler),
    )
    result = await tool.run_async(args={"topic": "octopuses"}, tool_context=None)
    assert result["status_code"] == 200
    assert result["body"]["echo"]["topic"] == "octopuses"
    assert captured["url"].startswith("https://api.example.com/lookup")


async def test_http_tool_path_template_substitution():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/status/204"
        return httpx.Response(204)

    tool = HttpTool(
        name="status_tool",
        description="test",
        input_schema={"type": "object", "properties": {"code": {"type": "string"}}},
        config={"base_url": "https://api.example.com", "method": "GET", "path_template": "/status/{code}"},
        transport=_mock_transport(handler),
    )
    result = await tool.run_async(args={"code": "204"}, tool_context=None)
    assert result["status_code"] == 204


async def test_http_tool_api_key_auth_header_from_env(monkeypatch):
    monkeypatch.setenv("TEST_TOOL_SECRET", "s3cr3t")
    seen_headers = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen_headers.update(request.headers)
        return httpx.Response(200, json={})

    tool = HttpTool(
        name="auth_tool",
        description="test",
        input_schema={"type": "object", "properties": {}},
        config={
            "base_url": "https://api.example.com",
            "method": "GET",
            "path_template": "/secure",
            "auth": {"type": "api_key", "header_name": "X-Api-Key", "secret_env": "TEST_TOOL_SECRET"},
        },
        transport=_mock_transport(handler),
    )
    await tool.run_async(args={}, tool_context=None)
    assert seen_headers.get("x-api-key") == "s3cr3t"


async def test_sql_tool_binds_params_not_string_interpolation(monkeypatch, sql_fixture_table):
    from app.config import get_settings

    monkeypatch.setenv("TEST_SQL_DB_URL", get_settings().database_url)

    tool = SqlTool(
        name="lookup",
        description="test",
        input_schema={"type": "object", "properties": {"name": {"type": "string"}}},
        config={
            "connection_env": "TEST_SQL_DB_URL",
            "query_template": f"SELECT * FROM agent_forge.{sql_fixture_table} WHERE name = :name",
        },
    )

    result = await tool.run_async(args={"name": "alpha"}, tool_context=None)
    assert result["row_count"] == 1
    assert result["rows"][0]["value"] == 1

    # An injection attempt is just a literal string value, not executable SQL —
    # it should safely match zero rows rather than altering the query.
    injection = "alpha'; DROP TABLE agent_forge." + sql_fixture_table + "; --"
    result = await tool.run_async(args={"name": injection}, tool_context=None)
    assert result["row_count"] == 0

    # Prove the table still exists and still has both rows.
    result = await tool.run_async(args={"name": "beta"}, tool_context=None)
    assert result["row_count"] == 1


def test_retrieval_tool_rejects_unsafe_identifier():
    with pytest.raises(ValueError):
        _assert_safe_identifier("documents; DROP TABLE x", "table")

    _assert_safe_identifier("public.documents", "table")  # should not raise


def test_mcp_toolset_builds_without_connecting():
    toolset = build_mcp_toolset(
        {"server_url": "https://mcp.example.com/mcp", "tool_name": "get_weather"}
    )
    assert toolset is not None
