"""Seeds `nl2sql_orchestrator` — the single entry point for every
structured-data (NL2SQL) domain on this platform, and attaches the
CURRENTLY onboarded domain specialists (`credit_facility_analyst`,
`revenue_returns_analyst`) to it as sub-agents.

This is a pure router built entirely on
`app.agent_runtime.orchestration_patterns` — the generic, reusable
"transfer to the right specialist(s), let each one bounce back to you for
anything outside its own domain, combine the partial answers into one
final reply" pattern any router orchestrator wires up the same way,
whether a given question needs one specialist, two, or all N of them. No
new ADK/transfer mechanism is needed for specialists to invoke EACH OTHER:
Google ADK's `transfer_to_agent` already allows any agent to transfer to
its own children, its parent, AND its parent's other children (siblings)
by default (`disallow_transfer_to_peers` defaults False, and
`app/agent_runtime/builder.py` never sets it) — orchestration_patterns
just adds the routing/collaboration instructions on top of that built-in
mechanism, plus builder.py's shared before_tool_callback caps how many
hand-offs can happen in one turn as a backstop against a model that
ignores the "never transfer to the same specialist twice" rule.

Designed to scale past two specialists: `SPECIALISTS` below is the single
source of truth for both the orchestrator's routing directory and which
agents get attached — onboarding a third domain (see
`backend/app/domains/<name>/` for the pattern any domain already follows)
means adding one entry here and re-running this script, nothing else. The
underlying instruction (orchestration_patterns.build_router_instruction)
was written for exactly this: it never hardcodes "first specialist,
second specialist" — it describes a loop that covers however many domains
a given question actually touches.

Idempotent: `--reset` detaches the specialists, strips the appended
collaboration clauses back out of their instructions, republishes them,
and deletes `nl2sql_orchestrator` itself (mirrors
`seed_reporting_specialist.py`'s reset pattern).

Usage (from backend/, so `app.*` imports resolve):
    python scripts/seed_nl2sql_orchestrator.py [--reset]
"""

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import delete, select  # noqa: E402

from app.agent_runtime.cache import agent_cache  # noqa: E402
from app.agent_runtime.orchestration_patterns import (  # noqa: E402
    build_peer_clause,
    build_router_instruction,
    strip_peer_clause,
)
from app.db import async_session_factory  # noqa: E402
from app.logging_hooks import write_audit_log  # noqa: E402
from app.models.agents import Agent, AgentSkill, AgentSubagent, AgentTool, AgentVersion  # noqa: E402
from app.models.logs import ConfigAuditLog, InvocationLog, ToolCallLog  # noqa: E402
from app.models.skills import Skill  # noqa: E402
from app.models.tools import Tool  # noqa: E402
from app.models.workspaces import DEFAULT_WORKSPACE_ID  # noqa: E402

SEED_MARKER = "nl2sql-orchestrator-import"
MODEL_CONFIG = {"model": "gemini-3.5-flash", "temperature": 0.1}

AGENT_NAME = "nl2sql_orchestrator"
AGENT_DESCRIPTION = (
    "Single entry point for every structured-data (NL2SQL) domain on this platform — "
    "routes to the right domain specialist and combines their answers for cross-domain "
    "questions. Currently onboarded: credit facility, revenue & returns."
)

# Single source of truth: one entry per onboarded domain specialist, mapping
# its exact published name to a one-line description of its domain. Adding
# a new domain later = add one entry here (+ re-run this script) — nothing
# else about the orchestrator's instruction needs hand-editing; see
# build_router_instruction's docstring for why that's true regardless of
# how many entries end up here.
SPECIALISTS = {
    "credit_facility_analyst": (
        "companies' credit facility usage — limits, utilization, outstanding balances, "
        "overdue amounts. Access is scoped by the logged-in user's persona "
        "(GCM/GSG/Non-GSG/CCB); the specialist handles that itself."
    ),
    "revenue_returns_analyst": (
        "product revenue, returns, and refunds — gross/net revenue, return rates, "
        "units sold/returned, by business unit/category/product/region."
    ),
}


def _orchestrator_instruction() -> str:
    return build_router_instruction("structured-data (NL2SQL)", SPECIALISTS)


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


