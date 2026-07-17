"""The Debug Console: lets someone trace exactly what happened across a
multi-agent (orchestrator -> transfer -> specialist -> tool calls) turn,
and pinpoint WHY it failed for root-cause analysis (RCA).

Works in two modes, gracefully:
  - "reconstructed" (always available): built straight from invocation_log +
    tool_call_log + agent_event_log — no extra infra required, works the
    moment the backend is running. Timing is approximate (tool calls are
    laid out sequentially by the order they completed, see
    ToolCallLog.call_index) rather than true wall-clock-precise, since
    these rows are written in one fire-and-forget batch after the run
    finishes.
  - "jaeger" (when OTEL_ENABLED=true and a Jaeger Query API is reachable):
    fetches the real span tree for this invocation's OTel trace id, with
    real nanosecond-precision timing, exactly matching what "Open in Jaeger"
    would show. Falls back to "reconstructed" transparently if Jaeger is
    unreachable or the trace hasn't landed there yet.

Either way, agent-to-agent transfers and self-heal retries (both captured
in agent_event_log — see playground_api._run_turn/_execute_run) are merged
into the SAME waterfall as "transfer"/"retry" markers, and a real tool-call
failure (detected via observability.rca.tool_call_error — an MCP tool that
reported isError=true) shows up as a red span with its actual input/output
attached, not just a generic "success".
"""

import json
import uuid
from datetime import datetime
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import false, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.agents import Agent
from app.db import get_db
from app.models.logs import AgentEventLog, InvocationLog, ToolCallLog
from app.models.tools import Tool
from app.observability.rca import RCA_SUGGESTIONS
from app.principal import Principal, require_role
from app.schemas.debug import RcaInfo, SpanNode, TraceDetail, TraceListResponse, TraceSummary

router = APIRouter(prefix="/debug", tags=["debug"])


def _actor_key(principal: Principal) -> str:
    return principal.email or f"{principal.role} (static token)"


def _scope_to_principal(query, principal: Principal):
    """admin/viewer see every trace in the workspace. developer sees only
    traces for agents they created, or invocations they personally triggered
    (their own chat/playground activity) — mirrors the ownership scoping
    already enforced on agent config writes in config_api.agents."""
    if principal.role != "developer":
        return query
    own_invoked_by = str(principal.user_id) if principal.user_id else None
    own_invocation_clause = InvocationLog.invoked_by == own_invoked_by if own_invoked_by else false()
    return query.where(or_(Agent.created_by == _actor_key(principal), own_invocation_clause))


@router.get("/traces", response_model=TraceListResponse)
async def list_traces(
    agent_id: uuid.UUID | None = None,
    status: str | None = None,
    error_category: str | None = None,
    invoked_by: str | None = None,
    from_date: datetime | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_role("admin", "viewer", "developer")),
) -> TraceListResponse:
    tool_call_counts = (
        select(ToolCallLog.invocation_id, func.count().label("cnt"))
        .group_by(ToolCallLog.invocation_id)
        .subquery()
    )

    base = (
        select(InvocationLog, Agent.name, func.coalesce(tool_call_counts.c.cnt, 0))
        .outerjoin(Agent, Agent.id == InvocationLog.agent_id)
        .outerjoin(tool_call_counts, tool_call_counts.c.invocation_id == InvocationLog.id)
        .where(InvocationLog.workspace_id == principal.workspace_id)
    )
    base = _scope_to_principal(base, principal)
    if agent_id:
        base = base.where(InvocationLog.agent_id == agent_id)
    if status:
        base = base.where(InvocationLog.status == status)
    if error_category:
        base = base.where(InvocationLog.error_category == error_category)
    if invoked_by:
        base = base.where(InvocationLog.invoked_by == invoked_by)
    if from_date:
        base = base.where(InvocationLog.created_at >= from_date)

    count_query = select(func.count()).select_from(base.with_only_columns(InvocationLog.id).subquery())
    total = (await db.execute(count_query)).scalar_one()

    result = await db.execute(base.order_by(InvocationLog.created_at.desc()).limit(limit).offset(offset))
    items = [
        TraceSummary(
            invocation_id=inv.id,
            trace_id=inv.trace_id,
            otel_trace_id=inv.otel_trace_id,
            agent_id=inv.agent_id,
            agent_name=agent_name,
            status=inv.status,
            error_category=inv.error_category,
            latency_ms=inv.latency_ms,
            tool_call_count=tool_count,
            invoked_by=inv.invoked_by,
            estimated_cost_usd=float(inv.estimated_cost_usd) if inv.estimated_cost_usd is not None else None,
            created_at=inv.created_at,
        )
        for inv, agent_name, tool_count in result
    ]
    return TraceListResponse(items=items, total=total, limit=limit, offset=offset)


