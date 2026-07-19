"""Admin API for durable execution: visibility into in-flight/stuck/failed
runs (`invocation_log` rows created by `app.logging_hooks.start_durable_run`
— see `playground_api/router.py`'s `_run_turn`), an explicit resume trigger,
and live circuit-breaker state. Mirrors `app/scil_api/router.py`'s auth/
pagination conventions.

Admin-only (not viewer/developer like debug_api) — resume is an operator
action with real side effects (it can re-invoke a real LLM/tool call), not a
passive read.
"""

import time
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent_runtime.builder import get_or_build_agent
from app.agent_runtime.byok import required_providers, resolve_request_api_keys, use_api_keys
from app.chat_api.router import _chat_sessions
from app.config import get_settings
from app.db import get_db
from app.logging_hooks import log_invocation_fire_and_forget
from app.models.agents import Agent
from app.models.logs import InvocationLog
from app.observability.pricing import estimate_cost_usd
from app.observability.rca import classify_error
from app.playground_api.router import _execute_run, _invoke_sessions, _resolve_response_text
from app.principal import Principal, require_role
from app.reliability import circuit_breaker
from app.reliability.compensation import run_compensations
from app.schemas.reliability import (
    CircuitBreakerEntry,
    DurableRunEntry,
    DurableRunListResponse,
    DurableRunResumeResponse,
    TemporalReservationRequest,
    TemporalReservationResponse,
)

router = APIRouter(prefix="/reliability", tags=["reliability"])

_SESSION_SERVICES_BY_APP_NAME = {
    "agent_forge_invoke": _invoke_sessions,
    "agent_forge_chat": _chat_sessions,
}


