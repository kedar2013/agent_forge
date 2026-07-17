"""Renames a published agent and republishes it under the new name so the
change actually takes effect in the built ADK agent tree — `agent_cache` is
keyed by (agent_id, version), and the ADK agent's own internal name is
baked in at build time by `agent_runtime/builder.py`'s `_safe_agent_name()`,
so a bare `UPDATE agents SET name = ...` alone wouldn't be picked up by any
cached build until the next publish anyway.

Every other agent's own published snapshot may still list this agent's old
name under its `sub_agents`/`tools` metadata — harmless, since
`agent_runtime/builder.py`'s `_build_from_snapshot` only uses the *id* from
that list to re-fetch the live, current row when recursing; the stored name
is cosmetic display metadata, never used to build the tree.

Usage (from backend/, so `app.*` imports resolve):
    python scripts/rename_agent.py <old_name> <new_name>
"""

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select  # noqa: E402

from app.agent_runtime.cache import agent_cache  # noqa: E402
from app.db import async_session_factory  # noqa: E402
from app.models.agents import Agent, AgentSkill, AgentSubagent, AgentTool, AgentVersion  # noqa: E402
from app.models.skills import Skill  # noqa: E402
from app.models.tools import Tool  # noqa: E402

SEED_MARKER = "rename-agent-script"


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("old_name")
    parser.add_argument("new_name")
    args = parser.parse_args()

    async with async_session_factory() as session:
        agent = await session.scalar(select(Agent).where(Agent.name == args.old_name))
        if agent is None:
            print(f"No agent named '{args.old_name}' found.")
            return
        clash = await session.scalar(select(Agent).where(Agent.name == args.new_name))
        if clash is not None:
            print(f"An agent named '{args.new_name}' already exists — pick a different name.")
            return

        agent.name = args.new_name

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
        sub_agent_ids = (
            await session.execute(select(AgentSubagent.child_agent_id).where(AgentSubagent.parent_agent_id == agent.id))
        ).scalars().all()
        sub_agents = [a for a in [await session.get(Agent, cid) for cid in sub_agent_ids] if a is not None]

        snapshot = {
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
        new_version = agent.current_version + 1
        session.add(AgentVersion(agent_id=agent.id, version=new_version, snapshot=snapshot, published_by=SEED_MARKER))
        agent.current_version = new_version
        agent.status = "published"
        agent_id = agent.id
        await session.commit()

    agent_cache.invalidate(agent_id)
    print(f"Renamed '{args.old_name}' -> '{args.new_name}' (agent {agent_id}), now version {new_version}.")


if __name__ == "__main__":
    asyncio.run(main())
