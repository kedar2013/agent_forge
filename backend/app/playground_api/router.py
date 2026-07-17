import json
import time
import uuid
from datetime import datetime, timezone
from typing import Any, AsyncIterator

from fastapi import APIRouter, Depends, Header, HTTPException
from google.adk.agents import Agent as AdkAgent
from google.adk.runners import Runner
from google.adk.sessions import BaseSessionService, DatabaseSessionService, InMemorySessionService
from google.genai import types
from opentelemetry.trace import Status, StatusCode
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import get_db
from app.logging_hooks import log_invocation_fire_and_forget
from app.models.agents import Agent as AgentRow
from app.agent_runtime.builder import close_agent_toolsets, get_or_build_agent
from app.agent_runtime.byok import required_providers, resolve_request_api_keys, use_api_keys
from app.observability.pricing import estimate_cost_usd
from app.observability.rca import cap_payload, classify_error, tool_call_error
from app.observability.tracing import get_tracer
from app.principal import Principal, require_role
from app.rate_limit import rate_limit_principal
from app.scil.corrector import build_correction_message, lookup_known_correction, save_correction_fire_and_forget
from app.scil.entities import remember_entities_fire_and_forget, resolve_entity_mismatch
from app.scil.eval_runner import sample_groundedness_fire_and_forget
from app.scil.hallucination import check_groundedness
from app.scil.normalizer import normalize
from app.scil.runner import (
    build_exemplar_message,
    check_cache,
    check_template,
    get_scil_config,
    log_metrics_fire_and_forget,
    save_cache_entry_fire_and_forget,
)
from app.scil.validators import ValidationResult, validate_output
from app.schemas.playground import (
    InvokeRequest,
    PlaygroundRunRequest,
    PlaygroundRunResponse,
    ToolCallTrace,
)

router = APIRouter(prefix="/playground", tags=["playground"])
invoke_router = APIRouter(prefix="/agents", tags=["invoke"])

# ADK's own internal plumbing calls — routing between orchestrator/sub-agents,
# and the output_schema+tools workaround's response-setter — neither is a
# real configured tool, so both are filtered out of the trace shown to a user.
_INTERNAL_FUNCTION_NAMES = {"transfer_to_agent", "set_model_response"}

# Playground sessions are cheap, throwaway test runs against a draft config —
# in-memory is the correct semantics, a restart *should* clear them. /invoke
# is the production surface real external callers depend on, so it's backed
# by Postgres (ADK's DatabaseSessionService) and survives a restart.
_playground_sessions = InMemorySessionService()
_invoke_sessions = DatabaseSessionService(db_url=get_settings().database_url)


def _current_date_state() -> dict[str, Any]:
    """"Today", re-asserted on every single turn (same reason
    chat_api._identity_state_delta re-asserts identity every turn rather
    than seeding it once at session creation: a long-lived session must
    never see a date frozen at whenever it started). Lives here — not in
    chat_api's identity delta — because it has no per-user identity
    dependency at all, so merging it in at the top of _run_turn/_stream_turn
    covers BOTH the chat surface and the Playground uniformly, with no
    "Playground needs it pasted into Session State by hand" gap the way
    _principal_soeid does. An agent's base_instruction opts in with ADK's
    ordinary {state_key} templating, e.g. "{current_date}" / "{current_month}"
    — unreferenced by an instruction, this is a harmless no-op.
    current_month is YYYYMM (int), matching credit_facility/revenue_and_returns'
    own load_id column format, so an instruction can filter/compare against it
    directly without asking the model to convert formats."""
    now = datetime.now(timezone.utc)
    return {"current_date": now.date().isoformat(), "current_month": now.year * 100 + now.month}


def _span_json(value: Any) -> str:
    """Serializes a tool/model payload for use as an OTel span attribute value
    (which must be a scalar, not an arbitrary object) — same size cap as the
    DB-stored copy (`cap_payload`) so a real trace backend like Langfuse/
    Jaeger never gets a multi-megabyte attribute either."""
    return json.dumps(cap_payload(value), default=str)


def _fallback_text_from_tool_calls(tool_calls: list[ToolCallTrace]) -> str | None:
    """Best-effort plain-text extraction from the last tool call's output, for
    the rare case the model finishes a turn without any text part of its own.
    MCP tool outputs are shaped like {"content": [{"type": "text", "text": ...}]}
    — pull that out rather than dumping the raw dict on the user."""
    if not tool_calls:
        return None
    output = tool_calls[-1].output
    if isinstance(output, dict):
        content = output.get("content")
        if isinstance(content, list) and content and isinstance(content[0], dict):
            text = content[0].get("text")
            if isinstance(text, str) and text.strip():
                return text
    return str(output) if output else None


def _resolve_response_text(outcome: "_RunOutcome") -> str:
    """Final user-facing text for one attempt. Gemini occasionally finishes
    a multi-hop transfer+tool-call turn without emitting a final text part
    (rare, model-side) — rather than show the user a blank bubble, fall back
    to the last tool result (still readable) or a plain apology, never
    silence."""
    response_text = "".join(outcome.final_text_parts)
    if outcome.status == "success" and not response_text.strip():
        response_text = _fallback_text_from_tool_calls(outcome.tool_calls) or (
            "Sorry, I couldn't come up with an answer to that — could you try rephrasing?"
        )
    return response_text