async def _get_invocation_scoped(db: AsyncSession, invocation_id: uuid.UUID, principal: Principal) -> tuple[InvocationLog, str | None]:
    result = await db.execute(
        select(InvocationLog, Agent.name, Agent.created_by)
        .outerjoin(Agent, Agent.id == InvocationLog.agent_id)
        .where(InvocationLog.id == invocation_id, InvocationLog.workspace_id == principal.workspace_id)
    )
    row = result.first()
    if row is None:
        raise HTTPException(status_code=404, detail="Trace not found")
    inv, agent_name, agent_created_by = row

    if principal.role == "developer":
        own_invoked_by = str(principal.user_id) if principal.user_id else None
        owns_agent = agent_created_by == _actor_key(principal)
        own_invocation = own_invoked_by is not None and inv.invoked_by == own_invoked_by
        if not (owns_agent or own_invocation):
            raise HTTPException(status_code=403, detail="You can only debug traces for your own agents or activity")

    return inv, agent_name


async def _event_spans(
    db: AsyncSession, invocation_id: uuid.UUID, root_id: str, *, include_model_text: bool = True
) -> list[SpanNode]:
    """agent_event_log rows (transfers + self-heal retries + model text
    segments), reshaped as zero-duration waterfall markers. Transfers and
    retries only ever come from our own DB regardless of which mode is
    rendering the tool-call spans, so they're always merged in. Model text
    segments are different: in "jaeger" mode they're ALSO real child spans
    (operationName "agent.message", see playground_api) already present in
    `_fetch_jaeger_spans`'s output — so the caller passes
    include_model_text=False there to avoid rendering each one twice."""
    result = await db.execute(
        select(AgentEventLog).where(AgentEventLog.invocation_id == invocation_id).order_by(AgentEventLog.sequence.asc())
    )
    spans: list[SpanNode] = []
    for event in result.scalars():
        offset = event.offset_ms or 0
        detail = event.detail or {}
        if event.event_type == "model_text" and not include_model_text:
            continue
        if event.event_type == "transfer":
            spans.append(
                SpanNode(
                    id=str(event.id),
                    parent_id=root_id,
                    kind="transfer",
                    name=f"transfer: {event.from_agent} → {event.to_agent}",
                    agent_name=event.to_agent,
                    status="success",
                    start_offset_ms=offset,
                    duration_ms=0,
                )
            )
        elif event.event_type == "model_text":
            spans.append(
                SpanNode(
                    id=str(event.id),
                    parent_id=root_id,
                    kind="model",
                    name=f"ai: {event.from_agent or 'model'}",
                    agent_name=event.from_agent,
                    status="success",
                    start_offset_ms=offset,
                    duration_ms=0,
                    output=detail.get("text"),
                )
            )
        else:
            label = "orchestrator hallucination retry" if event.event_type == "orchestrator_hallucination_retry" else "stale session retry"
            spans.append(
                SpanNode(
                    id=str(event.id),
                    parent_id=root_id,
                    kind="retry",
                    name=f"self-heal: {label}",
                    agent_name=None,
                    status="error",
                    start_offset_ms=offset,
                    duration_ms=0,
                    error_message=detail.get("error"),
                )
            )
    return spans


async def _reconstruct_spans(db: AsyncSession, inv: InvocationLog, agent_name: str | None) -> list[SpanNode]:
    root = SpanNode(
        id=str(inv.id),
        parent_id=None,
        kind="root",
        name="agent.invocation",
        agent_name=agent_name,
        status="error" if inv.status != "success" else "success",
        start_offset_ms=0,
        duration_ms=inv.latency_ms,
        input=(inv.transcript or {}).get("message") if inv.transcript else None,
        output=(inv.transcript or {}).get("response_text") if inv.transcript else None,
        error_message=inv.error_message,
    )

    result = await db.execute(
        select(ToolCallLog, Tool.name)
        .outerjoin(Tool, Tool.id == ToolCallLog.tool_id)
        .where(ToolCallLog.invocation_id == inv.id)
        .order_by(ToolCallLog.call_index.asc().nulls_last(), ToolCallLog.created_at.asc())
    )
    spans = [root]
    offset = 0
    for call, tool_name in result:
        spans.append(
            SpanNode(
                id=call.otel_span_id or str(call.id),
                parent_id=root.id,
                kind="tool",
                name=f"tool.{tool_name or 'unknown_tool'}",
                agent_name=call.agent_name,
                status="error" if call.status != "success" else "success",
                start_offset_ms=offset,
                duration_ms=call.latency_ms,
                input=call.input,
                output=call.output,
                error_message=call.error_message,
            )
        )
        offset += call.latency_ms

    spans += await _event_spans(db, inv.id, root.id)
    return _sorted_spans(spans)


def _sorted_spans(spans: list[SpanNode]) -> list[SpanNode]:
    """Root first (found by kind, NOT assumed to be spans[0] — the
    Jaeger-sourced list's order comes straight from the Query API response,
    with no such guarantee), then everything else by when it happened."""
    return sorted(spans, key=lambda s: (0 if s.kind == "root" else 1, s.start_offset_ms))


