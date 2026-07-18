import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Numeric, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

PROMPT_EVAL_SCOPES = ("static", "effective")


class PromptEvalRun(Base):
    """One system-prompt-evaluator run: a rubric-scored critique (+ optional
    suggested rewrite) of either a real agent's instruction or arbitrary
    pasted prompt text. Persisted (rather than a fire-and-forget/ephemeral
    result) for the same reason scil_eval_runs is: so a developer/admin can
    track whether an agent's prompt quality is improving across edits, not
    just see one-off feedback that's gone the moment the response closes.

    `agent_id` is nullable — evaluating raw pasted text (no agent involved
    at all) is a first-class input, not just an agent-scoped feature.
    `agent_name` is a point-in-time snapshot, not a live join target: an
    agent can be renamed or deleted after a run without invalidating this
    row's own history, same reasoning as ToolCallLog/InvocationLog
    denormalizing what they need at write time rather than assuming the
    referenced row will still look the same later.
    """

    __tablename__ = "prompt_eval_runs"
    __table_args__ = (
        CheckConstraint(f"scope IN {PROMPT_EVAL_SCOPES}", name="prompt_eval_runs_scope_check"),
        Index("ix_prompt_eval_runs_agent_id_created_at", "agent_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    agent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id", ondelete="SET NULL"), nullable=True
    )
    agent_name: Mapped[str | None] = mapped_column(String, nullable=True)
    # "static" = the raw base_instruction (or pasted text) alone. "effective"
    # = base_instruction + attached skills, composed exactly the way
    # agent_runtime.builder.compose_instruction does — what the model
    # actually receives. Raw pasted text (no agent_id) is always "static".
    scope: Mapped[str] = mapped_column(String, nullable=False, default="static")
    source_text: Mapped[str] = mapped_column(Text, nullable=False)
    # [{"id": "...", "label": "...", "category": "...", "method": "deterministic"|"judged",
    #   "score": 1-5, "max_score": 5, "severity": "info"|"warning"|"critical",
    #   "rationale": "...", "suggestion": "..." | null}, ...]
    criteria_results: Mapped[list] = mapped_column(JSONB, nullable=False)
    # 0-100, weighted across every criterion in criteria_results.
    overall_score: Mapped[float] = mapped_column(Numeric(5, 1), nullable=False)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Full rewritten instruction text addressing the weakest-scoring
    # criteria, or NULL when nothing scored low enough to warrant one (see
    # prompt_eval.judge's threshold) — never a required field, since a
    # genuinely strong prompt shouldn't get a rewrite manufactured for it.
    suggested_rewrite: Mapped[str | None] = mapped_column(Text, nullable=True)
    # "gemini-3.5-flash" / "anthropic/claude-..." / null if the judge call
    # itself failed and this run is deterministic-checks-only.
    model_used: Mapped[str | None] = mapped_column(String, nullable=True)
    judge_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
