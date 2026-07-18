"""Re-applies `orchestration_patterns.build_peer_clause()`'s current wording
to every sub-agent of `agent_forge_orchestrator` — strips whatever old
clause is already there (via `strip_peer_clause`, matched by marker comment,
not exact wording — this is exactly what that marker is for) and appends
the current one, then republishes.

Needed because `consolidate_orchestrators.py`'s own peer-clause step only
appends when the marker is ABSENT — a no-op once every specialist already
has one, so a later wording change (e.g. adding explicit guidance for
meta-questions like "what are your capabilities") needs this instead of a
re-run of that script.

Usage (from backend/, so `app.*` imports resolve):
    python scripts/refresh_peer_clause.py
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select  # noqa: E402

from app.agent_runtime.cache import agent_cache  # noqa: E402
from app.agent_runtime.orchestration_patterns import build_peer_clause, strip_peer_clause  # noqa: E402
from app.db import async_session_factory  # noqa: E402
from app.models.agents import Agent, AgentSkill, AgentSubagent, AgentTool, AgentVersion  # noqa: E402
from app.models.skills import Skill  # noqa: E402
from app.models.tools import Tool  # noqa: E402

SEED_MARKER = "refresh-peer-clause"
ROOT_NAME = "agent_forge_orchestrator"


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


async def main() -> None:
    async with async_session_factory() as session:
        root = await session.scalar(select(Agent).where(Agent.name == ROOT_NAME))
        if root is None:
            print(f"'{ROOT_NAME}' not found.")
            return
        child_ids = (
            await session.execute(select(AgentSubagent.child_agent_id).where(AgentSubagent.parent_agent_id == root.id))
        ).scalars().all()
        print(f"Refreshing peer clause on {len(child_ids)} specialists...")
        for cid in child_ids:
            agent = await session.get(Agent, cid)
            if agent is None:
                continue
            agent.base_instruction = strip_peer_clause(agent.base_instruction or "") + build_peer_clause()
            snapshot = await _full_snapshot(session, agent)
            new_version = agent.current_version + 1
            session.add(
                AgentVersion(agent_id=agent.id, version=new_version, snapshot=snapshot, published_by=SEED_MARKER)
            )
            agent.current_version = new_version
            await session.flush()
            agent_cache.invalidate(agent.id)
            print(f"  {agent.name} -> v{new_version}")
        await session.commit()
    print("Done.")


if __name__ == "__main__":
    asyncio.run(main())
