"""Collapses every orchestrator-shaped agent in the platform into ONE single
root orchestrator, and turns on Planner/ReAct (`google.adk.planners.
PlanReActPlanner`, see `app/agent_runtime/planning_config.py`) for it and
every real leaf specialist.

Reuses `market_intelligence_orchestrator`'s existing row/id (renamed, same
mechanics as `scripts/rename_agent.py` — the id stays stable, so nothing
that references it by id breaks) rather than creating a fresh agent, and
reuses the SAME generic router-prompt builder every router orchestrator in
this repo already uses (`app/agent_runtime/orchestration_patterns.py`) — no
new prompt-building code.

What happens:
  1. `market_intelligence_orchestrator` -> `agent_forge_orchestrator`
     (renamed in place), description + base_instruction rewritten to route
     across every real domain (finance/market, credit/revenue/sales
     analytics, studybuddy tutoring).
  2. Every real specialist not already attached gets a fresh `AgentSubagent`
     row: the 7 studybuddy specialists, credit_facility_analyst,
     revenue_returns_analyst, sales_analytics_analyst,
     revenue_query_orchestrator (kept, demoted to a leaf — its own internal
     tool/child wiring, an older query-decomposition/scratchpad pattern, is
     left completely untouched), fund_research_agent,
     self_healing_revenue_analyst.
  3. Every attached specialist that doesn't already carry the router
     peer-clause gets one appended (`orchestration_patterns.build_peer_clause()`)
     so it can bounce back to the new root for anything outside its domain
     — `credit_facility_analyst`/`revenue_returns_analyst` already have one
     and are skipped.
  4. `nl2sql_orchestrator`, `studybuddy_orchestrator`, and the live
     `'india_fund_orchestrator '` (trailing space — a pre-existing published
     duplicate of the already-archived `'india_fund_orchestrator'`) are
     archived: their own `AgentSubagent` rows detached (dead weight on an
     agent nothing can invoke anymore — `require...status == "published"`
     already blocks archived agents from being built at all) and
     `status = 'archived'`.
  5. `model_config.planning.enabled = true` on the new root and every
     attached specialist EXCEPT `flashcard_agent`/`quiz_agent` (their
     `output_schema` requires strict JSON, which the ReAct planner's
     free-text plan/action format cannot coexist with).
  6. Every touched agent is republished (fresh `AgentVersion` snapshot,
     `agent_cache.invalidate`) — same `_republish` pattern as
     `scripts/seed_reporting_specialist.py`.

Usage (from backend/, so `app.*` imports resolve):
    python scripts/consolidate_orchestrators.py
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import delete, select  # noqa: E402

from app.agent_runtime.cache import agent_cache  # noqa: E402
from app.agent_runtime.orchestration_patterns import build_peer_clause, build_router_instruction  # noqa: E402
from app.db import async_session_factory  # noqa: E402
from app.logging_hooks import write_audit_log  # noqa: E402
from app.models.agents import Agent, AgentSkill, AgentSubagent, AgentTool, AgentVersion  # noqa: E402
from app.models.skills import Skill  # noqa: E402
from app.models.tools import Tool  # noqa: E402
from app.models.workspaces import DEFAULT_WORKSPACE_ID  # noqa: E402

SEED_MARKER = "consolidate-orchestrators"

OLD_ROOT_NAME = "market_intelligence_orchestrator"
NEW_ROOT_NAME = "agent_forge_orchestrator"
NEW_ROOT_DESCRIPTION = (
    "The single entry point for Agent Forge — routes across every onboarded domain "
    "(market intelligence, credit risk, revenue/sales analytics, StudyBuddy tutoring) "
    "to the right specialist(s), never answering a domain question itself."
)

# name -> fallback description, used when the agent's own `description`
# column is empty/unhelpful (confirmed live: sales_analytics_analyst's is
# blank, 'mutual fund analyser''s is a placeholder).
_DESCRIPTION_FALLBACKS = {
    "sales_analytics_analyst": (
        "Answers questions about sales orders, regions, sales reps, and product "
        "categories — the generic data_query_tool worked example onboarded via "
        "/onboarding/new-domain."
    ),
    "mutual fund analyser": "Analyzes and compares Indian mutual fund schemes.",
}

# Ordered for a readable directory: market/finance, credit/revenue/sales,
# reporting, then studybuddy tutoring. Already-attached agents are included
# too (they need the peer clause added, same as the new ones).
ALL_SPECIALISTS = [
    "stock_market_analyst",
    "crypto_analyst",
    "forex_metals_analyst",
    "company_research_copilot",
    "fund_analyst_agent",
    "fund_research_agent",
    "credit_facility_analyst",
    "revenue_returns_analyst",
    "sales_analytics_analyst",
    "revenue_query_orchestrator",
    "self_healing_revenue_analyst",
    "reporting_specialist",
    "summarizer_agent",
    "example_agent",
    "qa_agent",
    "flashcard_agent",
    "quiz_agent",
    "translator_agent",
    "simplifier_agent",
    # Previously left as standalone top-level bots (not "orchestrator"-shaped,
    # so out of scope for the first consolidation pass) — folded in too, so
    # /chat/orchestrators has exactly one entry, not eight.
    "weather_agent",
    "sql_insights_agent",
    "mutual fund analyser",
    "slide_reporting_agent",
    "reliability_demo_agent",
]

# output_schema (strict JSON) can't coexist with PlanReActPlanner's
# free-text /*PLANNING*/.../*ACTION*/... format.
PLANNING_EXCLUDED = {
    "flashcard_agent",
    "quiz_agent",
    # A platform-capability/verification demo, not a business specialist —
    # deliberately left out of the planning rollout, same reasoning as before,
    # just now also structurally folded under the single root.
    "reliability_demo_agent",
}

# Retired: their routing function is now fully absorbed by the new root.
# 'india_fund_orchestrator ' (trailing space) is a pre-existing PUBLISHED
# duplicate of the already-archived 'india_fund_orchestrator' — same
# children (fund_analyst_agent, fund_research_agent), both now reachable
# directly from the new root.
ORCHESTRATORS_TO_ARCHIVE = ["nl2sql_orchestrator", "studybuddy_orchestrator", "india_fund_orchestrator "]


async def _get_agent(session, name: str) -> Agent | None:
    return await session.scalar(select(Agent).where(Agent.name == name))


async def _full_snapshot(session, agent: Agent) -> dict:
    tools = (
        await session.execute(
            select(Tool).join(AgentTool, AgentTool.tool_id == Tool.id).where(AgentTool.agent_id == agent.id)
        )
    ).scalars().all()
    skill_rows = (
        await session.execute(
            select(Skill, AgentSkill.attach_order)
            .join(AgentSkill, AgentSkill.skill_id == Skill.id)
            .where(AgentSkill.agent_id == agent.id)
            .order_by(AgentSkill.attach_order)
        )
    ).all()
    sub_ids = (
        await session.execute(select(AgentSubagent.child_agent_id).where(AgentSubagent.parent_agent_id == agent.id))
    ).scalars().all()
    sub_agents = [a for a in [await session.get(Agent, cid) for cid in sub_ids] if a is not None]
    return {
        "name": agent.name,
        "description": agent.description,
        "base_instruction": agent.base_instruction,
        "model_config": agent.model_config_json,
        "output_schema": agent.output_schema,
        "output_key": agent.output_key,
        "tools": [{"id": str(t.id), "name": t.name} for t in tools],
        "skills": [{"id": str(s.id), "name": s.name, "attach_order": order} for s, order in skill_rows],
        "sub_agents": [{"id": str(a.id), "name": a.name} for a in sub_agents],
    }


async def _republish(session, agent: Agent) -> None:
    snapshot = await _full_snapshot(session, agent)
    new_version = agent.current_version + 1
    session.add(AgentVersion(agent_id=agent.id, version=new_version, snapshot=snapshot, published_by=SEED_MARKER))
    agent.current_version = new_version
    agent.status = "published"
    await session.flush()
    agent_cache.invalidate(agent.id)


async def main() -> None:
    async with async_session_factory() as session:
        root = await _get_agent(session, OLD_ROOT_NAME)
        if root is None:
            root = await _get_agent(session, NEW_ROOT_NAME)
        if root is None:
            print(f"Neither '{OLD_ROOT_NAME}' nor '{NEW_ROOT_NAME}' found — nothing to consolidate.")
            return

        root.name = NEW_ROOT_NAME
        root.description = NEW_ROOT_DESCRIPTION

        specialists: dict[str, Agent] = {}
        directory: dict[str, str] = {}
        missing = []
        for name in ALL_SPECIALISTS:
            agent = await _get_agent(session, name)
            if agent is None:
                missing.append(name)
                continue
            specialists[name] = agent
            directory[name] = agent.description or _DESCRIPTION_FALLBACKS.get(name, name)
        if missing:
            print(f"WARNING: specialists not found, skipped: {missing}")

        root.base_instruction = build_router_instruction("Agent Forge", directory)

        existing_children = set(
            (
                await session.execute(
                    select(Agent.name)
                    .join(AgentSubagent, AgentSubagent.child_agent_id == Agent.id)
                    .where(AgentSubagent.parent_agent_id == root.id)
                )
            ).scalars().all()
        )
        for name, agent in specialists.items():
            if name not in existing_children:
                session.add(AgentSubagent(parent_agent_id=root.id, child_agent_id=agent.id))
            if "router-peer-clause" not in (agent.base_instruction or ""):
                agent.base_instruction = (agent.base_instruction or "") + build_peer_clause()
            if name not in PLANNING_EXCLUDED:
                agent.model_config_json = {**(agent.model_config_json or {}), "planning": {"enabled": True}}
        await session.flush()

        root.model_config_json = {**(root.model_config_json or {}), "planning": {"enabled": True}}

        for name in ORCHESTRATORS_TO_ARCHIVE:
            old = await _get_agent(session, name)
            if old is None:
                continue
            await session.execute(delete(AgentSubagent).where(AgentSubagent.parent_agent_id == old.id))
            old.status = "archived"
            await write_audit_log(
                session, entity_type="agent", entity_id=old.id, action="archive", actor=SEED_MARKER,
                diff={"reason": "consolidated into agent_forge_orchestrator"}, workspace_id=DEFAULT_WORKSPACE_ID,
            )

        await _republish(session, root)
        for agent in specialists.values():
            await _republish(session, agent)

        await write_audit_log(
            session, entity_type="agent", entity_id=root.id, action="publish", actor=SEED_MARKER,
            diff={"renamed_from": OLD_ROOT_NAME, "version": root.current_version}, workspace_id=DEFAULT_WORKSPACE_ID,
        )
        await session.commit()
        print(f"'{OLD_ROOT_NAME}' -> '{NEW_ROOT_NAME}' (now version {root.current_version}), "
              f"{len(specialists)} specialists attached/updated, "
              f"{len(ORCHESTRATORS_TO_ARCHIVE)} old orchestrators archived.")


if __name__ == "__main__":
    asyncio.run(main())
