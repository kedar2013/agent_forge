"""Orchestrates one System Prompt Evaluator run: resolves the input (an
existing agent's LIVE instruction, or arbitrary pasted text), runs the
deterministic checks (always, cheap) and the LLM judge (best-effort — a
judge failure degrades to deterministic-only rather than failing the whole
request, see JudgeError handling below), merges both into one weighted
rubric report, and persists a PromptEvalRun row.

Builds from the agent's LIVE config, never a published snapshot — same
reasoning Playground uses (agent_runtime.builder._build_from_live_config):
you want to evaluate what you're currently editing, not a frozen prior
version. Reuses builder.py's own live-load helpers directly rather than
re-querying agent_tools/agent_skills/agent_subagents a second time —
same cross-module reuse of an "internal" helper scil_api/router.py already
does with chat_api.router's _DEFAULT_CHAT_STATE/_identity_state_delta.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent_runtime.builder import (
    _load_live_skills,
    _load_live_subagent_ids,
    _load_live_tools,
    compose_instruction,
)
from app.models.agents import Agent
from app.models.prompt_eval import PromptEvalRun
from app.prompt_eval.deterministic_checks import ToolInfo, run_deterministic_checks
from app.prompt_eval.judge import DEFAULT_JUDGE_MODEL, JudgeError, run_judge
from app.prompt_eval.rubric import CRITERIA_BY_ID
from app.prompt_eval.types import CriterionResult


class PromptEvalInputError(Exception):
    pass


@dataclass
class _EvaluationInput:
    agent: Agent | None
    agent_name: str | None
    scope: str
    instruction_text: str
    tools: list[ToolInfo]
    sub_agent_names: list[str]
    has_output_schema: bool
    skills_have_few_shot: bool
    scil_enabled: bool
    durable_execution_enabled: bool
    planning_enabled: bool


async def _resolve_input(
    db: AsyncSession,
    *,
    agent_id: uuid.UUID | None,
    prompt_text: str | None,
    scope: str,
    workspace_id: uuid.UUID | None,
) -> _EvaluationInput:
    if agent_id is not None:
        agent = await db.get(Agent, agent_id)
        if agent is None or agent.workspace_id != workspace_id:
            raise PromptEvalInputError("Agent not found.")

        skills = await _load_live_skills(db, agent.id, agent.workspace_id)
        tools_rows = await _load_live_tools(db, agent.id, agent.workspace_id)
        subagent_ids = await _load_live_subagent_ids(db, agent.id)
        sub_agent_names: list[str] = []
        if subagent_ids:
            result = await db.execute(select(Agent.name).where(Agent.id.in_(subagent_ids)))
            sub_agent_names = [row[0] for row in result]

        instruction_text = (
            compose_instruction(agent.base_instruction, skills) if scope == "effective" else agent.base_instruction
        )

        model_config = agent.model_config_json or {}
        return _EvaluationInput(
            agent=agent,
            agent_name=agent.name,
            scope=scope,
            instruction_text=instruction_text,
            tools=[ToolInfo(name=t.name, description=t.description or "") for t in tools_rows],
            sub_agent_names=sub_agent_names,
            has_output_schema=bool(agent.output_schema),
            skills_have_few_shot=any(s.few_shot_examples for s in skills),
            scil_enabled=bool((model_config.get("scil") or {}).get("enabled")),
            durable_execution_enabled=bool((model_config.get("durable_execution") or {}).get("enabled")),
            planning_enabled=bool((model_config.get("planning") or {}).get("enabled")),
        )

    if not prompt_text or not prompt_text.strip():
        raise PromptEvalInputError("Provide either an agent_id or prompt_text.")

    # Raw pasted text has no skills/tools/sub-agents to compose against, so
    # it is always evaluated as "static" regardless of what scope was asked
    # for — there is nothing an "effective" composition would add.
    return _EvaluationInput(
        agent=None,
        agent_name=None,
        scope="static",
        instruction_text=prompt_text,
        tools=[],
        sub_agent_names=[],
        has_output_schema=False,
        skills_have_few_shot=False,
        scil_enabled=False,
        durable_execution_enabled=False,
        planning_enabled=False,
    )


def _weighted_overall_score(results: list[CriterionResult]) -> float:
    total_weight = 0
    weighted_sum = 0.0
    for r in results:
        if not r.applicable or r.score is None:
            continue
        criterion = CRITERIA_BY_ID.get(r.id)
        weight = criterion.weight if criterion else 1
        total_weight += weight
        weighted_sum += weight * r.score
    if total_weight == 0:
        return 0.0
    return round((weighted_sum / total_weight) / 5 * 100, 1)


def _result_to_dict(r: CriterionResult) -> dict:
    criterion = CRITERIA_BY_ID.get(r.id)
    return {
        "id": r.id,
        "label": criterion.label if criterion else r.id,
        "category": criterion.category if criterion else "structure",
        "method": criterion.method if criterion else "deterministic",
        "weight": criterion.weight if criterion else 1,
        "score": r.score,
        "max_score": 5,
        "applicable": r.applicable,
        "severity": r.severity,
        "rationale": r.rationale,
        "suggestion": r.suggestion,
    }


@dataclass
class EvaluationResult:
    id: uuid.UUID
    agent_id: uuid.UUID | None
    agent_name: str | None
    scope: str
    source_text: str
    overall_score: float
    criteria: list[dict]
    summary: str | None
    suggested_rewrite: str | None
    model_used: str | None
    judge_error: str | None
    created_at: datetime


async def evaluate_prompt(
    db: AsyncSession,
    *,
    agent_id: uuid.UUID | None,
    prompt_text: str | None,
    scope: str,
    model: str | None,
    workspace_id: uuid.UUID | None,
    actor: str,
) -> EvaluationResult:
    resolved = await _resolve_input(
        db, agent_id=agent_id, prompt_text=prompt_text, scope=scope, workspace_id=workspace_id
    )

    deterministic_results = run_deterministic_checks(
        text=resolved.instruction_text,
        tools=resolved.tools,
        sub_agent_names=resolved.sub_agent_names,
        has_output_schema=resolved.has_output_schema,
        skills_have_few_shot=resolved.skills_have_few_shot,
    )

    judged_results: list[CriterionResult] = []
    summary: str | None = None
    suggested_rewrite: str | None = None
    model_used: str | None = None
    judge_error: str | None = None

    agent_default_model = (resolved.agent.model_config_json or {}).get("model") if resolved.agent else None
    judge_model = model or agent_default_model or DEFAULT_JUDGE_MODEL

    try:
        judge_output = await run_judge(
            instruction_text=resolved.instruction_text,
            scope=resolved.scope,
            agent_name=resolved.agent_name,
            tools=[(t.name, t.description) for t in resolved.tools],
            sub_agent_names=resolved.sub_agent_names,
            has_output_schema=resolved.has_output_schema,
            scil_enabled=resolved.scil_enabled,
            durable_execution_enabled=resolved.durable_execution_enabled,
            planning_enabled=resolved.planning_enabled,
            model=judge_model,
        )
        judged_results = judge_output.criteria
        summary = judge_output.summary
        suggested_rewrite = judge_output.suggested_rewrite
        model_used = judge_output.model_used
    except JudgeError as exc:
        judge_error = str(exc)
        summary = (
            "The AI judge could not be reached, so this report only reflects the deterministic checks "
            f"below. ({judge_error})"
        )

    all_results = deterministic_results + judged_results
    overall_score = _weighted_overall_score(all_results)
    criteria_dicts = [_result_to_dict(r) for r in all_results]

    run = PromptEvalRun(
        workspace_id=workspace_id,
        agent_id=resolved.agent.id if resolved.agent else None,
        agent_name=resolved.agent_name,
        scope=resolved.scope,
        source_text=resolved.instruction_text,
        criteria_results=criteria_dicts,
        overall_score=overall_score,
        summary=summary,
        suggested_rewrite=suggested_rewrite,
        model_used=model_used,
        judge_error=judge_error,
        created_by=actor,
    )
    db.add(run)
    await db.commit()
    await db.refresh(run)

    return EvaluationResult(
        id=run.id,
        agent_id=run.agent_id,
        agent_name=run.agent_name,
        scope=run.scope,
        source_text=run.source_text,
        overall_score=float(run.overall_score),
        criteria=criteria_dicts,
        summary=run.summary,
        suggested_rewrite=run.suggested_rewrite,
        model_used=run.model_used,
        judge_error=run.judge_error,
        created_at=run.created_at,
    )