def _jaeger_tag(tags: list[dict], key: str) -> str | None:
    for tag in tags or []:
        if tag.get("key") == key:
            return tag.get("value")
    return None


def _jaeger_payload_tag(tags: list[dict], key: str) -> Any:
    """tool.input/tool.output are stored as JSON-serialized strings (see
    playground_api._span_json — an OTel attribute must be a scalar, not an
    arbitrary object). Parse back to structured data for the frontend;
    fall back to the raw string if it's ever not valid JSON (e.g. an older
    span written before this existed, or a non-JSON exporter)."""
    raw = _jaeger_tag(tags, key)
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return raw


async def _fetch_jaeger_spans(otel_trace_id: str) -> list[SpanNode] | None:
    settings = get_settings()
    if not settings.otel_enabled:
        return None
    url = f"{settings.jaeger_query_url.rstrip('/')}/api/traces/{otel_trace_id}"
    try:
        async with httpx.AsyncClient(timeout=2.5) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            payload = resp.json()
    except Exception:  # noqa: BLE001 — Jaeger unreachable/trace not ingested yet, fall back silently
        return None

    traces = payload.get("data") or []
    if not traces:
        return None
    raw_spans = traces[0].get("spans") or []
    if not raw_spans:
        return None

    root_start = min(s["startTime"] for s in raw_spans)
    nodes: list[SpanNode] = []
    for span in raw_spans:
        parent_id = None
        for ref in span.get("references") or []:
            if ref.get("refType") == "CHILD_OF":
                parent_id = ref.get("spanID")
                break
        tags = span.get("tags") or []
        is_error = str(_jaeger_tag(tags, "otel.status_code")).upper() == "ERROR"
        operation_name = span.get("operationName", "span")
        if parent_id is None:
            kind = "root"
        elif operation_name == "agent.message":
            kind = "model"
        else:
            kind = "tool"
        nodes.append(
            SpanNode(
                id=span["spanID"],
                parent_id=parent_id,
                kind=kind,
                name=operation_name,
                agent_name=_jaeger_tag(tags, "agent.name"),
                status="error" if is_error else "success",
                start_offset_ms=int((span["startTime"] - root_start) / 1000),
                duration_ms=int(span.get("duration", 0) / 1000),
                input=_jaeger_payload_tag(tags, "tool.input"),
                output=_jaeger_payload_tag(tags, "tool.output") if kind == "tool" else _jaeger_tag(tags, "message.text"),
                error_message=_jaeger_tag(tags, "otel.status_description") if is_error else None,
            )
        )
    return nodes


def _build_rca(inv: InvocationLog) -> RcaInfo | None:
    if not inv.error_category:
        return None
    suggestion = RCA_SUGGESTIONS.get(inv.error_category)
    if suggestion is None:
        return None
    headline, suggested_fix = suggestion
    return RcaInfo(category=inv.error_category, headline=headline, suggested_fix=suggested_fix)


@router.get("/traces/{invocation_id}", response_model=TraceDetail)
async def get_trace(
    invocation_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_role("admin", "viewer", "developer")),
) -> TraceDetail:
    inv, agent_name = await _get_invocation_scoped(db, invocation_id, principal)

    tool_call_count = (
        await db.scalar(select(func.count()).where(ToolCallLog.invocation_id == inv.id))
    ) or 0
    summary = TraceSummary(
        invocation_id=inv.id,
        trace_id=inv.trace_id,
        otel_trace_id=inv.otel_trace_id,
        agent_id=inv.agent_id,
        agent_name=agent_name,
        status=inv.status,
        error_category=inv.error_category,
        latency_ms=inv.latency_ms,
        tool_call_count=tool_call_count,
        invoked_by=inv.invoked_by,
        estimated_cost_usd=float(inv.estimated_cost_usd) if inv.estimated_cost_usd is not None else None,
        created_at=inv.created_at,
    )

    spans: list[SpanNode] | None = None
    spans_source = "reconstructed"
    if inv.otel_trace_id:
        jaeger_spans = await _fetch_jaeger_spans(inv.otel_trace_id)
        if jaeger_spans:
            root_id = next((s.id for s in jaeger_spans if s.kind == "root"), str(inv.id))
            spans = _sorted_spans(
                jaeger_spans + await _event_spans(db, inv.id, root_id, include_model_text=False)
            )
            spans_source = "jaeger"
    if spans is None:
        spans = await _reconstruct_spans(db, inv, agent_name)

    settings = get_settings()
    jaeger_trace_url = (
        f"{settings.jaeger_query_url.rstrip('/')}/trace/{inv.otel_trace_id}"
        if settings.otel_enabled and inv.otel_trace_id
        else None
    )

    return TraceDetail(
        summary=summary,
        message=(inv.transcript or {}).get("message") if inv.transcript else None,
        response_text=(inv.transcript or {}).get("response_text") if inv.transcript else None,
        error_message=inv.error_message,
        rca=_build_rca(inv),
        spans=spans,
        spans_source=spans_source,
        jaeger_trace_url=jaeger_trace_url,
    )