async def reset(session) -> None:
    print("Resetting previously-seeded nl2sql_orchestrator...")
    orchestrator = await _get_agent(session, AGENT_NAME)
    for specialist_name in SPECIALISTS:
        specialist = await _get_agent(session, specialist_name)
        if specialist is None:
            continue
        stripped = strip_peer_clause(specialist.base_instruction)
        if stripped != specialist.base_instruction:
            specialist.base_instruction = stripped
            await _republish(session, specialist)
            print(f"  Removed peer-collaboration clause from '{specialist_name}'.")
        if orchestrator is not None:
            await session.execute(
                delete(AgentSubagent).where(
                    AgentSubagent.parent_agent_id == orchestrator.id, AgentSubagent.child_agent_id == specialist.id
                )
            )
    if orchestrator is not None:
        invocation_ids = (
            (await session.execute(select(InvocationLog.id).where(InvocationLog.agent_id == orchestrator.id)))
            .scalars().all()
        )
        if invocation_ids:
            await session.execute(delete(ToolCallLog).where(ToolCallLog.invocation_id.in_(invocation_ids)))
            await session.execute(delete(InvocationLog).where(InvocationLog.id.in_(invocation_ids)))
        await session.execute(delete(AgentTool).where(AgentTool.agent_id == orchestrator.id))
        await session.execute(delete(AgentVersion).where(AgentVersion.agent_id == orchestrator.id))
        await session.execute(delete(Agent).where(Agent.id == orchestrator.id))
    await session.execute(delete(ConfigAuditLog).where(ConfigAuditLog.actor == SEED_MARKER))
    await session.commit()


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reset", action="store_true")
    args = parser.parse_args()

    async with async_session_factory() as session:
        if args.reset:
            await reset(session)

        existing = await _get_agent(session, AGENT_NAME)
        if existing is not None:
            print(f"'{AGENT_NAME}' already seeded. Use --reset to reseed.")
            return

        missing = [name for name in SPECIALISTS if await _get_agent(session, name) is None]
        if missing:
            print(f"Expected these specialists to already be published, but found none: {missing}")
            print("Run their owning domain's seed_agent.py first.")
            return

        orchestrator = Agent(
            name=AGENT_NAME,
            workspace_id=DEFAULT_WORKSPACE_ID,
            description=AGENT_DESCRIPTION,
            base_instruction=_orchestrator_instruction(),
            model_config_json=MODEL_CONFIG,
            created_by=SEED_MARKER,
        )
        session.add(orchestrator)
        await session.flush()

        # Attach every specialist BEFORE the orchestrator's own first publish —
        # a snapshot freezes `sub_agents` at publish time (see
        # `_full_snapshot`), so publishing before attaching would ship an
        # orchestrator with zero transfer targets in its own published
        # version (only the always-fresh Playground/draft build would show
        # the attachments; `/chat`, which builds from the published snapshot,
        # would silently have nothing to transfer to).
        for specialist_name in SPECIALISTS:
            specialist = await _get_agent(session, specialist_name)
            session.add(AgentSubagent(parent_agent_id=orchestrator.id, child_agent_id=specialist.id))

            # No peer clause needed with a single specialist — nothing to
            # hand off to yet.
            clause = build_peer_clause() if len(SPECIALISTS) >= 2 else ""
            stripped = strip_peer_clause(specialist.base_instruction)
            if clause and stripped + clause != specialist.base_instruction:
                # Strip-then-append (rather than a not-in check) so a wording
                # change to build_peer_clause() replaces the old clause
                # instead of stacking a second one alongside it — see
                # strip_peer_clause.
                specialist.base_instruction = stripped + clause
                await _republish(session, specialist)
                print(f"  Added/updated peer-collaboration clause on '{specialist_name}' (now version {specialist.current_version}).")

            await session.flush()
            print(f"  Attached '{specialist_name}' as a sub-agent of '{AGENT_NAME}'.")

        await _republish(session, orchestrator)
        await write_audit_log(
            session, entity_type="agent", entity_id=orchestrator.id, action="publish", actor=SEED_MARKER,
            diff={"version": orchestrator.current_version}, workspace_id=DEFAULT_WORKSPACE_ID,
        )
        print(f"Created and published '{AGENT_NAME}' (version {orchestrator.current_version}), with {len(SPECIALISTS)} sub-agents.")

        await session.commit()


if __name__ == "__main__":
    asyncio.run(main())
