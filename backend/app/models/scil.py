import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import BigInteger, Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.embeddings import EMBEDDING_DIM

CORRECTION_SOURCES = ("auto_retry", "hitl", "user_feedback")
# 'escalated'/'hitl' are reserved for the escalation tier (not implemented
# yet) -- only these five routes are ever written today. 'llm_retry' means
# the self-correction loop fired at least once this turn (ScilMetrics.retries
# carries how many times); 'deterministic' means a configured template
# answered with zero LLM calls (see app/scil/templates.py).
SCIL_METRICS_ROUTES = ("disabled", "deterministic", "cache_hit", "llm", "llm_retry")


class ScilSemanticCache(Base):
    """A validated (input -> output) pair an agent turn can return directly,
    skipping the LLM entirely. "validated" here means "the underlying call
    that produced this returned status=success" -- there's no real output
    validator yet (SQL dry-run / JSON schema / citation check), that's a
    later phase; this column exists now so the later validator can flip
    already-cached rows without a schema change."""

    __tablename__ = "scil_semantic_cache"
    __table_args__ = (
        Index(
            "ix_scil_semantic_cache_agent_id_scope_input_hash", "agent_id", "scope_key", "input_hash", unique=True
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    agent_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("agents.id"), nullable=False)
    # "" for globally-shareable answers (the default). For agents whose
    # answers depend on WHO asks (cache_scope="user" in scil config -- RLS
    # domains like credit_facility_analyst), this is the asking user's id,
    # so one persona's cached answer can never be served to another.
    scope_key: Mapped[str] = mapped_column(String, nullable=False, default="")
    # sha256 of the normalized input -- the exact-match fast path, checked
    # before falling back to embedding cosine similarity.
    input_hash: Mapped[str] = mapped_column(String, nullable=False)
    input_text: Mapped[str] = mapped_column(Text, nullable=False)
    input_embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIM), nullable=False)
    output_payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    output_type: Mapped[str] = mapped_column(String, nullable=False)
    hit_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    validated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    ttl_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_hit_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ScilCorrectionMemory(Base):
    """(input, failed_output, error, corrected_output) pairs from the
    self-correction retry loop. Table exists per the SCIL schema spec, but
    nothing writes to it yet -- that's the self-correction loop (a later
    phase); this phase only ships the semantic cache."""

    __tablename__ = "scil_correction_memory"
    __table_args__ = (
        CheckConstraint(f"correction_source IN {CORRECTION_SOURCES}", name="scil_correction_memory_source_check"),
        Index("ix_scil_correction_memory_agent_id_error_signature", "agent_id", "error_signature"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    agent_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("agents.id"), nullable=False)
    input_text: Mapped[str] = mapped_column(Text, nullable=False)
    input_embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIM), nullable=False)
    failed_output: Mapped[dict] = mapped_column(JSONB, nullable=False)
    error_signature: Mapped[str] = mapped_column(String, nullable=False)
    error_detail: Mapped[str] = mapped_column(Text, nullable=False)
    corrected_output: Mapped[dict] = mapped_column(JSONB, nullable=False)
    correction_source: Mapped[str] = mapped_column(String, nullable=False)
    reuse_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ScilEntityMemory(Base):
    """The self-correcting half of entity resolution (see app/scil/entities.py):
    canonical entity strings ("Tesla Inc") seen in a WHERE-clause literal of a
    data_query_tool call that came back with >=1 row. Starts empty per agent
    and grows organically -- the first successful "Tesla Inc" lookup is what
    lets a later "Tesslla" typo self-correct instead of dead-ending in "no
    companies matched, did you mean...?". Closes the gap
    app/scil/normalizer.py's docstring calls out ("entity canonicalization ...
    stubbed") -- neither the SQL validator (the query IS valid SQL) nor the
    zero-tool-call hallucination check (a tool WAS called) can see this
    failure class."""

    __tablename__ = "scil_entity_memory"
    __table_args__ = (
        Index("ix_scil_entity_memory_agent_id_entity_text", "agent_id", "entity_text", unique=True),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    agent_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("agents.id"), nullable=False)
    entity_text: Mapped[str] = mapped_column(Text, nullable=False)
    entity_embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIM), nullable=False)
    use_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ScilEvalCase(Base):
    """A curated golden question / expected-answer pair for an agent's
    regression suite. Unlike the semantic cache and correction memory
    (which only ever see real production traffic), this is deliberately-
    authored coverage: re-run on demand (POST /scil/eval/run) to catch a
    prompt, tool, or config change that silently breaks a previously-working
    answer, before a real user hits it."""

    __tablename__ = "scil_eval_cases"
    __table_args__ = (Index("ix_scil_eval_cases_agent_id", "agent_id"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    agent_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("agents.id"), nullable=False)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    # Free-text description of what a correct answer must contain -- graded
    # by an LLM judge against the agent's actual response, not an exact
    # string match (the same fact can be phrased many valid ways).
    expected_criteria: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_by: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ScilEvalRun(Base):
    """One golden case's result from one regression batch. `batch_id` groups
    every case run together in a single POST /scil/eval/run call, so the
    dashboard can show "batch from 2 hours ago: 9/10 passed" instead of an
    undifferentiated stream of individual results."""

    __tablename__ = "scil_eval_runs"
    __table_args__ = (Index("ix_scil_eval_runs_agent_id_batch_id", "agent_id", "batch_id"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    batch_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    agent_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("agents.id"), nullable=False)
    case_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("scil_eval_cases.id", ondelete="CASCADE"), nullable=False
    )
    passed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    actual_response: Mapped[str] = mapped_column(Text, nullable=False)
    judge_reasoning: Mapped[str] = mapped_column(Text, nullable=False)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ScilGroundednessSample(Base):
    """A sampled slice of REAL live traffic (not golden cases), scored by
    the same LLM-judge groundedness check the blocking hallucination
    validator uses (app/scil/hallucination.check_groundedness), but run OUT
    OF the request path, fire-and-forget, on a configurable fraction of
    turns (model_config.scil.eval_sample_rate) -- passive monitoring that
    costs latency/tokens on a sample instead of blocking every turn on every
    agent regardless of whether that agent opted into the (retry-triggering)
    hallucination_groundedness_check."""

    __tablename__ = "scil_groundedness_samples"
    __table_args__ = (Index("ix_scil_groundedness_samples_agent_id_created_at", "agent_id", "created_at"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    agent_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("agents.id"), nullable=False)
    request_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    input_text: Mapped[str] = mapped_column(Text, nullable=False)
    grounded: Mapped[bool] = mapped_column(Boolean, nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ScilMetrics(Base):
    """One row per agent turn that passes through SCIL (see
    app/scil/runner.py), regardless of which route it took -- this is what
    the /api/scil/metrics/summary endpoint aggregates to show LLM-call
    reduction."""

    __tablename__ = "scil_metrics"
    __table_args__ = (Index("ix_scil_metrics_agent_id_created_at", "agent_id", "created_at"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    agent_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    request_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    route: Mapped[str] = mapped_column(String, nullable=False)
    llm_calls: Mapped[int] = mapped_column(Integer, nullable=False)
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    retries: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
