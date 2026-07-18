"""System Prompt Evaluator API — scores an agent's live instruction (or
arbitrary pasted prompt text) against the rubric in app/prompt_eval/rubric.py
and, for weak criteria, suggests a rewrite. Mirrors app/scil_api/router.py's
auth/pagination conventions.

Gated to admin + developer (not viewer/chat_user): read-only over content a
developer can already see via GET /agents/{id} (an agent's own
base_instruction/tools/sub_agents), but each run spends real LLM tokens on
the judge call, same "build/test" bucket as Playground and the SCIL eval
suite, not a passive dashboard a viewer should get for free.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models.prompt_eval import PromptEvalRun
from app.principal import Principal, require_role
from app.prompt_eval.rubric import CRITERIA
from app.prompt_eval.service import PromptEvalInputError, evaluate_prompt
from app.schemas.prompt_eval import (
    CriterionResultOut,
    PromptEvalCriterionInfo,
    PromptEvalRequest,
    PromptEvalResult,
    PromptEvalRunSummary,
)

router = APIRouter(prefix="/prompt-eval", tags=["prompt-eval"])


def _actor(principal: Principal) -> str:
    return principal.email or f"{principal.role} (static token)"


@router.get("/criteria", response_model=list[PromptEvalCriterionInfo])
async def list_criteria(
    principal: Principal = Depends(require_role("admin", "developer", "viewer")),
) -> list[PromptEvalCriterionInfo]:
    return [
        PromptEvalCriterionInfo(
            id=c.id, label=c.label, category=c.category, method=c.method, weight=c.weight, description=c.description
        )
        for c in CRITERIA
    ]


@router.post("/evaluate", response_model=PromptEvalResult)
async def evaluate(
    payload: PromptEvalRequest,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_role("admin", "developer")),
) -> PromptEvalResult:
    try:
        result = await evaluate_prompt(
            db,
            agent_id=payload.agent_id,
            prompt_text=payload.prompt_text,
            scope=payload.scope,
            model=payload.model,
            workspace_id=principal.workspace_id,
            actor=_actor(principal),
        )
    except PromptEvalInputError as exc:
        raise HTTPException(status_code=404 if payload.agent_id else 422, detail=str(exc)) from exc

    return PromptEvalResult(
        id=result.id,
        agent_id=result.agent_id,
        agent_name=result.agent_name,
        scope=result.scope,
        source_text=result.source_text,
        overall_score=result.overall_score,
        criteria=[CriterionResultOut(**c) for c in result.criteria],
        summary=result.summary,
        suggested_rewrite=result.suggested_rewrite,
        model_used=result.model_used,
        judge_error=result.judge_error,
        created_at=result.created_at,
    )


@router.get("/runs", response_model=list[PromptEvalRunSummary])
async def list_runs(
    agent_id: uuid.UUID | None = None,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_role("admin", "developer")),
) -> list[PromptEvalRunSummary]:
    query = select(PromptEvalRun).where(PromptEvalRun.workspace_id == principal.workspace_id)
    if agent_id:
        query = query.where(PromptEvalRun.agent_id == agent_id)
    query = query.order_by(PromptEvalRun.created_at.desc()).limit(limit).offset(offset)
    rows = (await db.execute(query)).scalars().all()
    return [
        PromptEvalRunSummary(
            id=r.id,
            agent_id=r.agent_id,
            agent_name=r.agent_name,
            scope=r.scope,
            overall_score=float(r.overall_score),
            summary=r.summary,
            model_used=r.model_used,
            judge_error=r.judge_error,
            created_by=r.created_by,
            created_at=r.created_at,
        )
        for r in rows
    ]


@router.get("/runs/{run_id}", response_model=PromptEvalResult)
async def get_run(
    run_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_role("admin", "developer")),
) -> PromptEvalResult:
    run = await db.get(PromptEvalRun, run_id)
    if run is None or run.workspace_id != principal.workspace_id:
        raise HTTPException(status_code=404, detail="Evaluation run not found")
    return PromptEvalResult(
        id=run.id,
        agent_id=run.agent_id,
        agent_name=run.agent_name,
        scope=run.scope,
        source_text=run.source_text,
        overall_score=float(run.overall_score),
        criteria=[CriterionResultOut(**c) for c in run.criteria_results],
        summary=run.summary,
        suggested_rewrite=run.suggested_rewrite,
        model_used=run.model_used,
        judge_error=run.judge_error,
        created_at=run.created_at,
    )
