import uuid
from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, DateTime, Index, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

GUARDRAIL_DIRECTIONS = ("input", "output")
# "block" = the callback replaced the real model turn/response — the user
# never saw the offending text. "redact" = output was allowed through with
# the flagged span(s) masked (pii/mnpi only — see guardrails.config).
GUARDRAIL_ACTIONS = ("block", "redact")


class GuardrailEvent(Base):
    """One guardrail check verdict — written synchronously, inside the
    before/after-model callback itself (see app/guardrails/service.py),
    never batched with the rest of a turn's logging the way AgentEventLog
    is. Deliberately NOT foreign-keyed to invocation_log.id: that row is
    only guaranteed to exist for durable-execution-enabled agents until the
    turn finishes (see agent_runtime/builder._resolve_durable_invocation_id),
    but a guardrail verdict — especially a block — must be provably recorded
    even if the rest of the turn crashes immediately after. `adk_invocation_id`
    is the stable, always-available correlation key; joining back to
    invocation_log (by its own adk_invocation_id column) is a query-time
    concern for the audit dashboard, not a schema-time one.

    Only a flagged check is ever written here — a passing check produces no
    row (same "only the exception is interesting" convention as
    scil_correction_memory).

    `agent_id` is a plain UUID, deliberately NOT a real foreign key (same
    reasoning as `ConfigAuditLog.entity_id`): a hash-chained row's fields
    are frozen into its `row_hash` forever, so an `ON DELETE SET NULL` (or
    any FK-driven mutation) on a later agent deletion would silently
    rewrite this column out from under an already-computed hash — turning
    a legitimate cascade into what `verify_event_chain` correctly reports
    as tampering. An audit trail must never be mutated by something else's
    delete, so this is a soft reference, resolved at query time only.

    `seq`/`prev_hash`/`row_hash` form a hash chain, same tamper-evidence
    property as `config_audit_log` (see app.audit_hash.compute_event_hash)
    but its own independent chain, not mixed into config_audit_log's —
    a runtime security-decision trail and a config-change history are
    different kinds of audit data with different writers/readers, and
    conflating them into one chain would only make both harder to reason
    about. `GET /dashboards/audit/verify-chain?chain=guardrail_events`
    recomputes and confirms this one."""

    __tablename__ = "guardrail_events"
    __table_args__ = (
        CheckConstraint(f"direction IN {GUARDRAIL_DIRECTIONS}", name="guardrail_events_direction_check"),
        CheckConstraint(f"action IN {GUARDRAIL_ACTIONS}", name="guardrail_events_action_check"),
        Index("ix_guardrail_events_workspace_id_created_at", "workspace_id", "created_at"),
        Index("ix_guardrail_events_agent_id_created_at", "agent_id", "created_at"),
        Index("ix_guardrail_events_adk_invocation_id", "adk_invocation_id"),
        UniqueConstraint("seq", name="uq_guardrail_events_seq"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    seq: Mapped[int] = mapped_column(BigInteger, autoincrement=True, nullable=False)
    workspace_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    agent_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    agent_name: Mapped[str | None] = mapped_column(String, nullable=True)
    adk_invocation_id: Mapped[str | None] = mapped_column(String, nullable=True)
    direction: Mapped[str] = mapped_column(String, nullable=False)
    check_name: Mapped[str] = mapped_column(String, nullable=False)
    action: Mapped[str] = mapped_column(String, nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Capped preview of the text the check fired on — never the full
    # payload, same "shape/evidence, not necessarily every byte" convention
    # as observability.rca.cap_payload.
    matched_preview: Mapped[str | None] = mapped_column(Text, nullable=True)
    detail: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    prev_hash: Mapped[str | None] = mapped_column(String, nullable=True)
    row_hash: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PolicyEvent(Base):
    """One DENIED access_policy decision (Python engine or OPA — see
    app.tool_registry.policy_engine/opa_client), written synchronously from
    agent_runtime.builder's before_tool_callback the moment a tool call is
    denied. Sibling to GuardrailEvent in every structural respect (same
    "only the exception is interesting" convention — an ALLOWED decision
    produces no row, since access is already the default-permitted path
    for a persona with a matching rule; only a denial is a governance
    event worth an audit trail — and same independent hash chain via
    app.audit_hash.compute_event_hash). `agent_id`/`policy_id` are plain
    UUIDs, not real foreign keys, for the identical reason GuardrailEvent.
    agent_id is — see that class's docstring."""

    __tablename__ = "policy_events"
    __table_args__ = (
        Index("ix_policy_events_workspace_id_created_at", "workspace_id", "created_at"),
        Index("ix_policy_events_agent_id_created_at", "agent_id", "created_at"),
        Index("ix_policy_events_adk_invocation_id", "adk_invocation_id"),
        UniqueConstraint("seq", name="uq_policy_events_seq"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    seq: Mapped[int] = mapped_column(BigInteger, autoincrement=True, nullable=False)
    workspace_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    agent_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    agent_name: Mapped[str | None] = mapped_column(String, nullable=True)
    adk_invocation_id: Mapped[str | None] = mapped_column(String, nullable=True)
    tool_name: Mapped[str] = mapped_column(String, nullable=False)
    policy_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    # "python" (policy_engine.apply_policy) or "opa" (opa_client.evaluate_opa_policy).
    engine: Mapped[str] = mapped_column(String, nullable=False)
    persona: Mapped[str | None] = mapped_column(String, nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    prev_hash: Mapped[str | None] = mapped_column(String, nullable=True)
    row_hash: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())