class _RunOutcome:
    """Everything one ADK turn produced. `tool_call_records`/`events` are the
    RCA-oriented twins of `tool_calls` — real per-call input/output/error
    (not just name+timing), and non-tool-call events (agent-to-agent
    transfers) that `log_invocation_fire_and_forget` and the Debug Console
    both need to reconstruct what actually happened, not just the final
    text."""

    __slots__ = (
        "status",
        "error_message",
        "tool_calls",
        "tool_call_records",
        "events",
        "final_text_parts",
        "input_tokens",
        "output_tokens",
        "last_author",
        "otel_trace_id",
    )

    def __init__(self) -> None:
        self.status = "success"
        self.error_message: str | None = None
        self.tool_calls: list[ToolCallTrace] = []
        self.tool_call_records: list[dict[str, Any]] = []
        self.events: list[dict[str, Any]] = []
        self.final_text_parts: list[str] = []
        self.input_tokens: int | None = None
        self.output_tokens: int | None = None
        self.last_author: str | None = None
        self.otel_trace_id: str | None = None


async def _execute_run(
    *,
    adk_agent: AdkAgent,
    session_service: BaseSessionService,
    app_name: str,
    user_id: str,
    session_id: str,
    message: str,
    state_delta: dict[str, Any] | None,
) -> _RunOutcome:
    """Runs one turn and collects its outcome. Split out from `_run_turn` so a
    stale-session failure (see below) can retry this in isolation.

    Every tool call gets its own OTel child span (name `tool.<tool name>`),
    nested under one root span for the whole invocation (`agent.invocation`)
    — this is what the Debug Console's waterfall view (and any real trace
    backend it's pointed at, e.g. Jaeger) actually renders. Tool calls whose
    MCP response has isError=true are marked status="error" with the tool's
    own error text captured (see observability.rca.tool_call_error) — a
    tool failure otherwise looked identical to a success everywhere
    downstream, since ADK itself doesn't raise for it. Agent-to-agent
    transfers are recorded as `events`, not spans — they're instantaneous
    hand-offs, not something with its own duration. With tracing disabled
    (default), `get_tracer()` returns a no-op tracer and all of this costs
    effectively nothing."""
    runner = Runner(agent=adk_agent, app_name=app_name, session_service=session_service)
    outcome = _RunOutcome()
    pending_calls: dict[str, dict[str, Any]] = {}
    run_start = time.monotonic()

    tracer = get_tracer()
    with tracer.start_as_current_span(
        "agent.invocation",
        attributes={"agent.name": adk_agent.name, "session.id": session_id, "user.id": user_id},
    ) as root_span:
        span_context = root_span.get_span_context()
        # Tracing disabled -> get_tracer() returns a no-op tracer whose spans
        # have an all-zero, `is_valid=False` context; don't persist that as if
        # it were a real trace id.
        outcome.otel_trace_id = format(span_context.trace_id, "032x") if span_context.is_valid else None
        try:
            async for event in runner.run_async(
                user_id=user_id,
                session_id=session_id,
                new_message=types.Content(role="user", parts=[types.Part.from_text(text=message)]),
                state_delta=state_delta,
            ):
                # Tracks whichever agent authored the most recent event — for a
                # request that transferred to a specialist, this ends up being the
                # specialist, not the root orchestrator that was actually invoked.
                # Used both to attribute usage/cost to the agent that did the real
                # work (see logging_hooks._write_invocation_log's resolved_author
                # handling) and, per-tool-call, to attribute which agent made it.
                prior_author = outcome.last_author
                if event.author:
                    outcome.last_author = event.author

                if event.actions and event.actions.transfer_to_agent:
                    to_agent = event.actions.transfer_to_agent
                    from_agent = prior_author or adk_agent.name
                    outcome.events.append(
                        {
                            "event_type": "transfer",
                            "from_agent": from_agent,
                            "to_agent": to_agent,
                            "offset_ms": int((time.monotonic() - run_start) * 1000),
                            "sequence": len(outcome.events),
                        }
                    )
                    root_span.add_event(
                        f"transfer_to_{to_agent}", attributes={"from_agent": from_agent, "to_agent": to_agent}
                    )

                for call in event.get_function_calls():
                    if call.name in _INTERNAL_FUNCTION_NAMES:
                        continue
                    span = tracer.start_span(
                        f"tool.{call.name}",
                        attributes={
                            "tool.name": call.name,
                            "agent.name": event.author or outcome.last_author or adk_agent.name,
                            "tool.input": _span_json(call.args),
                        },
                    )
                    pending_calls[call.id] = {
                        "name": call.name,
                        "input": call.args,
                        "span": span,
                        "start": time.monotonic(),
                        "agent_name": event.author or outcome.last_author or adk_agent.name,
                    }

                for resp in event.get_function_responses():
                    if resp.name in _INTERNAL_FUNCTION_NAMES:
                        continue
                    started = pending_calls.pop(resp.id, None) or {
                        "name": resp.name,
                        "input": {},
                        "span": None,
                        "start": time.monotonic(),
                        "agent_name": outcome.last_author or adk_agent.name,
                    }
                    outcome.tool_calls.append(
                        ToolCallTrace(name=started["name"], input=started["input"], output=resp.response)
                    )
                    call_latency_ms = int((time.monotonic() - started["start"]) * 1000)
                    call_error = tool_call_error(resp.response)
                    otel_span_id = None
                    span = started.get("span")
                    if span is not None:
                        span.set_attribute("tool.latency_ms", call_latency_ms)
                        span.set_attribute("tool.output", _span_json(resp.response))
                        if call_error:
                            span.set_attribute("tool.error", True)
                            span.set_status(Status(StatusCode.ERROR, call_error))
                        span_ctx = span.get_span_context()
                        if span_ctx.is_valid:
                            otel_span_id = format(span_ctx.span_id, "016x")
                        span.end()
                    outcome.tool_call_records.append(
                        {
                            "name": started["name"],
                            "status": "error" if call_error else "success",
                            "latency_ms": call_latency_ms,
                            "agent_name": started.get("agent_name"),
                            "otel_span_id": otel_span_id,
                            "input": cap_payload(started["input"]),
                            "output": cap_payload(resp.response),
                            "error_message": call_error,
                        }
                    )

                if event.content and event.content.parts:
                    event_text_parts = [part.text for part in event.content.parts if part.text]
                    if event_text_parts:
                        outcome.final_text_parts.extend(event_text_parts)
                        model_text = "".join(event_text_parts)
                        model_agent = event.author or outcome.last_author or adk_agent.name
                        msg_span = tracer.start_span(
                            "agent.message",
                            attributes={"agent.name": model_agent, "message.text": model_text[:4000]},
                        )
                        msg_span.end()
                        outcome.events.append(
                            {
                                "event_type": "model_text",
                                "from_agent": model_agent,
                                "detail": {"text": model_text},
                                "offset_ms": int((time.monotonic() - run_start) * 1000),
                                "sequence": len(outcome.events),
                            }
                        )

                # usage_metadata reflects the running total for the interaction so
                # far; the last event we see it on has the final counts.
                if event.usage_metadata:
                    if event.usage_metadata.prompt_token_count is not None:
                        outcome.input_tokens = event.usage_metadata.prompt_token_count
                    if event.usage_metadata.candidates_token_count is not None:
                        outcome.output_tokens = event.usage_metadata.candidates_token_count
        except Exception as exc:  # noqa: BLE001 — surfaced to the caller, not swallowed
            outcome.status = "error"
            outcome.error_message = str(exc)
            root_span.record_exception(exc)
        # Any tool call left pending (e.g. the run raised before its response
        # event arrived) would otherwise leak an unended span.
        for leftover in pending_calls.values():
            span = leftover.get("span")
            if span is not None:
                span.end()
        root_span.set_attribute("invocation.status", outcome.status)

    return outcome


