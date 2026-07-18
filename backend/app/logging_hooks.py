import asyncio
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent_runtime.builder import _safe_agent_name
from app.audit_hash import compute_row_hash
from app.db import async_session_factory
from app.models.agents import Agent
from app.models.logs import AgentEventLog, ConfigAuditLog, InvocationLog, ToolCallLog
from app.models.tools import Tool


async def write_audit_log(
    db: AsyncSession,
    *,
    entity_type: str,
    entity_id: uuid.UUID,
    action: str,
    actor: str | None,
    diff: dict | None = None,
    workspace_id: uuid.UUID | None = None,
) -> None:
    """Synchronous (awaited inline) audit trail write for a config mutation.

    Called from within the same request/transaction as the mutation itself —
    correctness matters more than latency here, unlike invocation logging.

    Each row's hash covers its own fields plus the previous row's hash (a hash
    chain), so tampering with or deleting a past row is detectable. The
    `SELECT ... FOR UPDATE` on the last row serializes concurrent writers so
    two requests can't compute the same `seq`/`prev_hash` and silently fork
    the chain.
    """
    last_row = (
        await db.execute(
            select(ConfigAuditLog).order_by(ConfigAuditLog.seq.desc()).limit(1).with_for_update()
        )
    ).scalar_one_or_none()
    next_seq = (last_row.seq + 1) if last_row else 1
    prev_hash = last_row.row_hash if last_row else None
    created_at = datetime.now(timezone.utc)

    row_hash = compute_row_hash(
        prev_hash=prev_hash,
        entity_type=entity_type,
        entity_id=str(entity_id),
        action=action,
        actor=actor,
        diff=diff,
        created_at_iso=created_at.isoformat(),
    )

    db.add(
        ConfigAuditLog(
            seq=next_seq,
            workspace_id=workspace_id,
            entity_type=entity_type,
            entity_id=entity_id,
            action=action,
            actor=actor,
            diff=diff,
            prev_hash=prev_hash,
            row_hash=row_hash,
            created_at=created_at,
        )
    )


def log_invocation_fire_and_forget(**kwargs: Any) -> None:
    """Fire-and-forget invocation_log write — never blocks the caller's response."""
    asyncio.create_task(_write_invocation_log(**kwargs))


async def start_durable_run(
    *,
    agent_id: uuid.UUID | None,
    agent_version: int,
    workspace_id: uuid.UUID | None,
    adk_session_id: str,
    adk_user_id: str,
    adk_app_name: str,
    invoked_by: str | None,
) -> uuid.UUID:
    """Eagerly, SYNCHRONOUSLY (awaited, unlike every other write in this
    file) inserts a 'running' InvocationLog row before this turn's first
    `runner.run_async()` call — the durable checkpoint anchor a
    crash-recovery resume (`app/reliability_api/router.py`) needs. Only
    called for durable-execution-enabled agents running on a DB-backed
    session (see `playground_api/router.py`'s `_run_turn`); every other
    agent keeps today's insert-once-at-the-end behavior via
    `log_invocation_fire_and_forget`."""
    async with async_session_factory() as session:
        invocation = InvocationLog(
            agent_id=agent_id,
            agent_version=agent_version,
            workspace_id=workspace_id,
            trace_id=adk_session_id,
            status="running",
            latency_ms=0,
            adk_session_id=adk_session_id,
            adk_user_id=adk_user_id,
            adk_app_name=adk_app_name,
            invoked_by=invoked_by,
        )
        session.add(invocation)
        await session.commit()
        return invocation.id


async def set_durable_attempt(invocation_log_id: uuid.UUID, adk_invocation_id: str) -> None:
    """Overwrites the 'currently live attempt' pointer before each
    `runner.run_async()` call for this turn (the initial attempt, or any
    SCIL retry) — always points at whichever attempt is actually in flight,
    so a crash mid-turn leaves the RIGHT id for a resume to continue from."""
    async with async_session_factory() as session:
        invocation = await session.get(InvocationLog, invocation_log_id)
        if invocation is not None:
            invocation.adk_invocation_id = adk_invocation_id
            await session.commit()


