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
