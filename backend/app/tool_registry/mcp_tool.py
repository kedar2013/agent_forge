import os

from google.adk.tools.mcp_tool import McpToolset
from google.adk.tools.mcp_tool.mcp_session_manager import (
    StdioConnectionParams,
    StreamableHTTPConnectionParams,
)
from mcp import StdioServerParameters


def build_mcp_toolset(config: dict) -> McpToolset:
    """Binds to a single named tool on an MCP server — either a remote HTTP
    server or a local one launched as a subprocess over stdio.

    `config` shape (HTTP transport, the default):
        {
          "transport": "http",                       # optional, default
          "server_url": "https://mcp.example.com/mcp",
          "tool_name": "get_weather",
          "auth_header_env": "MCP_AUTH_TOKEN"          # optional bearer token env var
        }

    `config` shape (stdio transport — a locally-run MCP server process):
        {
          "transport": "stdio",
          "command": "python",
          "args": ["mcp_servers/weather_server.py"],
          "tool_name": "get_forecast",
          "env": {"SOME_VAR": "value"}                 # optional, merged with os.environ
        }

    One `tools` row == one callable tool, so the toolset is filtered down to
    just `tool_name` even though the upstream MCP server may expose many.
    """
    transport = config.get("transport", "http")

    if transport == "stdio":
        env = {**os.environ, **config.get("env", {})}
        connection_params = StdioConnectionParams(
            server_params=StdioServerParameters(
                command=config["command"], args=config.get("args", []), env=env
            ),
            timeout=config.get("timeout", 30.0),
        )
    else:
        headers = {}
        if config.get("auth_header_env"):
            token = os.environ.get(config["auth_header_env"], "")
            headers["Authorization"] = f"Bearer {token}"
        connection_params = StreamableHTTPConnectionParams(url=config["server_url"], headers=headers)

    return McpToolset(connection_params=connection_params, tool_filter=[config["tool_name"]])
