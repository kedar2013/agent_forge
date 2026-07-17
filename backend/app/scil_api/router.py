


"""Admin API for SCIL (Self-Correcting Intelligence Layer) — metrics
visibility and semantic-cache curation. Mirrors app/debug_api/router.py's
auth/pagination/workspace-scoping conventions.

Gated to admin only (not viewer/developer like debug_api) — cached Q&A
pairs can contain another user's request/response content, which is more
sensitive to expose broadly than a trace's own timing/tool-call shape.
"""

import time
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent_runtime.builder import get_or_build_agent
from app.chat_api.router import _DEFAULT_CHAT_STATE, _identity_state_delta
from app.db import get_db
from app.embeddings import embed_text
from app.models.agents import Agent
from app.models.scil import (
    ScilCorrectionMemory,
    ScilEntityMemory,
    ScilEvalCase,
    ScilEvalRun,
    ScilGroundednessSample,
    ScilMetrics,
    ScilSemanticCache,
)
from app.playground_api.router import _invoke_sessions, _run_turn
from app.principal import Principal, require_role
from app.scil.eval_runner import judge_regression_case
from app.scil.normalizer import normalize
from app.schemas.scil import (
    ScilCacheEntry,
    ScilCacheListResponse,
    ScilCacheSimilarityCheckRequest,
    ScilCacheSimilarityCheckResponse,
    ScilCorrectionEntry,
    ScilCorrectionListResponse,
    ScilEntityEntry,
    ScilEntityListResponse,
    ScilEvalBatchSummary,
    ScilEvalCaseCreate,
    ScilEvalCaseEntry,
    ScilEvalRunRequest,
    ScilEvalRunResult,
    ScilGroundednessSampleEntry,
    ScilGroundednessSummary,
    ScilGroundednessSummaryPoint,
    ScilMetricsSummary,
    ScilPurgeRequest,
    ScilRouteCount,
    ScilTimeseriesPoint,
)

router = APIRouter(prefix="/scil", tags=["scil"])

# Matches ScilConfig.cache_similarity_threshold's default in app/scil/runner.py
# -- duplicated as a literal here rather than imported, since importing
# ScilConfig would pull in the whole runner module for one float.
_DEFAULT_CACHE_SIMILARITY_THRESHOLD = 0.80


def _cache_similarity_threshold(agent: Agent) -> float:
    return float((agent.model_config_json or {}).get("scil", {}).get("cache_similarity_threshold", _DEFAULT_CACHE_SIMILARITY_THRESHOLD))


async def _get_owned_agent(db: AsyncSession, agent_id: uuid.UUID, principal: Principal) -> Agent:
    agent = await db.get(Agent, agent_id)
    if agent is None or agent.workspace_id != principal.workspace_id:
        raise HTTPException(status_code=404, detail="Agent not found")
    return agent


@router.get("/cache/entries", response_model=ScilCacheListResponse)
async def list_cache_entries(
    agent_id: uuid.UUID | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_role("admin")),
) -> ScilCacheListResponse:
    base = (
        select(ScilSemanticCache, Agent)
        .join(Agent, Agent.id == ScilSemanticCache.agent_id)
        .where(Agent.workspace_id == principal.workspace_id)
    )
    if agent_id:
        base = base.where(ScilSemanticCache.agent_id == agent_id)

    total = (
        await db.scalar(select(func.count()).select_from(base.with_only_columns(ScilSemanticCache.id).subquery()))
    ) or 0

    result = await db.execute(base.order_by(ScilSemanticCache.created_at.desc()).limit(limit).offset(offset))
    items = [
        ScilCacheEntry(
            id=row.id,
            agent_id=row.agent_id,
            agent_name=agent.name,
            input_text=row.input_text,
            output_type=row.output_type,
            hit_count=row.hit_count,
            validated=row.validated,
            created_at=row.created_at,
            last_hit_at=row.last_hit_at,
            similarity_threshold=_cache_similarity_threshold(agent),
        )
        for row, agent in result
    ]
    return ScilCacheListResponse(items=items, total=total, limit=limit, offset=offset)