@router.get("/runs", response_model=DurableRunListResponse)
async def list_durable_runs(
    status: str | None = Query(default=None),
    stale_minutes: int = Query(default=2, ge=0),
    limit: int = Query(default=25, le=100),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_role("admin")),
) -> DurableRunListResponse:
    """Only durable-execution turns show up here — `adk_invocation_id IS NOT
    NULL` is exactly the set of InvocationLog rows `start_durable_run` ever
    touched; every other agent's rows (the overwhelming majority) are
    invisible here, same as they're invisible to any resume/breaker
    concern."""
    conditions = [InvocationLog.workspace_id == principal.workspace_id, InvocationLog.adk_invocation_id.isnot(None)]
    if status:
        conditions.append(InvocationLog.status == status)

    total = await db.scalar(select(func.count()).select_from(InvocationLog).where(*conditions))
    rows = (
        await db.execute(
            select(InvocationLog, Agent.name)
            .outerjoin(Agent, Agent.id == InvocationLog.agent_id)
            .where(*conditions)
            .order_by(InvocationLog.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
    ).all()

    now = datetime.now(timezone.utc)
    stale_after = timedelta(minutes=stale_minutes)
    items = [
        DurableRunEntry(
            id=inv.id,
            agent_id=inv.agent_id,
            agent_name=agent_name,
            status=inv.status,
            adk_session_id=inv.adk_session_id,
            adk_invocation_id=inv.adk_invocation_id,
            error_category=inv.error_category,
            error_message=inv.error_message,
            invoked_by=inv.invoked_by,
            created_at=inv.created_at,
            age_seconds=(now - inv.created_at).total_seconds(),
            is_stale=(inv.status == "running" and (now - inv.created_at) >= stale_after),
        )
        for inv, agent_name in rows
    ]
    return DurableRunListResponse(items=items, total=total or 0, limit=limit, offset=offset)


@router.get("/circuit-breakers", response_model=list[CircuitBreakerEntry])
async def list_circuit_breakers(principal: Principal = Depends(require_role("admin"))) -> list[CircuitBreakerEntry]:
    return [CircuitBreakerEntry(**row) for row in circuit_breaker.snapshot()]


@router.post("/runs/{invocation_log_id}/resume", response_model=DurableRunResumeResponse)
async def resume_durable_run(
    invocation_log_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_role("admin")),
) -> DurableRunResumeResponse:
    invocation = await db.get(InvocationLog, invocation_log_id)
    if invocation is None or invocation.workspace_id != principal.workspace_id:
        raise HTTPException(status_code=404, detail="Run not found")
    if invocation.status != "running":
        raise HTTPException(
            status_code=400, detail=f"Run is '{invocation.status}', not resumable — it already finished."
        )
    if not (invocation.adk_invocation_id and invocation.adk_session_id and invocation.adk_app_name):
        raise HTTPException(status_code=409, detail="Run is missing durable-execution identifiers; cannot resume.")
    if invocation.agent_id is None:
        raise HTTPException(status_code=409, detail="Run has no associated agent; cannot resume.")

    session_service = _SESSION_SERVICES_BY_APP_NAME.get(invocation.adk_app_name)
    if session_service is None:
        raise HTTPException(status_code=409, detail=f"Unknown app_name '{invocation.adk_app_name}' — cannot resume.")

    agent_row = await db.get(Agent, invocation.agent_id)
    if agent_row is None:
        raise HTTPException(status_code=404, detail="Agent no longer exists.")

    adk_agent = await get_or_build_agent(
        db, agent_row.id, version=agent_row.current_version, durable_execution_enabled=True
    )

    # Admin-triggered operator action, not public traffic — same
    # operator-fallback treatment as /invoke (see playground_api's
    # invoke_published_agent).
    gemini_key, anthropic_key = resolve_request_api_keys(
        required_providers(adk_agent), None, None, allow_operator_fallback=True
    )

    start = time.monotonic()
    with use_api_keys(gemini_key, anthropic_key):
        # message=None + the ORIGINAL adk_invocation_id + resumable=True is
        # exactly ADK's own "resume an invocation from the last event"
        # contract (google.adk.apps.app.ResumabilityConfig) — any tool call
        # ADK re-attempts hits builder.py's idempotency check first, so an
        # already-durably-recorded success is replayed, not re-executed.
        outcome = await _execute_run(
            adk_agent=adk_agent,
            session_service=session_service,
            app_name=invocation.adk_app_name,
            user_id=invocation.adk_user_id,
            session_id=invocation.adk_session_id,
            message=None,
            state_delta=None,
            invocation_id=invocation.adk_invocation_id,
            resumable=True,
        )
    latency_ms = int((time.monotonic() - start) * 1000)
    response_text = _resolve_response_text(outcome)
    error_category = classify_error(
        status=outcome.status,
        error_message=outcome.error_message,
        events=outcome.events,
        tool_call_records=outcome.tool_call_records,
    )
    model = agent_row.model_config_json.get("model", "gemini-3.5-flash")

    log_invocation_fire_and_forget(
        invocation_log_id=invocation.id,
        agent_id=agent_row.id,
        agent_version=agent_row.current_version,
        workspace_id=agent_row.workspace_id,
        trace_id=invocation.adk_session_id,
        otel_trace_id=outcome.otel_trace_id,
        status=outcome.status,
        error_category=error_category,
        latency_ms=latency_ms,
        input_tokens=outcome.input_tokens,
        output_tokens=outcome.output_tokens,
        estimated_cost_usd=estimate_cost_usd(model, outcome.input_tokens, outcome.output_tokens),
        error_message=outcome.error_message,
        invoked_by=invocation.invoked_by,
        transcript={"resumed": True, "response_text": response_text},
        # Already durable per-call (builder.py's after_tool callback) — see
        # the same note in playground_api._run_turn's own log call.
        tool_calls=None,
        events=outcome.events,
        resolved_author=outcome.last_author,
    )

    if outcome.status == "error":
        # Same saga/compensation walk as _run_turn's own error path — a
        # resume that fails again still needs to roll back whatever
        # already-succeeded steps (this resume's own, or the original
        # attempt's, since both share the same invocation_log_id) had real
        # side effects.
        await run_compensations(invocation.id)
        raise HTTPException(status_code=502, detail=f"Resume failed: {outcome.error_message}")

    return DurableRunResumeResponse(
        id=invocation.id, status=outcome.status, response_text=response_text, error_message=outcome.error_message
    )


@router.post("/temporal/reservations", response_model=TemporalReservationResponse)
async def start_reservation_saga(
    payload: TemporalReservationRequest,
    principal: Principal = Depends(require_role("admin", "developer")),
) -> TemporalReservationResponse:
    """Starts app.durable_workflow.workflows.ReservationSagaWorkflow and
    waits for it to finish — the Temporal-backed twin of
    reservation_demo_tool's in-process reserve/confirm/release, proving
    the same saga/compensation guarantee now survives a WORKER process
    crash between steps, not just an API-request one. Requires
    TEMPORAL_ENABLED=true and a real Temporal server/worker reachable
    (`docker compose up -d temporal`, `python scripts/run_temporal_worker.py`)
    — 503 with a clear message otherwise, same "off by default, doesn't
    need extra infra to boot" pattern as OPA/Jaeger, not a hard crash at
    import time (see app/durable_workflow/__init__.py's docstring for why
    every import here is deliberately lazy)."""
    settings = get_settings()
    if not settings.temporal_enabled:
        raise HTTPException(
            status_code=503,
            detail="Temporal is not enabled on this server (TEMPORAL_ENABLED=false).",
        )

    try:
        from app.durable_workflow.client import get_temporal_client
        from app.durable_workflow.workflows import ReservationSagaInput, ReservationSagaWorkflow
    except ImportError as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Temporal support is not installed (pip install -e '.[temporal]'): {exc}",
        ) from exc

    workflow_id = f"reservation-{uuid.uuid4()}"
    try:
        client = await get_temporal_client()
        result = await client.execute_workflow(
            ReservationSagaWorkflow.run,
            ReservationSagaInput(item=payload.item, quantity=payload.quantity, order_id=payload.order_id),
            id=workflow_id,
            task_queue=settings.temporal_task_queue,
        )
    except Exception as exc:  # noqa: BLE001 — surfaced as a clear 502, not a raw traceback
        raise HTTPException(status_code=502, detail=f"Temporal workflow failed to run: {exc}") from exc

    return TemporalReservationResponse(workflow_id=result.reservation_id, status=result.status, detail=result.detail)
