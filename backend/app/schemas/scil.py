import uuid
from datetime import datetime

from pydantic import BaseModel


class ScilCacheEntry(BaseModel):
    id: int
    agent_id: uuid.UUID
    agent_name: str | None
    input_text: str
    output_type: str
    hit_count: int
    validated: bool
    created_at: datetime
    last_hit_at: datetime | None
    # This entry's owning agent's CURRENT model_config.scil.cache_similarity_
    # threshold (not a value frozen at write time — an agent's threshold can
    # change after this row was written, and the dashboard should always show
    # what a NEW question would be compared against, not history).
    similarity_threshold: float


class ScilCacheSimilarityCheckRequest(BaseModel):
    agent_id: uuid.UUID
    text_a: str
    text_b: str


class ScilCacheSimilarityCheckResponse(BaseModel):
    similarity: float
    threshold: float
    would_hit: bool


class ScilCacheListResponse(BaseModel):
    items: list[ScilCacheEntry]
    total: int
    limit: int
    offset: int


class ScilRouteCount(BaseModel):
    route: str
    count: int
    llm_calls: int


class ScilMetricsSummary(BaseModel):
    total_requests: int
    llm_calls: int
    llm_calls_avoided: int
    cache_hit_rate: float
    # Self-correction loop (route="llm_retry"): how many turns needed at
    # least one validation retry, and what fraction of those ended in a
    # validated answer (measured against auto_retry correction-memory
    # writes, which only happen on recovery).
    retried_turns: int
    retry_success_rate: float
    avg_latency_ms_by_route: dict[str, float]
    routes: list[ScilRouteCount]
    # Count of scil_correction_memory rows in this range whose error_signature
    # starts with "Hallucination:" — corrected hallucinations only. Turns that
    # exhausted their retries still hallucinating are NOT counted here (they
    # never got a correction-memory row); those are visible as
    # hallucination_unresolved events in the Debug Console/RCA instead.
    hallucination_flags: int


class ScilPurgeRequest(BaseModel):
    agent_id: uuid.UUID


class ScilCorrectionEntry(BaseModel):
    id: int
    agent_id: uuid.UUID
    agent_name: str | None
    input_text: str
    error_signature: str
    error_detail: str
    correction_source: str
    reuse_count: int
    created_at: datetime


class ScilCorrectionListResponse(BaseModel):
    items: list[ScilCorrectionEntry]
    total: int
    limit: int
    offset: int


class ScilEntityEntry(BaseModel):
    id: int
    agent_id: uuid.UUID
    agent_name: str | None
    entity_text: str
    use_count: int
    created_at: datetime
    last_used_at: datetime | None


class ScilEntityListResponse(BaseModel):
    items: list[ScilEntityEntry]
    total: int
    limit: int
    offset: int


class ScilTimeseriesPoint(BaseModel):
    """One (day, route) bucket — the dashboard pivots these into per-route
    series for the savings-over-time chart."""

    date: str
    route: str
    count: int
    llm_calls: int


class ScilEvalRunRequest(BaseModel):
    agent_id: uuid.UUID


class ScilEvalCaseCreate(BaseModel):
    agent_id: uuid.UUID
    question: str
    expected_criteria: str


class ScilEvalCaseEntry(BaseModel):
    id: int
    agent_id: uuid.UUID
    question: str
    expected_criteria: str
    is_active: bool
    created_at: datetime
    # Denormalized from this case's most recent scil_eval_runs row, if any
    # batch has run yet — lets the case list show current pass/fail without
    # a second round trip per case.
    last_passed: bool | None = None
    last_run_at: datetime | None = None


class ScilEvalRunResult(BaseModel):
    case_id: int
    question: str
    passed: bool
    actual_response: str
    judge_reasoning: str
    latency_ms: int


class ScilEvalBatchSummary(BaseModel):
    batch_id: uuid.UUID
    agent_id: uuid.UUID
    total: int
    passed: int
    results: list[ScilEvalRunResult]
    created_at: datetime


class ScilGroundednessSummaryPoint(BaseModel):
    date: str
    grounded: int
    ungrounded: int


class ScilGroundednessSampleEntry(BaseModel):
    id: int
    agent_id: uuid.UUID
    agent_name: str | None
    input_text: str
    grounded: bool
    reason: str | None
    created_at: datetime


class ScilGroundednessSummary(BaseModel):
    total_samples: int
    grounded_rate: float
    timeseries: list[ScilGroundednessSummaryPoint]
    recent_flagged: list[ScilGroundednessSampleEntry]