@router.post("/cache/similarity-check", response_model=ScilCacheSimilarityCheckResponse)
async def check_cache_similarity(
    payload: ScilCacheSimilarityCheckRequest,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_role("admin")),
) -> ScilCacheSimilarityCheckResponse:
    """Answers "why didn't X hit the cache for Y" directly, using the exact
    same normalize -> embed -> cosine pipeline app/scil/cache.py's lookup()
    uses, against the agent's CURRENT configured threshold — a read-only
    diagnostic, no cache rows read or written. embed_text's vectors are
    already L2-normalized (see app/embeddings.py), so cosine similarity
    reduces to a plain dot product."""
    agent = await _get_owned_agent(db, payload.agent_id, principal)
    threshold = _cache_similarity_threshold(agent)

    text_a = normalize(payload.text_a).normalized_text
    text_b = normalize(payload.text_b).normalized_text
    vec_a = embed_text(text_a)
    vec_b = embed_text(text_b)
    similarity = sum(a * b for a, b in zip(vec_a, vec_b))

    return ScilCacheSimilarityCheckResponse(
        similarity=round(similarity, 4), threshold=threshold, would_hit=similarity >= threshold
    )


@router.delete("/cache/entries/{entry_id}", status_code=204)
async def delete_cache_entry(
    entry_id: int,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_role("admin")),
) -> None:
    row = (
        await db.execute(
            select(ScilSemanticCache)
            .join(Agent, Agent.id == ScilSemanticCache.agent_id)
            .where(ScilSemanticCache.id == entry_id, Agent.workspace_id == principal.workspace_id)
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Cache entry not found")
    await db.delete(row)
    await db.commit()


@router.post("/cache/purge", status_code=204)
async def purge_cache(
    payload: ScilPurgeRequest,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_role("admin")),
) -> None:
    await _get_owned_agent(db, payload.agent_id, principal)
    await db.execute(delete(ScilSemanticCache).where(ScilSemanticCache.agent_id == payload.agent_id))
    await db.commit()


@router.get("/corrections", response_model=ScilCorrectionListResponse)
async def list_corrections(
    agent_id: uuid.UUID | None = None,
    error_signature: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_role("admin")),
) -> ScilCorrectionListResponse:
    base = (
        select(ScilCorrectionMemory, Agent.name)
        .join(Agent, Agent.id == ScilCorrectionMemory.agent_id)
        .where(Agent.workspace_id == principal.workspace_id)
    )
    if agent_id:
        base = base.where(ScilCorrectionMemory.agent_id == agent_id)
    if error_signature:
        base = base.where(ScilCorrectionMemory.error_signature == error_signature)

    total = (
        await db.scalar(select(func.count()).select_from(base.with_only_columns(ScilCorrectionMemory.id).subquery()))
    ) or 0

    result = await db.execute(base.order_by(ScilCorrectionMemory.created_at.desc()).limit(limit).offset(offset))
    items = [
        ScilCorrectionEntry(
            id=row.id,
            agent_id=row.agent_id,
            agent_name=agent_name,
            input_text=row.input_text,
            error_signature=row.error_signature,
            error_detail=row.error_detail,
            correction_source=row.correction_source,
            reuse_count=row.reuse_count,
            created_at=row.created_at,
        )
        for row, agent_name in result
    ]
    return ScilCorrectionListResponse(items=items, total=total, limit=limit, offset=offset)