async def _stream_turn(
    *,
    adk_agent: AdkAgent,
    agent_row: AgentRow,
    session_service: BaseSessionService,
    app_name: str,
    user_id: str,
    session_id: str,
    message: str,
    state_delta: dict[str, Any] | None,
) -> AsyncIterator[dict[str, Any]]:
    """Streaming twin of `_run_turn` — yields progress events as the ADK
    Runner produces them (a transfer, a tool call starting, a tool call
    finishing), then a final "done" event shaped like PlaygroundRunResponse.
    Used by the chat surface to show live "what the agent is doing" instead
    of a blank wait during multi-tool-call chains.

    Deliberately simpler than `_run_turn`: no stale-session/hallucination
    retry here — an error mid-stream just yields an "error" event and ends
    the stream. That reliability layer stays on the non-streaming endpoints;
    this one is about visibility, and a client can always resend the message
    with a fresh session_id if it hits the rare hallucination case. It still
    captures the same RCA data (tool I/O, failures, transfers) for the
    Debug Console as the blocking path does — just without the retry.

    SCIL (app/scil/) short-circuits right here, before any session/Runner
    setup, when `agent_row.model_config_json["scil"]["enabled"]` is true and
    the message matches a validated cached answer (exact-hash or
    cosine-similarity, see app/scil/cache.py) — zero LLM calls, a synthetic
    "cache_hit" event then a "done" event shaped exactly like the real
    path's. When scil is disabled/absent or the cache misses, execution
    falls through to the unchanged existing logic below; a metrics row is
    still written either way (route="disabled" or "llm") so baseline
    call-volume is visible even before scil is turned on for an agent."""
    state_delta = {**(state_delta or {}), **_current_date_state()}
    scil_request_id = uuid.uuid4()
    scil_start = time.monotonic()
    scil_config = get_scil_config(agent_row)

    template_answer = check_template(normalize(message), scil_config)
    if template_answer is not None:
        template_latency_ms = int((time.monotonic() - scil_start) * 1000)
        log_metrics_fire_and_forget(
            agent_id=agent_row.id,
            request_id=scil_request_id,
            route="deterministic",
            llm_calls=0,
            latency_ms=template_latency_ms,
        )
        yield {"type": "cache_hit"}
        yield {
            "type": "done",
            "response_text": template_answer,
            "tool_calls": [],
            "latency_ms": template_latency_ms,
            "session_id": session_id,
        }
        return

    scil_hit, scil_normalized = await check_cache(agent_row.id, message, scil_config, user_id)
    if scil_hit is not None:
        cache_latency_ms = int((time.monotonic() - scil_start) * 1000)
        log_metrics_fire_and_forget(
            agent_id=agent_row.id,
            request_id=scil_request_id,
            route="cache_hit",
            llm_calls=0,
            latency_ms=cache_latency_ms,
        )
        yield {"type": "cache_hit"}
        yield {
            "type": "done",
            "response_text": scil_hit.output_payload.get("response_text", ""),
            "tool_calls": scil_hit.output_payload.get("tool_calls", []),
            "latency_ms": cache_latency_ms,
            "session_id": session_id,
        }
        return

    llm_message = await build_exemplar_message(agent_row.id, message, scil_normalized, scil_config)

    existing_session = await session_service.get_session(
        app_name=app_name, user_id=user_id, session_id=session_id
    )
    if existing_session is None:
        await session_service.create_session(
            app_name=app_name, user_id=user_id, session_id=session_id, state=state_delta
        )

    runner = Runner(agent=adk_agent, app_name=app_name, session_service=session_service)

    tool_calls: list[ToolCallTrace] = []
    tool_call_records: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    pending_calls: dict[str, dict[str, Any]] = {}
    final_text_parts: list[str] = []
    status = "success"
    error_message: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    last_author: str | None = None
    start = time.monotonic()

    tracer = get_tracer()
    with tracer.start_as_current_span(
        "agent.invocation",
        attributes={"agent.name": adk_agent.name, "session.id": session_id, "user.id": user_id},
    ) as root_span:
        span_context = root_span.get_span_context()
        otel_trace_id = format(span_context.trace_id, "032x") if span_context.is_valid else None
        try:
            async for event in runner.run_async(
                user_id=user_id,
                session_id=session_id,
                new_message=types.Content(role="user", parts=[types.Part.from_text(text=llm_message)]),
                state_delta=state_delta,
            ):
                prior_author = last_author
                if event.author:
                    last_author = event.author

                if event.actions and event.actions.transfer_to_agent:
                    to_agent = event.actions.transfer_to_agent
                    from_agent = prior_author or adk_agent.name
                    events.append(
                        {
                            "event_type": "transfer",
                            "from_agent": from_agent,
                            "to_agent": to_agent,
                            "offset_ms": int((time.monotonic() - start) * 1000),
                            "sequence": len(events),
                        }
                    )
                    root_span.add_event(
                        f"transfer_to_{to_agent}", attributes={"from_agent": from_agent, "to_agent": to_agent}
                    )
                    yield {"type": "transfer", "to": to_agent}

                for call in event.get_function_calls():
                    if call.name in _INTERNAL_FUNCTION_NAMES:
                        continue
                    span = tracer.start_span(
                        f"tool.{call.name}",
                        attributes={
                            "tool.name": call.name,
                            "agent.name": event.author or last_author or adk_agent.name,
                            "tool.input": _span_json(call.args),
                        },
                    )
                    pending_calls[call.id] = {
                        "name": call.name,
                        "input": call.args,
                        "span": span,
                        "start": time.monotonic(),
                        "agent_name": event.author or last_author or adk_agent.name,
                    }
                    yield {"type": "tool_call_start", "name": call.name, "input": call.args}

                for resp in event.get_function_responses():
                    if resp.name in _INTERNAL_FUNCTION_NAMES:
                        continue
                    started = pending_calls.pop(resp.id, None) or {
                        "name": resp.name,
                        "input": {},
                        "span": None,
                        "start": time.monotonic(),
                        "agent_name": last_author or adk_agent.name,
                    }
                    tool_calls.append(
                        ToolCallTrace(name=started["name"], input=started["input"], output=resp.response)
                    )
                    call_latency_ms = int((time.monotonic() - started["start"]) * 1000)
                    call_error = tool_call_error(resp.response)
                    otel_span_id = None
                    span = started.get("span")
                    if span is not None:
                        span.set_attribute("tool.latency_ms", call_latency_ms)
                        span.set_attribute("tool.output", _span_json(resp.response))
                        if call_error:
                            span.set_attribute("tool.error", True)
                            span.set_status(Status(StatusCode.ERROR, call_error))
                        span_ctx = span.get_span_context()
                        if span_ctx.is_valid:
                            otel_span_id = format(span_ctx.span_id, "016x")
                        span.end()
                    tool_call_records.append(
                        {
                            "name": started["name"],
                            "status": "error" if call_error else "success",
                            "latency_ms": call_latency_ms,
                            "agent_name": started.get("agent_name"),
                            "otel_span_id": otel_span_id,
                            "input": cap_payload(started["input"]),
                            "output": cap_payload(resp.response),
                            "error_message": call_error,
                        }
                    )
                    yield {
                        "type": "tool_call_end",
                        "name": started["name"],
                        "status": "error" if call_error else "success",
                    }

                if event.content and event.content.parts:
                    event_text_parts = [part.text for part in event.content.parts if part.text]
                    if event_text_parts:
                        final_text_parts.extend(event_text_parts)
                        model_text = "".join(event_text_parts)
                        model_agent = event.author or last_author or adk_agent.name
                        msg_span = tracer.start_span(
                            "agent.message",
                            attributes={"agent.name": model_agent, "message.text": model_text[:4000]},
                        )
                        msg_span.end()
                        events.append(
                            {
                                "event_type": "model_text",
                                "from_agent": model_agent,
                                "detail": {"text": model_text},
                                "offset_ms": int((time.monotonic() - start) * 1000),
                                "sequence": len(events),
                            }
                        )

                if event.usage_metadata:
                    if event.usage_metadata.prompt_token_count is not None:
                        input_tokens = event.usage_metadata.prompt_token_count
                    if event.usage_metadata.candidates_token_count is not None:
                        output_tokens = event.usage_metadata.candidates_token_count
        except Exception as exc:  # noqa: BLE001 — surfaced to the caller, not swallowed
            status = "error"
            error_message = str(exc)
            root_span.record_exception(exc)
        for leftover in pending_calls.values():
            leftover_span = leftover.get("span")
            if leftover_span is not None:
                leftover_span.end()
        root_span.set_attribute("invocation.status", status)

    latency_ms = int((time.monotonic() - start) * 1000)
    response_text = "".join(final_text_parts)
    if status == "success" and not response_text.strip():
        response_text = _fallback_text_from_tool_calls(tool_calls) or (
            "Sorry, I couldn't come up with an answer to that — could you try rephrasing?"
        )
    model = agent_row.model_config_json.get("model", "gemini-2.5-flash")
    error_category = classify_error(
        status=status, error_message=error_message, events=events, tool_call_records=tool_call_records
    )

    log_invocation_fire_and_forget(
        agent_id=agent_row.id,
        agent_version=agent_row.current_version,
        workspace_id=agent_row.workspace_id,
        trace_id=session_id,
        otel_trace_id=otel_trace_id,
        status=status,
        error_category=error_category,
        latency_ms=latency_ms,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        estimated_cost_usd=estimate_cost_usd(model, input_tokens, output_tokens),
        error_message=error_message,
        invoked_by=user_id,
        transcript={"message": message, "response_text": response_text},
        tool_calls=tool_call_records,
        events=events,
        resolved_author=last_author,
    )

    log_metrics_fire_and_forget(
        agent_id=agent_row.id,
        request_id=scil_request_id,
        route="llm" if scil_config.enabled else "disabled",
        llm_calls=1,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        latency_ms=latency_ms,
    )
    # No retry loop on the streaming path (matching the stale-session/
    # hallucination self-heals, which are also non-streaming-only) — but the
    # validators still gate the cache, so an invalid streamed answer can't
    # become a future cache hit.
    if scil_config.enabled and status == "success" and (
        not scil_config.validators
        or validate_output(
            response_text, scil_config.validators, agent_row, tool_calls, bool(adk_agent.tools)
        ).ok
    ) and not any(tc.get("status") == "error" for tc in tool_call_records):
        save_cache_entry_fire_and_forget(
            agent_row.id,
            scil_normalized,
            {"response_text": response_text, "tool_calls": [tc.model_dump() for tc in tool_calls]},
            ttl_hours=scil_config.cache_ttl_hours,
            scope_key=scil_config.scope_key(user_id),
        )

    if status == "error":
        yield {"type": "error", "message": f"Run failed: {error_message}"}
        return

    yield {
        "type": "done",
        "response_text": response_text,
        "tool_calls": [tc.model_dump() for tc in tool_calls],
        "latency_ms": latency_ms,
        "session_id": session_id,
    }


