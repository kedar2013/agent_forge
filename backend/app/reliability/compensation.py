"""Saga/compensation: best-effort rollback of a failed multi-step turn.

Only ever runs for durable-execution-enabled agents, whose successfully
executed tool calls are already durably recorded (`ToolCallLog`, written
synchronously by `app.agent_runtime.builder`'s after_tool callback — see
that module's docstring). When a turn ultimately fails, this walks those
already-succeeded calls in REVERSE completion order and, for any whose tool
declares a `compensation_tool_id` in its own `config` (the same free-form
JSONB convention as `context_params`/`policy_id`), invokes that tool with
the original call's args — e.g. step 1 "reserved" something, step 4 failed,
so step 1's reservation gets released.

Deliberately simple, not a general saga engine: compensation tools run
OUTSIDE any live ADK invocation (there's no session left to run them in —
the turn already failed), so they get a minimal stand-in tool_context, and a
compensation tool is expected to be self-contained (no policy/context_params
dependency) — see `backend/scripts/seed_reliability_demo.py` for the
smallest possible worked example.
"""

import logging
import uuid

from sqlalchemy import select

from app.db import async_session_factory
from app.models.logs import ToolCallLog
from app.models.tools import Tool
from app.tool_registry.factory import build_tool

logger = logging.getLogger(__name__)


class _CompensationToolContext:
    """Minimal stand-in for ADK's real tool_context. Compensation tools run
    after the turn that produced them has already ended, so there is no
    live session/state to hand them — only tools that don't depend on
    policy/context_params injection (see module docstring) are valid
    compensation targets."""

    invocation_id = "compensation"
    function_call_id = None
    state: dict = {}


async def run_compensations(invocation_log_id: uuid.UUID) -> None:
    """Never raises — a failed compensation is recorded on the original
    ToolCallLog row, not propagated, since the turn has already failed and
    this is best-effort cleanup, not a new failure mode."""
    async with async_session_factory() as session:
        result = await session.execute(
            select(ToolCallLog)
            .where(
                ToolCallLog.invocation_id == invocation_log_id,
                ToolCallLog.status == "success",
                ToolCallLog.idempotency_key.isnot(None),
            )
            .order_by(ToolCallLog.call_index.desc())
        )
        successful_calls = list(result.scalars().all())
        if not successful_calls:
            return

        tool_ids = {c.tool_id for c in successful_calls if c.tool_id}
        tools_by_id: dict[uuid.UUID, Tool] = {}
        if tool_ids:
            tool_rows = (await session.execute(select(Tool).where(Tool.id.in_(tool_ids)))).scalars().all()
            tools_by_id = {t.id: t for t in tool_rows}

        for call in successful_calls:
            tool = tools_by_id.get(call.tool_id) if call.tool_id else None
            raw_compensation_id = tool.config.get("compensation_tool_id") if tool else None
            if not raw_compensation_id:
                continue

            call.compensation_status = "pending"
            await session.commit()

            try:
                compensation_tool_row = await session.get(Tool, uuid.UUID(str(raw_compensation_id)))
                if compensation_tool_row is None:
                    raise ValueError(f"compensation_tool_id {raw_compensation_id} not found")
                compensation_tool = build_tool(compensation_tool_row)
                await compensation_tool.run_async(args=dict(call.input or {}), tool_context=_CompensationToolContext())
                call.compensation_status = "compensated"
            except Exception:
                logger.exception(
                    "Compensation failed for tool_call_log %s (tool %s)", call.id, tool.name if tool else "?"
                )
                call.compensation_status = "failed"
            await session.commit()