@router.delete("/corrections/{correction_id}", status_code=204)
async def delete_correction(
    correction_id: int,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_role("admin")),
) -> None:
    row = (
        await db.execute(
            select(ScilCorrectionMemory)
            .join(Agent, Agent.id == ScilCorrectionMemory.agent_id)
            .where(ScilCorrectionMemory.id == correction_id, Agent.workspace_id == principal.workspace_id)
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Correction not found")
    await db.delete(row)
    await db.commit()


@router.get("/entities", response_model=ScilEntityListResponse)
async def list_entities(
    agent_id: uuid.UUID | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_role("admin")),
) -> ScilEntityListResponse:
    """Curation surface for scil_entity_memory (app/scil/entities.py) — same
    admin-only, workspace-scoped conventions as /cache/entries and
    /corrections. A wrongly-remembered entity (e.g. a typo that itself got
    written once) can be deleted here before it corrupts a future match."""
    base = (
        select(ScilEntityMemory, Agent.name)
        .join(Agent, Agent.id == ScilEntityMemory.agent_id)
        .where(Agent.workspace_id == principal.workspace_id)
    )
    if agent_id:
        base = base.where(ScilEntityMemory.agent_id == agent_id)

    total = (
        await db.scalar(select(func.count()).select_from(base.with_only_columns(ScilEntityMemory.id).subquery()))
    ) or 0

    result = await db.execute(base.order_by(ScilEntityMemory.use_count.desc()).limit(limit).offset(offset))
    items = [
        ScilEntityEntry(
            id=row.id,
            agent_id=row.agent_id,
            agent_name=agent_name,
            entity_text=row.entity_text,
            use_count=row.use_count,
            created_at=row.created_at,
            last_used_at=row.last_used_at,
        )
        for row, agent_name in result
    ]
    return ScilEntityListResponse(items=items, total=total, limit=limit, offset=offset)


@router.delete("/entities/{entity_id}", status_code=204)
async def delete_entity(
    entity_id: int,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_role("admin")),
) -> None:
    row = (
        await db.execute(
            select(ScilEntityMemory)
            .join(Agent, Agent.id == ScilEntityMemory.agent_id)
            .where(ScilEntityMemory.id == entity_id, Agent.workspace_id == principal.workspace_id)
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Entity not found")
    await db.delete(row)
    await db.commit()


@router.get("/metrics/timeseries", response_model=list[ScilTimeseriesPoint])
async def metrics_timeseries(
    range_days: int = Query(30, ge=1, le=365),
    agent_id: uuid.UUID | None = None,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_role("admin")),
) -> list[ScilTimeseriesPoint]:
    since = datetime.now(timezone.utc) - timedelta(days=range_days)
    day = func.date_trunc("day", ScilMetrics.created_at).label("day")

    query = (
        select(day, ScilMetrics.route, func.count(), func.sum(ScilMetrics.llm_calls))
        .join(Agent, Agent.id == ScilMetrics.agent_id)
        .where(ScilMetrics.created_at >= since, Agent.workspace_id == principal.workspace_id)
        .group_by(day, ScilMetrics.route)
        .order_by(day)
    )
    if agent_id:
        query = query.where(ScilMetrics.agent_id == agent_id)

    result = await db.execute(query)
    return [
        ScilTimeseriesPoint(date=d.strftime("%Y-%m-%d"), route=route, count=count, llm_calls=llm_calls or 0)
        for d, route, count, llm_calls in result
    ]


@router.get("/metrics/summary", response_model=ScilMetricsSummary)
async def metrics_summary(
    agent_id: uuid.UUID | None = None,
    from_date: datetime | None = None,
    to_date: datetime | None = None,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_role("admin")),
) -> ScilMetricsSummary:
    base = select(ScilMetrics).join(Agent, Agent.id == ScilMetrics.agent_id).where(
        Agent.workspace_id == principal.workspace_id
    )
    if agent_id:
        base = base.where(ScilMetrics.agent_id == agent_id)
    if from_date:
        base = base.where(ScilMetrics.created_at >= from_date)
    if to_date:
        base = base.where(ScilMetrics.created_at <= to_date)

    scoped = base.subquery()
    grouped = await db.execute(
        select(
            scoped.c.route,
            func.count().label("count"),
            func.sum(scoped.c.llm_calls).label("llm_calls"),
            func.avg(scoped.c.latency_ms).label("avg_latency_ms"),
        ).group_by(scoped.c.route)
    )
    routes: list[ScilRouteCount] = []
    avg_latency_by_route: dict[str, float] = {}
    total_requests = 0
    total_llm_calls = 0
    cache_hits = 0
    retried_turns = 0
    for route, count, llm_calls, avg_latency_ms in grouped:
        routes.append(ScilRouteCount(route=route, count=count, llm_calls=llm_calls or 0))
        avg_latency_by_route[route] = round(float(avg_latency_ms), 1) if avg_latency_ms is not None else 0.0
        total_requests += count
        total_llm_calls += llm_calls or 0
        if route == "cache_hit":
            cache_hits = count
        elif route == "llm_retry":
            retried_turns = count

    # Retry success rate: an auto_retry correction-memory row is written
    # exactly once per turn the self-correction loop RECOVERED (see
    # playground_api._run_turn), so recovered/retried over the same
    # agent+time window is the success rate — no extra bookkeeping column.
    corrections_query = (
        select(func.count())
        .select_from(ScilCorrectionMemory)
        .join(Agent, Agent.id == ScilCorrectionMemory.agent_id)
        .where(
            Agent.workspace_id == principal.workspace_id,
            ScilCorrectionMemory.correction_source == "auto_retry",
        )
    )
    if agent_id:
        corrections_query = corrections_query.where(ScilCorrectionMemory.agent_id == agent_id)
    if from_date:
        corrections_query = corrections_query.where(ScilCorrectionMemory.created_at >= from_date)
    if to_date:
        corrections_query = corrections_query.where(ScilCorrectionMemory.created_at <= to_date)
    recovered_turns = (await db.scalar(corrections_query)) or 0

    # Corrected hallucinations only (see ScilMetricsSummary.hallucination_flags
    # docstring) — same query shape as recovered_turns above, filtered by
    # error-signature category instead of correction_source.
    hallucination_query = (
        select(func.count())
        .select_from(ScilCorrectionMemory)
        .join(Agent, Agent.id == ScilCorrectionMemory.agent_id)
        .where(
            Agent.workspace_id == principal.workspace_id,
            ScilCorrectionMemory.error_signature.like("Hallucination:%"),
        )
    )
    if agent_id:
        hallucination_query = hallucination_query.where(ScilCorrectionMemory.agent_id == agent_id)
    if from_date:
        hallucination_query = hallucination_query.where(ScilCorrectionMemory.created_at >= from_date)
    if to_date:
        hallucination_query = hallucination_query.where(ScilCorrectionMemory.created_at <= to_date)
    hallucination_flags = (await db.scalar(hallucination_query)) or 0

    return ScilMetricsSummary(
        total_requests=total_requests,
        llm_calls=total_llm_calls,
        llm_calls_avoided=cache_hits,
        cache_hit_rate=round(cache_hits / total_requests, 4) if total_requests else 0.0,
        retried_turns=retried_turns,
        retry_success_rate=round(min(recovered_turns, retried_turns) / retried_turns, 4) if retried_turns else 0.0,
        avg_latency_ms_by_route=avg_latency_by_route,
        routes=routes,
        hallucination_flags=hallucination_flags,
    )


