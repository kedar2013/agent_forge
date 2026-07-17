import uuid
from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, Index, Integer, Numeric, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

INVOCATION_STATUSES = ("success", "error", "timeout")
TOOL_CALL_STATUSES = ("success", "error")
AUDIT_ENTITY_TYPES = ("agent", "tool", "skill", "access_policy", "data_entity")
AUDIT_ACTIONS = ("create", "update", "publish", "archive", "delete")
# "transfer" = agent-to-agent handoff (ADK's transfer_to_agent). The two
# "*_retry" types are the two self-heal paths _run_turn already had (see
# playground_api/router.py) — recorded as first-class events instead of
# silently retrying with no trace of it having happened. "model_text" is a
# text segment the model emitted (its reasoning/narration, often right
# before deciding to call a tool) — captured as its own waterfall step so
# the Debug Console can show "AI said X -> tool called with Y -> tool
# returned Z" in sequence, not just the tool calls in isolation.
# "hallucination_unresolved" = SCIL's hallucination validator (deterministic
# zero-tool-call check and/or the LLM-judge groundedness check) kept failing
# through every retry — the user got the best-available (still-invented)
# answer, with nothing left to auto-fix. See app/scil/validators.py and
# app/scil/hallucination.py.
AGENT_EVENT_TYPES = (
    "transfer",
    "orchestrator_hallucination_retry",
    "stale_session_retry",
    "model_text",
    "hallucination_unresolved",
)


class InvocationLog(Base):
    __tablename__ = "invocation_log"
    __table_args__ = (
        CheckConstraint(f"status IN {INVOCATION_STATUSES}", name="invocation_log_status_check"),
        Index("ix_invocation_log_agent_id_created_at", "agent_id", "created_at"),
        Index("ix_invocation_log_workspace_id_created_at", "workspace_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agent_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("agents.id"))
    agent_version: Mapped[int] = mapped_column(Integer, nullable=False)
    workspace_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    trace_id: Mapped[str | None] = mapped_column(String, nullable=True)
    # W3C trace id (32 hex chars) of the OpenTelemetry root span for this
    # invocation, distinct from `trace_id` above (which is the ADK session_id)
    # — this is what correlates a row here to a trace in Jaeger/Langfuse/etc.
    otel_trace_id: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String, nullable=False)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    estimated_cost_usd: Mapped[float | None] = mapped_column(Numeric(10, 6), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    # A best-effort RCA bucket computed at log time (see playground_api's
    # _classify_error) — "tool_error", "agent_handoff_failure",
    # "stale_session", "rate_limited", "timeout", "llm_safety_block",
    # "unknown_error", or a "recovered_*" variant of the first three when
    # the turn ultimately succeeded after a self-heal. NULL means a clean
    # run with no error and no self-heal. Never itself gated by a CHECK
    # constraint — this is a debugging aid, not a hard schema contract, and
    # the set of categories may grow without a migration.
    error_category: Mapped[str | None] = mapped_column(String, nullable=True)
    invoked_by: Mapped[str | None] = mapped_column(String, nullable=True)
    transcript: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ToolCallLog(Base):
    __tablename__ = "tool_call_log"
    __table_args__ = (
        CheckConstraint(f"status IN {TOOL_CALL_STATUSES}", name="tool_call_log_status_check"),
        Index("ix_tool_call_log_tool_id_created_at", "tool_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    invocation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("invocation_log.id", ondelete="CASCADE")
    )
    tool_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("tools.id"))
    # Denormalized name of whichever agent (orchestrator or specialist) was
    # active when this specific tool was called — closes the previously-known
    # gap where a chat turn's tool calls couldn't be attributed to the
    # specialist that actually made them, only to the top-level chat root.
    agent_name: Mapped[str | None] = mapped_column(String, nullable=True)
    # OpenTelemetry span id (16 hex chars) for this tool call, so a row here
    # can be matched to its exact span in the trace backend.
    otel_span_id: Mapped[str | None] = mapped_column(String, nullable=True)
    # Position of this call within its invocation, in the order it actually
    # completed — all of one invocation's ToolCallLog rows are written in a
    # single fire-and-forget batch after the run finishes (see
    # logging_hooks._write_invocation_log), so `created_at` alone can't be
    # used to reconstruct call order for the debug-console waterfall.
    call_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String, nullable=False)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Captured for RCA — what exactly did the model send this tool, and what
    # did the tool actually return. Size-capped at write time (see
    # playground_api._cap_payload) so a large legitimate response doesn't
    # bloat this table; a capped value is stored as
    # {"_truncated": true, "preview": "..."} rather than silently dropped.
    input: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    output: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AgentEventLog(Base):
    """Non-tool-call events within one invocation that matter for RCA:
    agent-to-agent hand-offs (ADK transfer_to_agent), the two self-heal
    retry paths in playground_api._run_turn, and model text segments
    (event_type="model_text", the model's own narration/reasoning text,
    stored in `detail.text` with `from_agent` set to whoever said it).
    Previously transfers/retries left no trace at all or were invisible
    after a silent same-turn retry, and model text was only ever visible
    baked into the final concatenated response — this table is what lets
    the Debug Console show "the orchestrator tried to call a specialist's
    tool directly, failed, and self-healed on retry" or "the AI said X,
    then called tool Y" instead of just a successful-looking final response
    with no history."""

    __tablename__ = "agent_event_log"
    __table_args__ = (
        CheckConstraint(f"event_type IN {AGENT_EVENT_TYPES}", name="agent_event_log_event_type_check"),
        Index("ix_agent_event_log_invocation_id", "invocation_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    invocation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("invocation_log.id", ondelete="CASCADE")
    )
    event_type: Mapped[str] = mapped_column(String, nullable=False)
    from_agent: Mapped[str | None] = mapped_column(String, nullable=True)
    to_agent: Mapped[str | None] = mapped_column(String, nullable=True)
    detail: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    offset_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ConfigAuditLog(Base):
    """Append-only. `seq`/`prev_hash`/`row_hash` form a hash chain — each row's
    hash covers its own fields plus the previous row's hash, so altering or
    deleting any past row breaks every hash after it. `GET
    /dashboards/audit/verify-chain` recomputes and confirms this."""

    __tablename__ = "config_audit_log"
    __table_args__ = (
        CheckConstraint(f"entity_type IN {AUDIT_ENTITY_TYPES}", name="config_audit_log_entity_type_check"),
        CheckConstraint(f"action IN {AUDIT_ACTIONS}", name="config_audit_log_action_check"),
        Index("ix_config_audit_log_entity_type_entity_id_created_at", "entity_type", "entity_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    seq: Mapped[int] = mapped_column(BigInteger, autoincrement=True, unique=True, nullable=False)
    workspace_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    entity_type: Mapped[str] = mapped_column(String, nullable=False)
    entity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    action: Mapped[str] = mapped_column(String, nullable=False)
    actor: Mapped[str | None] = mapped_column(String, nullable=True)
    diff: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    prev_hash: Mapped[str | None] = mapped_column(String, nullable=True)
    row_hash: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
