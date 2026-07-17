"""Stateless read of the scratchpad slots self_healing_sql_tool writes to
when called with a `scratchpad_slot` argument (see that module's
docstring for the full query-decomposition pattern).

A synthesizer agent gets exactly this one tool — never a SQL execution
tool of its own — so it can only ever read already-fetched results, not
issue new queries. Deliberately a tool call (not ADK `{state_key}`
instruction templating, which this app does use elsewhere — see
chat_api/router.py's `_DEFAULT_CHAT_STATE`): templating raises a hard
`KeyError` if a referenced key was never set, which would break this
agent on any question that only needed two sub-queries out of the three
available slots. A tool can just `.get(..., None)` and skip whatever
wasn't used.
"""

from typing import Any

from app.tool_registry.base import ConfigDrivenTool

SCRATCHPAD_SLOTS = ("scratchpad_1", "scratchpad_2", "scratchpad_3")


class ReadScratchpadTool(ConfigDrivenTool):
    """No config needed — always reads the same fixed, small set of slot
    names any self_healing_sql_tool call may have written to."""

    def __init__(self, *, name: str, description: str, input_schema: dict, config: dict) -> None:
        super().__init__(name=name, description=description, input_schema=input_schema)

    async def run_async(self, *, args: dict[str, Any], tool_context) -> Any:
        results = {slot: tool_context.state.get(slot) for slot in SCRATCHPAD_SLOTS}
        filled = {slot: value for slot, value in results.items() if value is not None}
        if not filled:
            return {"error": "The scratchpad is empty — no sub-query results have been stored yet."}
        return filled