# --- Eval framework: golden-question regression suite ----------------------


async def _latest_run_by_case(db: AsyncSession, case_ids: list[int]) -> dict[int, ScilEvalRun]:
    """Most recent scil_eval_runs row per case_id, via DISTINCT ON — used to
    annotate the case list with current pass/fail without N+1 queries."""
    if not case_ids:
        return {}
    rows = (
        await db.execute(
            select(ScilEvalRun)
            .where(ScilEvalRun.case_id.in_(case_ids))
            .order_by(ScilEvalRun.case_id, ScilEvalRun.created_at.desc())
            .distinct(ScilEvalRun.case_id)
        )
    ).scalars()
    return {row.case_id: row for row in rows}


@router.get("/eval/cases", response_model=list[ScilEvalCaseEntry])
async def list_eval_cases(
    agent_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_role("admin")),
) -> list[ScilEvalCaseEntry]:
    await _get_owned_agent(db, agent_id, principal)
    cases = (
        (
            await db.execute(
                select(ScilEvalCase).where(ScilEvalCase.agent_id == agent_id).order_by(ScilEvalCase.created_at)
            )
        )
        .scalars()
        .all()
    )
    latest = await _latest_run_by_case(db, [c.id for c in cases])
    return [
        ScilEvalCaseEntry(
            id=c.id,
            agent_id=c.agent_id,
            question=c.question,
            expected_criteria=c.expected_criteria,
            is_active=c.is_active,
            created_at=c.created_at,
            last_passed=latest[c.id].passed if c.id in latest else None,
            last_run_at=latest[c.id].created_at if c.id in latest else None,
        )
        for c in cases
    ]


@router.post("/eval/cases", response_model=ScilEvalCaseEntry, status_code=201)
async def create_eval_case(
    payload: ScilEvalCaseCreate,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_role("admin")),
) -> ScilEvalCaseEntry:
    await _get_owned_agent(db, payload.agent_id, principal)
    case = ScilEvalCase(
        agent_id=payload.agent_id,
        question=payload.question,
        expected_criteria=payload.expected_criteria,
        created_by=str(principal.user_id) if principal.user_id else "admin-static-token",
    )
    db.add(case)
    await db.commit()
    await db.refresh(case)
    return ScilEvalCaseEntry(
        id=case.id,
        agent_id=case.agent_id,
        question=case.question,
        expected_criteria=case.expected_criteria,
        is_active=case.is_active,
        created_at=case.created_at,
    )