async def _write_invocation_log(
    *,
    agent_id: uuid.UUID | None,
    agent_version: int,
    workspace_id: uuid.UUID | None,
    trace_id: str | None,
    status: str,
    latency_ms: int,
    invocation_log_id: uuid.UUID | None = None,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    estimated_cost_usd: float | None = None,
    error_message: str | None = None,
    invoked_by: str | None = None,
    transcript: dict | None = None,
    tool_calls: list[dict] | None = None,
    events: list[dict] | None = None,
    resolved_author: str | None = None,
    otel_trace_id: str | None = None,
    error_category: str | None = None,
) -> None:
    """`agent_id`/`agent_version` as passed in are whichever agent was
    actually INVOKED by the caller (e.g. the chat root orchestrator) — for a
    request that transferred to a specialist, that's not who did the real
    work. `resolved_author` is the ADK-sanitized name of whichever agent
    authored the final response (see _execute_run/_stream_turn's last_author
    tracking); if it resolves to a different, real agent in this workspace,
    usage/cost gets attributed to that specialist instead, so per-agent
    dashboards (admin usage-by-agent, self-service /chat/usage by-agent)
    reflect who actually answered rather than always showing the router.
    Falls back to the passed-in agent_id/version whenever resolution can't
    find a match (unpublished specialist, cross-workspace, ADK-internal name).
    Runs in this function's own session (not the request's) since this is a
    fire-and-forget background write — the extra lookups here never add
    latency to the response the caller already sent."""
    try:
        async with async_session_factory() as session:
            if resolved_author and workspace_id is not None:
                candidates = (
                    await session.execute(
                        select(Agent.id, Agent.name, Agent.current_version).where(
                            Agent.workspace_id == workspace_id, Agent.status == "published"
                        )
                    )
                ).all()
                for candidate_id, candidate_name, candidate_version in candidates:
                    if _safe_agent_name(candidate_name) == resolved_author:
                        agent_id = candidate_id
                        agent_version = candidate_version
                        break

            invocation: InvocationLog | None = None
            if invocation_log_id is not None:
                # Durable-execution path: the row was already inserted
                # (status='running') before the turn started, by
                # start_durable_run — update it in place rather than
                # inserting a second row for the same turn.
                invocation = await session.get(InvocationLog, invocation_log_id)
            if invocation is None:
                invocation = InvocationLog(id=invocation_log_id) if invocation_log_id else InvocationLog()
                session.add(invocation)
            invocation.agent_id = agent_id
            invocation.agent_version = agent_version
            invocation.workspace_id = workspace_id
            invocation.trace_id = trace_id
            invocation.otel_trace_id = otel_trace_id
            invocation.status = status
            invocation.error_category = error_category
            invocation.latency_ms = latency_ms
            invocation.input_tokens = input_tokens
            invocation.output_tokens = output_tokens
            invocation.estimated_cost_usd = estimated_cost_usd
            invocation.error_message = error_message
            invocation.invoked_by = invoked_by
            invocation.transcript = transcript
            await session.flush()

            tool_names = [call["name"] for call in (tool_calls or []) if call.get("name")]
            tool_id_by_name: dict[str, uuid.UUID] = {}
            if tool_names:
                rows = (await session.execute(select(Tool.id, Tool.name).where(Tool.name.in_(tool_names)))).all()
                tool_id_by_name = {name: tid for tid, name in rows}

            for index, call in enumerate(tool_calls or []):
                session.add(
                    ToolCallLog(
                        invocation_id=invocation.id,
                        tool_id=call.get("tool_id") or tool_id_by_name.get(call.get("name")),
                        agent_name=call.get("agent_name"),
                        otel_span_id=call.get("otel_span_id"),
                        call_index=index,
                        status=call.get("status", "success"),
                        latency_ms=call.get("latency_ms", 0),
                        error_message=call.get("error_message"),
                        input=call.get("input"),
                        output=call.get("output"),
                    )
                )

            for event in events or []:
                session.add(
                    AgentEventLog(
                        invocation_id=invocation.id,
                        event_type=event["event_type"],
                        from_agent=event.get("from_agent"),
                        to_agent=event.get("to_agent"),
                        detail=event.get("detail"),
                        offset_ms=event.get("offset_ms"),
                        sequence=event.get("sequence", 0),
                    )
                )
            await session.commit()
    except Exception:
        # Logging must never take down the request path that triggered it.
        import logging

        logging.getLogger(__name__).exception("Failed to write invocation/tool_call log")