async def _run_turn(
    *,
    db: AsyncSession,
    adk_agent: AdkAgent,
    agent_row: AgentRow,
    session_service: BaseSessionService,
    app_name: str,
    user_id: str,
    session_id: str,
    message: str,
    state_delta: dict[str, Any] | None,
) -> PlaygroundRunResponse:
    # SCIL short-circuits -- see the matching block in _stream_turn for the
    # full rationale. Order: template match (pure regex, cheapest) -> cache
    # (DB) -> LLM with correction exemplars. Disabled/missed -> unchanged.
    scil_request_id = uuid.uuid4()
    scil_start = time.monotonic()
    scil_config = get_scil_config(agent_row)

    template_answer = check_template(normalize(message), scil_config)
    if template_answer is not None:
        template_latency_ms = int((time.monotonic() - scil_start) * 1000)
        log_metrics_fire_and_forget(
            agent_id=agent_row.id,
            request_id=scil_request_id,
            route="deterministic",
            llm_calls=0,
            latency_ms=template_latency_ms,
        )
        return PlaygroundRunResponse(
            response_text=template_answer, tool_calls=[], latency_ms=template_latency_ms, session_id=session_id
        )

    scil_hit, scil_normalized = await check_cache(agent_row.id, message, scil_config, user_id)
    if scil_hit is not None:
        cache_latency_ms = int((time.monotonic() - scil_start) * 1000)
        log_metrics_fire_and_forget(
            agent_id=agent_row.id,
            request_id=scil_request_id,
            route="cache_hit",
            llm_calls=0,
            latency_ms=cache_latency_ms,
        )
        payload = scil_hit.output_payload
        return PlaygroundRunResponse(
            response_text=payload.get("response_text", ""),
            tool_calls=[ToolCallTrace(**tc) for tc in payload.get("tool_calls", [])],
            latency_ms=cache_latency_ms,
            session_id=session_id,
        )

    # Correction-exemplar injection: the model sees past (mistake -> fix)
    # pairs for similar requests up front, cutting first-attempt failures
    # instead of only recovering from them via the retry loop below. Only
    # the outbound prompt changes -- transcript/cache keep the original.
    llm_message = await build_exemplar_message(agent_row.id, message, scil_normalized, scil_config)

    existing_session = await session_service.get_session(
        app_name=app_name, user_id=user_id, session_id=session_id
    )
    if existing_session is None:
        await session_service.create_session(
            app_name=app_name, user_id=user_id, session_id=session_id, state=state_delta
        )

    start = time.monotonic()
    outcome = await _execute_run(
        adk_agent=adk_agent,
        session_service=session_service,
        app_name=app_name,
        user_id=user_id,
        session_id=session_id,
        message=llm_message,
        state_delta=state_delta,
    )
    # Accumulated across every attempt (including ones later superseded by a
    # retry) so RCA can see the FAILED attempt's tool calls/transfers too —
    # not just the final, possibly-successful one. `outcome` itself gets
    # reassigned below on a retry; these lists never lose history.
    all_tool_call_records = list(outcome.tool_call_records)
    all_events = list(outcome.events)

    is_stale_session_error = (
        outcome.status == "error"
        and isinstance(outcome.error_message, str)
        and "Context variable not found" in outcome.error_message
    )
    is_tool_hallucination_error = (
        outcome.status == "error"
        and isinstance(outcome.error_message, str)
        and "not found" in outcome.error_message
        and "Available tools" in outcome.error_message
    )

    if is_stale_session_error:
        # The session resumed a since-retired agent that referenced session
        # state this conversation never set — that history is genuinely
        # incompatible with the current config, so drop it and replay this
        # one message fresh.
        all_events.append(
            {
                "event_type": "stale_session_retry",
                "detail": {"error": outcome.error_message},
                "offset_ms": int((time.monotonic() - start) * 1000),
                "sequence": len(all_events),
            }
        )
        await session_service.delete_session(app_name=app_name, user_id=user_id, session_id=session_id)
        await session_service.create_session(
            app_name=app_name, user_id=user_id, session_id=session_id, state=state_delta
        )
        outcome = await _execute_run(
            adk_agent=adk_agent,
            session_service=session_service,
            app_name=app_name,
            user_id=user_id,
            session_id=session_id,
            message=llm_message,
            state_delta=state_delta,
        )
        all_tool_call_records += outcome.tool_call_records
        all_events += outcome.events
    elif is_tool_hallucination_error:
        # A pure-router agent with no tools of its own (e.g. the orchestrator)
        # occasionally calls a specialist's tool directly instead of
        # transferring first — ADK has no graceful fallback for an unknown
        # function name and raises hard. This is a one-off bad model sample on
        # an otherwise-healthy session, not stale state, so resample on the
        # SAME session rather than deleting potentially long conversation
        # history just to fix a single bad turn. (The failed author was the
        # root agent itself, so even if that attempt's events already landed
        # in history, ADK's own session-resume logic falls back to the root
        # agent on the next turn regardless — safe to retry in place.)
        all_events.append(
            {
                "event_type": "orchestrator_hallucination_retry",
                "detail": {"error": outcome.error_message},
                "offset_ms": int((time.monotonic() - start) * 1000),
                "sequence": len(all_events),
            }
        )
        outcome = await _execute_run(
            adk_agent=adk_agent,
            session_service=session_service,
            app_name=app_name,
            user_id=user_id,
            session_id=session_id,
            message=llm_message,
            state_delta=state_delta,
        )
        all_tool_call_records += outcome.tool_call_records
        all_events += outcome.events

    response_text = _resolve_response_text(outcome)

    # --- SCIL self-correction loop (validators configured on this agent) ---
    # Validation failures are NOT turn errors: the model answered, it just
    # answered wrong in a deterministically-detectable way. Retry the SAME
    # model on the SAME session with structured feedback (plus a known-good
    # fix for this error class from correction memory, if one exists) before
    # anyone pays for a bigger model or a manual retry. Mirrors the existing
    # stale-session/hallucination self-heals above: non-streaming path only.
    scil_retries = 0
    scil_validation = None

    async def _validate_this_attempt() -> ValidationResult:
        """Deterministic validators first (free); if they pass and this
        agent has hallucination detection + the LLM-judge groundedness tier
        both enabled, spend the extra model call to check groundedness too.
        Then, if entity resolution is enabled, catch the failure class
        neither of the above can see: valid SQL, a real tool call, zero rows
        because the searched-for literal was misspelled (see
        app/scil/entities.py). Any failure flows into the exact same retry
        loop below."""
        result = validate_output(
            response_text, scil_config.validators, agent_row, outcome.tool_calls, bool(adk_agent.tools)
        )
        if (
            result.ok
            and "hallucination" in scil_config.validators
            and scil_config.hallucination_groundedness_check
            and outcome.tool_calls
        ):
            result = await check_groundedness(response_text, outcome.tool_calls, agent_row)
        if result.ok and "entity_resolution" in scil_config.validators and outcome.tool_calls:
            result = await resolve_entity_mismatch(agent_row.id, outcome.tool_calls)
        return result

    if scil_config.enabled and scil_config.validators and outcome.status == "success":
        scil_validation = await _validate_this_attempt()
        first_failure = None if scil_validation.ok else scil_validation
        first_failed_text = response_text
        while not scil_validation.ok and scil_retries < scil_config.max_retries:
            known_correction = await lookup_known_correction(
                agent_row.id, scil_validation.error_signature, scil_normalized
            )
            correction_message = build_correction_message(
                original_message=message,
                failed_output=response_text,
                error_signature=scil_validation.error_signature,
                error_detail=scil_validation.error_detail or "",
                known_correction=known_correction,
            )
            scil_retries += 1
            outcome = await _execute_run(
                adk_agent=adk_agent,
                session_service=session_service,
                app_name=app_name,
                user_id=user_id,
                session_id=session_id,
                message=correction_message,
                state_delta=state_delta,
            )
            all_tool_call_records += outcome.tool_call_records
            all_events += outcome.events
            if outcome.status != "success":
                break
            response_text = _resolve_response_text(outcome)
            scil_validation = await _validate_this_attempt()
        if first_failure is not None and outcome.status == "success" and scil_validation.ok:
            # The retry fixed it — remember (input, mistake, fix) so the next
            # similar request either avoids the retry entirely (correction
            # memory feeds the next failure's feedback) or, once cached,
            # skips the LLM altogether.
            save_correction_fire_and_forget(
                agent_id=agent_row.id,
                normalized=scil_normalized,
                failed_output={"response_text": first_failed_text},
                error_signature=first_failure.error_signature,
                error_detail=first_failure.error_detail or "",
                corrected_output={
                    "response_text": response_text,
                    "tool_calls": [tc.model_dump() for tc in outcome.tool_calls],
                },
            )
        if (
            not scil_validation.ok
            and scil_validation.error_signature
            and scil_validation.error_signature.startswith("Hallucination:")
        ):
            # Retries exhausted and it's still hallucinating — the user is
            # about to receive the best-available (still-invented) answer.
            # Nothing left to auto-fix; make sure it's at least visible.
            all_events.append(
                {
                    "event_type": "hallucination_unresolved",
                    "detail": {
                        "error_signature": scil_validation.error_signature,
                        "error_detail": scil_validation.error_detail,
                    },
                    "offset_ms": int((time.monotonic() - start) * 1000),
                    "sequence": len(all_events),
                }
            )
        if "entity_resolution" in scil_config.validators and outcome.tool_calls:
            # Organic memory growth: remember whatever literal(s) this turn's
            # FINAL (possibly retried) successful data_query_tool call(s)
            # resolved, regardless of whether some other validator also
            # flagged this turn — a future typo's correction candidate
            # shouldn't depend on this exact turn having been otherwise
            # perfect. No-ops for turns with no data_query_tool calls at all.
            remember_entities_fire_and_forget(agent_row.id, outcome.tool_calls)

    latency_ms = int((time.monotonic() - start) * 1000)
    model = agent_row.model_config_json.get("model", "gemini-2.5-flash")
    error_category = classify_error(
        status=outcome.status,
        error_message=outcome.error_message,
        events=all_events,
        tool_call_records=all_tool_call_records,
    )

    log_invocation_fire_and_forget(
        agent_id=agent_row.id,
        agent_version=agent_row.current_version,
        workspace_id=agent_row.workspace_id,
        trace_id=session_id,
        otel_trace_id=outcome.otel_trace_id,
        status=outcome.status,
        error_category=error_category,
        latency_ms=latency_ms,
        input_tokens=outcome.input_tokens,
        output_tokens=outcome.output_tokens,
        estimated_cost_usd=estimate_cost_usd(model, outcome.input_tokens, outcome.output_tokens),
        error_message=outcome.error_message,
        invoked_by=user_id,
        transcript={"message": message, "response_text": response_text},
        tool_calls=all_tool_call_records,
        events=all_events,
        resolved_author=outcome.last_author,
    )

    log_metrics_fire_and_forget(
        agent_id=agent_row.id,
        request_id=scil_request_id,
        route="llm_retry" if scil_retries else ("llm" if scil_config.enabled else "disabled"),
        llm_calls=1 + scil_retries,
        retries=scil_retries,
        input_tokens=outcome.input_tokens,
        output_tokens=outcome.output_tokens,
        latency_ms=latency_ms,
    )
    # Passive, out-of-band groundedness sampling -- independent of the
    # blocking hallucination_groundedness_check (which retries), this only
    # ever observes and logs a random fraction of successful turns. See
    # app/scil/eval_runner.py.
    if scil_config.enabled and scil_config.eval_sample_rate > 0 and outcome.status == "success":
        sample_groundedness_fire_and_forget(
            agent_id=agent_row.id,
            request_id=scil_request_id,
            input_text=message,
            response_text=response_text,
            tool_calls=outcome.tool_calls,
            sample_rate=scil_config.eval_sample_rate,
            agent_row=agent_row,
        )
    # Cache only what passed validation (or ran with no validators configured)
    # — a response that exhausted its retries still invalid gets RETURNED
    # (the user sees the best available answer) but never CACHED, so the
    # mistake can't be replayed to future callers as a "validated" hit.
    # A turn with ANY failed tool call is likewise uncacheable: the model
    # "succeeds" by apologizing gracefully (e.g. an RLS authorization
    # refusal), and an apology must never be served as a cached answer.
    scil_output_valid = (scil_validation is None or scil_validation.ok) and not any(
        tc.get("status") == "error" for tc in all_tool_call_records
    )
    if scil_config.enabled and outcome.status == "success" and scil_output_valid:
        save_cache_entry_fire_and_forget(
            agent_row.id,
            scil_normalized,
            {"response_text": response_text, "tool_calls": [tc.model_dump() for tc in outcome.tool_calls]},
            ttl_hours=scil_config.cache_ttl_hours,
            scope_key=scil_config.scope_key(user_id),
        )

    if outcome.status == "error":
        raise HTTPException(status_code=502, detail=f"Run failed: {outcome.error_message}")

    return PlaygroundRunResponse(
        response_text=response_text,
        tool_calls=outcome.tool_calls,
        latency_ms=latency_ms,
        session_id=session_id,
    )


