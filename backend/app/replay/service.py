"""Deterministic replay — the "time-travel debugger" half of observability,
complementing the Debug Console's read-only waterfall
(app/debug_api/router.py._reconstruct_spans, which shows WHAT happened).
This re-runs a past invocation's agent trajectory, feeding each tool call
its ORIGINAL recorded output instead of re-executing the real tool, so a
past turn — especially a failed one — can be reproduced without depending
on live, possibly-since-changed external data (a different row in the
warehouse, a renamed entity, a flaky upstream API that has since recovered
or broken differently). Useful for two things: reproducing a bug to debug
it, and comparing before/after a prompt/config fix against the exact same
inputs the original failure saw.

Tool outputs are matched by (agent_name, tool_name), popped in the order
they were originally called — never by input args, since the whole point
is to force the same data regardless of what the model asks for on a
re-run. See app.agent_runtime.builder._build_before_tool_callback's
`replay_by_tool_name` docstring for what happens when the replayed
trajectory calls a given tool MORE times than the original recorded
(graceful fall-through to a real call, not an error).

Always rebuilds a fresh, never-cached agent tree from the ORIGINAL
recorded agent_version's snapshot (app.agent_runtime.builder.
build_replay_agent) — replaying against whatever is live/published NOW
would defeat the entire point of reproducing what actually happened THEN.
"""

import uuid
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Any

from google.adk.sessions import InMemorySessionService
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent_runtime.builder import build_replay_agent, close_agent_toolsets
from app.models.agents import AgentVersion
from app.models.logs import InvocationLog, ToolCallLog
from app.models.tools import Tool
from app.observability.pricing import estimate_cost_usd

_REPLAY_APP_NAME = "agent_forge_replay"
_REPLAY_USER_ID = "debug-replay"


class ReplayError(Exception):
    """Raised for a replay precondition that isn't the caller's fault to
    retry (missing recording, agent version pruned, etc) — the router
    translates this straight to a 422."""


@dataclass
class ReplayResult:
    invocation_id: uuid.UUID
    original_response_text: str
    original_status: str
    replayed_response_text: str
    replayed_status: str
    replayed_error_message: str | None
    replayed_tool_calls: list[dict[str, Any]] = field(default_factory=list)
    replayed_events: list[dict[str, Any]] = field(default_factory=list)
    replayed_input_tokens: int | None = None
    replayed_output_tokens: int | None = None
    replayed_estimated_cost_usd: float | None = None
    # How many of the originally-recorded tool calls the replay actually
    # consumed from the queue vs. how many were recorded in total — a full
    # match (matched == total) means every tool call in the replayed run
    # was fed a real historical output; a partial match means the
    # trajectory diverged (called fewer/different tools than before) and
    # some recorded outputs were never used, or the replay ran past what
    # was recorded and made at least one REAL tool call instead.
    matched_tool_call_count: int = 0
    total_recorded_tool_call_count: int = 0


async def _load_replay_map(
    db: AsyncSession, invocation_id: uuid.UUID
) -> tuple[dict[str, dict[str, deque]], int]:
    result = await db.execute(
        select(ToolCallLog, Tool.name)
        .outerjoin(Tool, Tool.id == ToolCallLog.tool_id)
        .where(ToolCallLog.invocation_id == invocation_id, ToolCallLog.status == "success")
        .order_by(ToolCallLog.call_index.asc().nulls_last(), ToolCallLog.created_at.asc())
    )
    replay_map: dict[str, dict[str, deque]] = defaultdict(lambda: defaultdict(deque))
    total = 0
    for call, tool_name in result:
        if tool_name is None or call.agent_name is None:
            # Tool since deleted (tool_id FK went nowhere), or a row from
            # before agent_name was captured — nothing reliable to key a
            # replay slot on, so this one call can't be replayed. Excluded
            # rather than guessed at; the replay just calls the real tool
            # for it (or the model may not call it at all this time).
            continue
        replay_map[call.agent_name][tool_name].append(call.output)
        total += 1
    return replay_map, total


async def replay_invocation(
    db: AsyncSession, invocation_id: uuid.UUID, workspace_id: uuid.UUID | None
) -> ReplayResult:
    # Imported here, not at module level: playground_api.router imports
    # from agent_runtime.builder (which this module also imports from),
    # and a top-level import back into playground_api risks a circular
    # import for no real benefit — same "reuse an internal helper from a
    # sibling module" convention scil_api/router.py already uses for
    # chat_api.router's _DEFAULT_CHAT_STATE.
    from app.playground_api.router import _execute_run

    inv = await db.get(InvocationLog, invocation_id)
    if inv is None or inv.workspace_id != workspace_id:
        raise ReplayError("Invocation not found")
    if inv.agent_id is None:
        raise ReplayError("This invocation has no associated agent to rebuild")

    message = (inv.transcript or {}).get("message")
    if not message:
        raise ReplayError("This invocation has no recorded input message to replay")

    version_row = await db.scalar(
        select(AgentVersion).where(AgentVersion.agent_id == inv.agent_id, AgentVersion.version == inv.agent_version)
    )
    if version_row is None:
        raise ReplayError(f"Agent version {inv.agent_version} is no longer available to rebuild")

    replay_map, total_recorded = await _load_replay_map(db, invocation_id)
    model = (version_row.snapshot.get("model_config") or {}).get("model", "gemini-3.5-flash")

    adk_agent = await build_replay_agent(db, inv.agent_id, inv.agent_version, replay_map)
    try:
        session_service = InMemorySessionService()
        session_id = f"replay-{uuid.uuid4()}"
        await session_service.create_session(
            app_name=_REPLAY_APP_NAME, user_id=_REPLAY_USER_ID, session_id=session_id, state={}
        )
        outcome = await _execute_run(
            adk_agent=adk_agent,
            model=model,
            session_service=session_service,
            app_name=_REPLAY_APP_NAME,
            user_id=_REPLAY_USER_ID,
            session_id=session_id,
            message=message,
            state_delta=None,
        )
    finally:
        await close_agent_toolsets(adk_agent)

    remaining = sum(len(queue) for by_tool in replay_map.values() for queue in by_tool.values())

    return ReplayResult(
        invocation_id=invocation_id,
        original_response_text=(inv.transcript or {}).get("response_text", ""),
        original_status=inv.status,
        replayed_response_text="".join(outcome.final_text_parts),
        replayed_status=outcome.status,
        replayed_error_message=outcome.error_message,
        replayed_tool_calls=outcome.tool_call_records,
        replayed_events=outcome.events,
        replayed_input_tokens=outcome.input_tokens,
        replayed_output_tokens=outcome.output_tokens,
        replayed_estimated_cost_usd=estimate_cost_usd(model, outcome.input_tokens, outcome.output_tokens),
        matched_tool_call_count=total_recorded - remaining,
        total_recorded_tool_call_count=total_recorded,
    )
