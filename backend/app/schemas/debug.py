import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel


class TraceSummary(BaseModel):
    invocation_id: uuid.UUID
    trace_id: str | None
    otel_trace_id: str | None
    agent_id: uuid.UUID | None
    agent_name: str | None
    status: str
    error_category: str | None
    latency_ms: int
    tool_call_count: int
    invoked_by: str | None
    estimated_cost_usd: float | None
    created_at: datetime


class TraceListResponse(BaseModel):
    items: list[TraceSummary]
    total: int
    limit: int
    offset: int


class SpanNode(BaseModel):
    """One node in the reconstructed (or Jaeger-sourced) waterfall. `kind`
    distinguishes the root "agent.invocation" span, a "tool.*" child span
    per tool call, a "model" marker (a text segment the model emitted —
    its reasoning/narration, `output` holds the text — zero duration, a
    point in time not a span), a "transfer" marker (agent-to-agent
    hand-off — also zero duration), and a "retry" marker (one of the two
    self-heal paths in playground_api._run_turn firing)."""

    id: str
    parent_id: str | None
    kind: Literal["root", "tool", "model", "transfer", "retry"]
    name: str
    agent_name: str | None
    status: Literal["success", "error"]
    start_offset_ms: int
    duration_ms: int
    input: Any = None
    output: Any = None
    error_message: str | None = None


class RcaInfo(BaseModel):
    """Root-cause-analysis summary shown at the top of a trace's detail
    view — a plain-English diagnosis + suggested fix, keyed off
    InvocationLog.error_category (see observability.rca)."""

    category: str
    headline: str
    suggested_fix: str


class TraceDetail(BaseModel):
    summary: TraceSummary
    message: str | None
    response_text: str | None
    error_message: str | None
    rca: RcaInfo | None
    spans: list[SpanNode]
    spans_source: Literal["jaeger", "reconstructed"]
    jaeger_trace_url: str | None


class ReplayToolCall(BaseModel):
    name: str
    status: Literal["success", "error"]
    latency_ms: int
    agent_name: str | None
    input: Any = None
    output: Any = None
    error_message: str | None = None


class ReplayResponse(BaseModel):
    """Result of POST /debug/traces/{invocation_id}/replay — see
    app/replay/service.py. `matched_tool_call_count ==
    total_recorded_tool_call_count` means every tool call the replay made
    was fed a real historical output (a clean, fully-deterministic replay);
    fewer means the replayed trajectory diverged from the original (called
    a different set of tools, or ran past what was recorded into a real
    tool call) — informative on its own, not necessarily a bug in replay."""

    invocation_id: uuid.UUID
    original_response_text: str
    original_status: str
    replayed_response_text: str
    replayed_status: str
    replayed_error_message: str | None
    replayed_tool_calls: list[ReplayToolCall]
    replayed_input_tokens: int | None
    replayed_output_tokens: int | None
    replayed_estimated_cost_usd: float | None
    matched_tool_call_count: int
    total_recorded_tool_call_count: int


class LineageToolCall(BaseModel):
    name: str
    agent_name: str | None
    status: Literal["success", "error"]
    input: Any = None
    output: Any = None


class LineageGuardrailEvent(BaseModel):
    direction: Literal["input", "output"]
    check_name: str
    action: str
    reason: str | None


class LineagePolicyEvent(BaseModel):
    tool_name: str
    engine: str
    persona: str | None
    reason: str | None


class LineageResponse(BaseModel):
    """What grounded this answer, and what governance decisions applied to
    it — GET /debug/traces/{invocation_id}/lineage. Answer attribution is
    at the INVOCATION level (every tool call this turn made), not sentence-
    level: this platform doesn't attempt to attribute individual claims in
    the final text to individual tool calls, only to say which calls fed
    the turn that produced it."""

    invocation_id: uuid.UUID
    agent_name: str | None
    message: str | None
    response_text: str | None
    grounding_tool_calls: list[LineageToolCall]
    guardrail_events: list[LineageGuardrailEvent]
    policy_events: list[LineagePolicyEvent]