@router.post("/run", response_model=PlaygroundRunResponse, dependencies=[Depends(rate_limit_principal)])
async def run_playground(
    payload: PlaygroundRunRequest,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_role("admin", "developer")),
    x_gemini_api_key: str | None = Header(default=None, alias="X-Gemini-Api-Key"),
    x_anthropic_api_key: str | None = Header(default=None, alias="X-Anthropic-Api-Key"),
) -> PlaygroundRunResponse:
    agent_row = await db.get(AgentRow, payload.agent_id)
    if agent_row is None or agent_row.workspace_id != principal.workspace_id:
        raise HTTPException(status_code=404, detail="Agent not found")

    adk_agent = await get_or_build_agent(db, payload.agent_id, version=None)
    user_id = payload.user_id or "playground-user"
    session_id = payload.session_id or f"playground-{uuid.uuid4()}"

    # BYOK: Playground is require_role("admin"/"developer")-gated internal
    # tooling, not public traffic — falls back to the operator's own key so
    # a developer can iterate on a Claude-model agent without needing their
    # own Anthropic key on hand. A supplied header still takes priority.
    gemini_key, anthropic_key = resolve_request_api_keys(
        required_providers(adk_agent), x_gemini_api_key, x_anthropic_api_key, allow_operator_fallback=True
    )

    try:
        with use_api_keys(gemini_key, anthropic_key):
            return await _run_turn(
                db=db,
                adk_agent=adk_agent,
                agent_row=agent_row,
                session_service=_playground_sessions,
                app_name="agent_forge_playground",
                user_id=user_id,
                session_id=session_id,
                message=payload.message,
                state_delta=payload.state_delta,
            )
    finally:
        # This tree is built fresh every call (version=None, never cached) —
        # unlike a cached build, nobody else will ever reuse these toolsets,
        # so their MCP subprocess(es) must be closed here or they leak.
        await close_agent_toolsets(adk_agent)


