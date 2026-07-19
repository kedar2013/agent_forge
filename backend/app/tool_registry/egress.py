"""Outbound-network sandboxing for http_tool — the one tool type that makes
a caller-configured HTTP call to an arbitrary host (every other tool type
either has no network I/O of its own, or talks to a fixed, admin-configured
connection like a database). MCP servers (mcp_tool) make their OWN outbound
calls inside their own subprocess, outside this app's process boundary —
real network sandboxing for those needs OS-level controls (a container
network policy, an egress proxy in front of the MCP subprocess), not
anything achievable from here; deliberately not attempted by this module.
"""

from urllib.parse import urlparse

from app.config import get_settings


def _host_allowed(host: str, allowlist: list[str]) -> bool:
    host = host.lower()
    for entry in allowlist:
        if entry.startswith("."):
            if host == entry[1:] or host.endswith(entry):
                return True
        elif host == entry:
            return True
    return False


def check_egress_allowed(url: str, tool_config: dict) -> str | None:
    """Returns None if `url` is allowed, or a human-readable denial reason
    if not. A tool's own `config.egress_allowlist` (if set) is authoritative
    for that tool, overriding the platform-wide list entirely; otherwise
    falls back to `Settings.tool_egress_allowlist`. Both empty means
    unrestricted (today's behavior, unchanged for every tool that hasn't
    opted into either)."""
    allowlist = tool_config.get("egress_allowlist")
    if not allowlist:
        allowlist = get_settings().tool_egress_allowlist
    if not allowlist:
        return None

    host = urlparse(url).hostname
    if not host:
        return f"Could not determine a hostname to check from URL {url!r}."
    if _host_allowed(host, allowlist):
        return None
    return f"Host {host!r} is not in this tool's egress allowlist."