@router.delete("/eval/cases/{case_id}", status_code=204)
async def delete_eval_case(
    case_id: int,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_role("admin")),
) -> None:
    row = (
        await db.execute(
            select(ScilEvalCase)
            .join(Agent, Agent.id == ScilEvalCase.agent_id)
            .where(ScilEvalCase.id == case_id, Agent.workspace_id == principal.workspace_id)
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Eval case not found")
    await db.delete(row)
    await db.commit()


@router.post("/eval/run", response_model=ScilEvalBatchSummary)
async def run_eval_batch(
    payload: ScilEvalRunRequest,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_role("admin")),
) -> ScilEvalBatchSummary:
    """Runs every active golden case for this agent against its PUBLISHED
    version right now, grades each with an LLM judge, and writes one
    scil_eval_runs row per case under a shared batch_id. Synchronous (the
    caller waits for the whole batch) — there's no scheduler in this
    platform to hand it off to, and a handful of golden questions per agent
    finishes in well under the request timeout."""
    agent_row = await _get_owned_agent(db, payload.agent_id, principal)
    if agent_row.status != "published":
        raise HTTPException(status_code=409, detail="Agent has no published version to evaluate")

    cases = (
        (
            await db.execute(
                select(ScilEvalCase).where(
                    ScilEvalCase.agent_id == payload.agent_id, ScilEvalCase.is_active.is_(True)
                )
            )
        )
        .scalars()
        .all()
    )
    if not cases:
        raise HTTPException(status_code=422, detail="No active eval cases for this agent — add one first")

    model = (agent_row.model_config_json or {}).get("model", "gemini-2.5-flash")
    adk_agent = await get_or_build_agent(db, payload.agent_id, version=agent_row.current_version)
    batch_id = uuid.uuid4()
    results: list[ScilEvalRunResult] = []
    run_rows: list[ScilEvalRun] = []

    # Each case gets a brand-new session (unique session_id below), so this
    # state is what SEEDS it — same trusted-identity keys chat_api plants at
    # real session creation (_ensure_session_state), read by every built
    # agent's before_tool_callback for an RLS decision (agent_runtime/
    # builder.py). Without this, an RLS-scoped agent (e.g.
    # credit_facility_analyst) denies every eval turn with "No authenticated
    # identity on this session" regardless of whether the question itself
    # was answerable — this makes an eval run see what THIS admin would see,
    # same as if they asked the agent in chat themselves.
    identity_state = {**_DEFAULT_CHAT_STATE, **_identity_state_delta(principal)}

    for case in cases:
        start = time.monotonic()
        try:
            run_response = await _run_turn(
                db=db,
                adk_agent=adk_agent,
                agent_row=agent_row,
                session_service=_invoke_sessions,
                app_name="agent_forge_eval",
                user_id="scil-eval",
                session_id=f"eval-{batch_id}-{case.id}",
                message=case.question,
                state_delta=identity_state,
            )
            actual_response = run_response.response_text
        except HTTPException as exc:
            actual_response = f"(turn failed: {exc.detail})"

        verdict = await judge_regression_case(case.question, case.expected_criteria, actual_response, model)
        latency_ms = int((time.monotonic() - start) * 1000)
        run_rows.append(
            ScilEvalRun(
                batch_id=batch_id,
                agent_id=payload.agent_id,
                case_id=case.id,
                passed=verdict.passed,
                actual_response=actual_response,
                judge_reasoning=verdict.reasoning,
                latency_ms=latency_ms,
            )
        )
        results.append(
            ScilEvalRunResult(
                case_id=case.id,
                question=case.question,
                passed=verdict.passed,
                actual_response=actual_response,
                judge_reasoning=verdict.reasoning,
                latency_ms=latency_ms,
            )
        )

    db.add_all(run_rows)
    await db.commit()

    return ScilEvalBatchSummary(
        batch_id=batch_id,
        agent_id=payload.agent_id,
        total=len(results),
        passed=sum(1 for r in results if r.passed),
        results=results,
        created_at=datetime.now(timezone.utc),
    )


@router.get("/eval/runs/latest", response_model=ScilEvalBatchSummary)
async def latest_eval_batch(
    agent_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_role("admin")),
) -> ScilEvalBatchSummary:
    await _get_owned_agent(db, agent_id, principal)
    latest_batch_id = await db.scalar(
        select(ScilEvalRun.batch_id)
        .where(ScilEvalRun.agent_id == agent_id)
        .order_by(ScilEvalRun.created_at.desc())
        .limit(1)
    )
    if latest_batch_id is None:
        raise HTTPException(status_code=404, detail="No eval runs yet for this agent")

    rows = (
        (
            await db.execute(
                select(ScilEvalRun, ScilEvalCase.question)
                .join(ScilEvalCase, ScilEvalCase.id == ScilEvalRun.case_id)
                .where(ScilEvalRun.batch_id == latest_batch_id)
                .order_by(ScilEvalRun.id)
            )
        )
        .all()
    )
    results = [
        ScilEvalRunResult(
            case_id=run.case_id,
            question=question,
            passed=run.passed,
            actual_response=run.actual_response,
            judge_reasoning=run.judge_reasoning,
            latency_ms=run.latency_ms,
        )
        for run, question in rows
    ]
    return ScilEvalBatchSummary(
        batch_id=latest_batch_id,
        agent_id=agent_id,
        total=len(results),
        passed=sum(1 for r in results if r.passed),
        results=results,
        created_at=rows[0][0].created_at if rows else datetime.now(timezone.utc),
    )


