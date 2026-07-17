"""Root-cause-analysis helpers shared by playground_api (where failures
happen and get captured) and debug_api (where they get explained back to a
developer). Kept separate from playground_api/router.py so the
classification rules can be read/tested on their own.
"""

import json
from typing import Any

# Cap on the JSON-serialized size of a tool call's stored input/output.
# RCA needs to SEE the shape/error of a payload, not necessarily every byte
# of a large legitimate response (e.g. a multi-year price history dump).
_MAX_PAYLOAD_CHARS = 4000


def cap_payload(value: Any) -> Any:
    """Returns `value` unchanged if it serializes small enough to store as-is,
    else a truncated preview marker — never silently dropped."""
    try:
        text = json.dumps(value, default=str)
    except TypeError:
        text = str(value)
    if len(text) <= _MAX_PAYLOAD_CHARS:
        return value
    return {"_truncated": True, "preview": text[:_MAX_PAYLOAD_CHARS]}


def tool_call_error(output: Any) -> str | None:
    """MCP tool outputs are shaped like {"content": [...], "isError": bool,
    "structuredContent": {...}} (see mcp_servers/*.py + tool_registry/
    mcp_tool.py). A failed tool call still comes back as a normal
    FunctionResponse from ADK's point of view — nothing raises — so without
    this check a tool that failed looked IDENTICAL to one that succeeded
    anywhere downstream (tool_call_log, the debug console, usage
    dashboards). Non-MCP tool types (http_tool etc.) don't use this
    envelope and always return None here — their failures already surface
    as a raised exception that aborts the whole turn."""
    if isinstance(output, dict) and output.get("isError"):
        content = output.get("content")
        if isinstance(content, list) and content and isinstance(content[0], dict):
            text = content[0].get("text")
            if isinstance(text, str) and text.strip():
                return text
        return "Tool reported an error"
    return None


# (category, (headline, suggested_fix)) — shown verbatim in the Debug
# Console's RCA panel. "recovered_*" variants apply when the turn ultimately
# SUCCEEDED after a self-heal — worth surfacing even though nothing is
# broken right now, since repeated recoveries on the same agent are a signal.
RCA_SUGGESTIONS: dict[str, tuple[str, str]] = {
    "tool_error": (
        "A tool call failed and the turn could not recover.",
        "Check the failing tool call's input/output below for the exact error "
        "(bad credentials, invalid params, upstream API down). Fix the tool's "
        "config or the calling agent's instruction, then re-test in the Playground.",
    ),
    "recovered_tool_error": (
        "A tool call failed, but the turn still completed successfully.",
        "The model likely answered without that tool's result. Check the failing "
        "call's output below — if this keeps happening on the same tool, it's "
        "worth fixing even though this particular turn recovered.",
    ),
    "agent_handoff_failure": (
        "The orchestrator tried to call a specialist's tool directly instead of "
        "transferring to it, and the automatic same-turn retry also failed.",
        "This is usually a routing-instruction problem — review the orchestrator "
        "agent's instruction for ambiguous or missing routing guidance to the "
        "specialist it should have transferred to.",
    ),
    "recovered_agent_handoff_failure": (
        "The orchestrator initially tried to call a specialist's tool directly "
        "instead of transferring — it self-healed on an automatic retry.",
        "No action needed for this turn. If this recurs often on the same "
        "orchestrator, tighten its routing instructions to reduce the retry rate.",
    ),
    "stale_session": (
        "This session referenced an agent or session-state key that no longer "
        "exists (e.g. after a config change), and the automatic session reset "
        "also failed.",
        "Ask the user to start a new conversation. If this affects many "
        "sessions at once, check whether an agent this session depended on was "
        "recently archived, renamed, or had its expected state keys changed.",
    ),
    "recovered_stale_session": (
        "This session referenced stale agent/session-state — it self-healed by "
        "resetting the session and replaying the message.",
        "No action needed; prior conversation history for this session was "
        "dropped as part of the reset.",
    ),
    "rate_limited": (
        "The underlying LLM API call was rate-limited or the quota was "
        "exhausted.",
        "Check the provider's (Gemini or Claude, depending on this agent's "
        "model) quota/rate limits for this project. Consider backoff, a "
        "lower-traffic model, or spreading load across agents.",
    ),
    "timeout": (
        "The turn took too long and timed out.",
        "Check per-tool-call latency in the waterfall below for the slow step — "
        "often one MCP tool call or an unusually long multi-hop transfer chain.",
    ),
    "llm_safety_block": (
        "The model refused to respond — this usually means a safety/content "
        "filter was triggered.",
        "Review the user's message and the agent's instruction text for content "
        "that may be tripping the model provider's safety filters.",
    ),
    "unknown_error": (
        "The turn failed with an error that doesn't match a known pattern.",
        "Check the raw error message below for details.",
    ),
}


def classify_error(
    *,
    status: str,
    error_message: str | None,
    events: list[dict[str, Any]],
    tool_call_records: list[dict[str, Any]],
) -> str | None:
    """Buckets a finished turn into an RCA category. Returns None for a
    clean success with no error and no self-heal — the common case, not
    worth flagging in the trace list."""
    had_hallucination_retry = any(e.get("event_type") == "orchestrator_hallucination_retry" for e in events)
    had_stale_session_retry = any(e.get("event_type") == "stale_session_retry" for e in events)
    had_tool_error = any(tc.get("status") == "error" for tc in tool_call_records)

    if status == "success":
        if had_stale_session_retry:
            return "recovered_stale_session"
        if had_hallucination_retry:
            return "recovered_agent_handoff_failure"
        if had_tool_error:
            return "recovered_tool_error"
        return None

    msg = error_message or ""
    if "Context variable not found" in msg:
        return "stale_session"
    if "not found" in msg and "Available tools" in msg:
        return "agent_handoff_failure"
    if had_tool_error:
        return "tool_error"
    lower = msg.lower()
    if "429" in msg or "resource_exhausted" in lower or "rate limit" in lower or "quota" in lower:
        return "rate_limited"
    if "timeout" in lower or "timed out" in lower or "deadline" in lower:
        return "timeout"
    if "safety" in lower or "blocked" in lower or "recitation" in lower:
        return "llm_safety_block"
    return "unknown_error"
