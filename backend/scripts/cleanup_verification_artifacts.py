"""One-off cleanup of test-suite/verification debris — the same class of
cleanup the design doc says a prior session already did once ("154 test
agents / 12 tools / 24 skills / 21 users were found and removed in a
cleanup pass"). The test suite re-accumulates this every run by design
(`tests/conftest.py`'s `unique_name()` fixture creates real rows in the
real dev DB and never deletes them — see the design doc's Testing
Philosophy section) — this script is the same identification method,
run again.

Identification is deliberately NOT name-pattern matching alone (fragile,
easy to false-positive on a real hand-built agent that happens to have a
short name) — it's:
  - `created_by IS NULL` AND NOT in the explicit `_REAL_AGENT_NAMES` allowlist
    below (every genuinely real agent this repo has that happens to lack a
    seed-script creator marker, confirmed live against the DB before writing
    this script), OR
  - `created_by LIKE 'dev_%@example.com'` (the pytest collaborator-user
    fixture pattern, `tests/conftest.py`'s `unique_name()`).
Tools/skills use REFERENTIAL orphan-detection, not name matching: a
`created_by IS NULL` tool/skill is only deleted if, after the agent pass,
nothing in `agent_tools`/`agent_skills` still references it — this is what
protects the real-but-undocumented tools this repo also has (`query_orders`,
`get_company_fundamentals`, `weather_current_mcp`, ...), which stay
referenced by a kept agent and therefore survive regardless of their own
`created_by` being NULL too.

FK-safe deletion order (see design doc's Testing Philosophy section):
`invocation_log`/`tool_call_log`/every `scil_*` table reference an agent or
tool with NO cascade — deleted first. `agent_tools`/`agent_skills`/
`agent_subagents`/`agent_versions` DO cascade on their parent agent's
deletion.

Usage (from backend/, so `app.*` imports resolve):
    python scripts/cleanup_verification_artifacts.py              # dry run (default)
    python scripts/cleanup_verification_artifacts.py --confirm     # actually delete
"""

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import delete, or_, select  # noqa: E402

from app.db import async_session_factory  # noqa: E402
from app.models.agents import (  # noqa: E402
    Agent,
    AgentCollaborator,
    AgentPublishRequest,
    AgentSkill,
    AgentSubagent,
    AgentTool,
    AgentVersion,
)
from app.models.logs import AgentEventLog, ConfigAuditLog, InvocationLog, ToolCallLog  # noqa: E402
from app.models.scil import (  # noqa: E402
    ScilCorrectionMemory,
    ScilEntityMemory,
    ScilEvalCase,
    ScilEvalRun,
    ScilGroundednessSample,
    ScilSemanticCache,
)
from app.models.skills import SkillCollaborator, Skill  # noqa: E402
from app.models.tools import Tool  # noqa: E402
from app.models.users import User  # noqa: E402

# Every real agent that happens to lack a seed-script `created_by` marker —
# confirmed live against the DB before writing this script (hand-built via
# the admin UI, no seed script exists for them, see README's Known
# Limitations section for fund_analyst_agent/fund_research_agent/
# company_research_copilot specifically).
_REAL_AGENT_NAMES = {
    "sales_analytics_analyst",
    "fund_analyst_agent",
    "fund_research_agent",
    "company_research_copilot",
    "weather_agent",
    "sql_insights_agent",
    "mutual fund analyser",
    "india_fund_orchestrator",
}

_DEV_EMAIL_PATTERN = "dev_%@example.com"


async def _find_doomed_agents(session) -> list[Agent]:
    rows = (
        await session.execute(
            select(Agent).where(
                or_(
                    Agent.created_by.is_(None),
                    Agent.created_by.like(_DEV_EMAIL_PATTERN),
                )
            )
        )
    ).scalars().all()
    return [a for a in rows if a.name not in _REAL_AGENT_NAMES]