@invoke_router.post(
    "/{agent_id}/invoke", response_model=PlaygroundRunResponse, dependencies=[Depends(rate_limit_principal)]
)
async def invoke_published_agent(
    agent_id: uuid.UUID,
    payload: InvokeRequest,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_role("admin")),
    x_gemini_api_key: str | None = Header(default=None, alias="X-Gemini-Api-Key"),
    x_anthropic_api_key: str | None = Header(default=None, alias="X-Anthropic-Api-Key"),
) -> PlaygroundRunResponse:
    """Runs the *published* version of an agent — the stable surface an
    external caller (e.g. StudyBuddy) hits, as opposed to /playground/run
    which always rebuilds from the live draft tables."""
    agent_row = await db.get(AgentRow, agent_id)
    if agent_row is None or agent_row.workspace_id != principal.workspace_id:
        raise HTTPException(status_code=404, detail="Agent not found")
    if agent_row.status != "published":
        raise HTTPException(status_code=409, detail="Agent has no published version")

    adk_agent = await get_or_build_agent(db, agent_id, version=agent_row.current_version)
    user_id = payload.user_id or "external-caller"
    session_id = payload.session_id or f"invoke-{uuid.uuid4()}"

    # BYOK: /invoke is require_role("admin")-gated machine-to-machine
    # traffic (e.g. StudyBuddy), not public chat — same operator-fallback
    # treatment as Playground, see run_playground's comment above.
    gemini_key, anthropic_key = resolve_request_api_keys(
        required_providers(adk_agent), x_gemini_api_key, x_anthropic_api_key, allow_operator_fallback=True
    )

    with use_api_keys(gemini_key, anthropic_key):
        return await _run_turn(
            db=db,
            adk_agent=adk_agent,
            agent_row=agent_row,
            session_service=_invoke_sessions,
            app_name="agent_forge_invoke",
            user_id=user_id,
            session_id=session_id,
            message=payload.message,
            state_delta=payload.state_delta,
        )