# --- Eval framework: sampled live-traffic groundedness ----------------------


@router.get("/eval/groundedness/summary", response_model=ScilGroundednessSummary)
async def groundedness_summary(
    agent_id: uuid.UUID | None = None,
    range_days: int = Query(30, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_role("admin")),
) -> ScilGroundednessSummary:
    since = datetime.now(timezone.utc) - timedelta(days=range_days)
    day = func.date_trunc("day", ScilGroundednessSample.created_at).label("day")
    ts_query = (
        select(day, ScilGroundednessSample.grounded, func.count())
        .join(Agent, Agent.id == ScilGroundednessSample.agent_id)
        .where(Agent.workspace_id == principal.workspace_id, ScilGroundednessSample.created_at >= since)
    )
    if agent_id:
        ts_query = ts_query.where(ScilGroundednessSample.agent_id == agent_id)
    ts_query = ts_query.group_by(day, ScilGroundednessSample.grounded).order_by(day)

    by_day: dict[str, dict[str, int]] = {}
    for d, grounded, count in await db.execute(ts_query):
        key = d.strftime("%Y-%m-%d")
        bucket = by_day.setdefault(key, {"grounded": 0, "ungrounded": 0})
        bucket["grounded" if grounded else "ungrounded"] += count
    timeseries = [
        ScilGroundednessSummaryPoint(date=d, grounded=v["grounded"], ungrounded=v["ungrounded"])
        for d, v in sorted(by_day.items())
    ]
    total_samples = sum(p.grounded + p.ungrounded for p in timeseries)
    total_grounded = sum(p.grounded for p in timeseries)

    flagged_rows = (
        await db.execute(
            select(ScilGroundednessSample, Agent.name)
            .join(Agent, Agent.id == ScilGroundednessSample.agent_id)
            .where(
                Agent.workspace_id == principal.workspace_id,
                ScilGroundednessSample.created_at >= since,
                ScilGroundednessSample.grounded.is_(False),
                *([ScilGroundednessSample.agent_id == agent_id] if agent_id else []),
            )
            .order_by(ScilGroundednessSample.created_at.desc())
            .limit(20)
        )
    ).all()
    recent_flagged = [
        ScilGroundednessSampleEntry(
            id=row.id,
            agent_id=row.agent_id,
            agent_name=agent_name,
            input_text=row.input_text,
            grounded=row.grounded,
            reason=row.reason,
            created_at=row.created_at,
        )
        for row, agent_name in flagged_rows
    ]

    return ScilGroundednessSummary(
        total_samples=total_samples,
        grounded_rate=round(total_grounded / total_samples, 4) if total_samples else 0.0,
        timeseries=timeseries,
        recent_flagged=recent_flagged,
    )