async def _delete_agent(session, agent: Agent) -> None:
    invocation_ids = (
        await session.execute(select(InvocationLog.id).where(InvocationLog.agent_id == agent.id))
    ).scalars().all()
    if invocation_ids:
        await session.execute(delete(ToolCallLog).where(ToolCallLog.invocation_id.in_(invocation_ids)))
        await session.execute(delete(AgentEventLog).where(AgentEventLog.invocation_id.in_(invocation_ids)))
        await session.execute(delete(InvocationLog).where(InvocationLog.id.in_(invocation_ids)))
    await session.execute(delete(ScilSemanticCache).where(ScilSemanticCache.agent_id == agent.id))
    await session.execute(delete(ScilCorrectionMemory).where(ScilCorrectionMemory.agent_id == agent.id))
    await session.execute(delete(ScilEntityMemory).where(ScilEntityMemory.agent_id == agent.id))
    eval_case_ids = (
        await session.execute(select(ScilEvalCase.id).where(ScilEvalCase.agent_id == agent.id))
    ).scalars().all()
    if eval_case_ids:
        await session.execute(delete(ScilEvalRun).where(ScilEvalRun.case_id.in_(eval_case_ids)))
    await session.execute(delete(ScilEvalCase).where(ScilEvalCase.agent_id == agent.id))
    await session.execute(delete(ScilGroundednessSample).where(ScilGroundednessSample.agent_id == agent.id))
    await session.execute(delete(AgentPublishRequest).where(AgentPublishRequest.agent_id == agent.id))
    await session.execute(delete(ConfigAuditLog).where(ConfigAuditLog.entity_id == agent.id))
    # agent_tools/agent_skills/agent_subagents (both directions)/agent_versions/
    # agent_collaborators all cascade on the agent row's own delete.
    await session.delete(agent)


async def _find_orphaned_tools(session) -> list[Tool]:
    rows = (
        await session.execute(
            select(Tool).where(or_(Tool.created_by.is_(None), Tool.created_by.like(_DEV_EMAIL_PATTERN)))
        )
    ).scalars().all()
    orphaned = []
    for tool in rows:
        still_used = await session.scalar(select(AgentTool.tool_id).where(AgentTool.tool_id == tool.id).limit(1))
        if still_used is None:
            orphaned.append(tool)
    return orphaned


async def _find_orphaned_skills(session) -> list[Skill]:
    rows = (
        await session.execute(
            select(Skill).where(or_(Skill.created_by.is_(None), Skill.created_by.like(_DEV_EMAIL_PATTERN)))
        )
    ).scalars().all()
    orphaned = []
    for skill in rows:
        still_used = await session.scalar(select(AgentSkill.skill_id).where(AgentSkill.skill_id == skill.id).limit(1))
        if still_used is None:
            orphaned.append(skill)
    return orphaned


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--confirm", action="store_true", help="Actually delete (default is dry-run/print-only).")
    args = parser.parse_args()

    async with async_session_factory() as session:
        doomed_agents = await _find_doomed_agents(session)
        print(f"Agents to delete: {len(doomed_agents)}")
        for a in doomed_agents:
            print(f"  - {a.name!r} (status={a.status}, created_by={a.created_by})")

        if args.confirm:
            for a in doomed_agents:
                await _delete_agent(session, a)
            await session.flush()

        orphaned_tools = await _find_orphaned_tools(session)
        print(f"\nTools to delete (orphaned after agent pass): {len(orphaned_tools)}")
        for t in orphaned_tools:
            print(f"  - {t.name!r} ({t.tool_type})")
        if args.confirm:
            for t in orphaned_tools:
                await session.execute(delete(ToolCallLog).where(ToolCallLog.tool_id == t.id))
                await session.delete(t)

        orphaned_skills = await _find_orphaned_skills(session)
        print(f"\nSkills to delete (orphaned after agent pass): {len(orphaned_skills)}")
        for s in orphaned_skills:
            print(f"  - {s.name!r}")
        if args.confirm:
            for s in orphaned_skills:
                await session.delete(s)

        dev_users = (await session.execute(select(User).where(User.email.like(_DEV_EMAIL_PATTERN)))).scalars().all()
        print(f"\nUsers to delete: {len(dev_users)}")
        for u in dev_users:
            print(f"  - {u.email!r}")
        if args.confirm:
            for u in dev_users:
                await session.execute(delete(AgentCollaborator).where(AgentCollaborator.user_email == u.email))
                await session.execute(delete(SkillCollaborator).where(SkillCollaborator.user_email == u.email))
                await session.delete(u)

        if args.confirm:
            await session.commit()
            print("\nDeleted.")
        else:
            print("\nDry run only — pass --confirm to actually delete.")


if __name__ == "__main__":
    asyncio.run(main())
