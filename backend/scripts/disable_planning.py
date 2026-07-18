"""Turns `model_config.planning.enabled` back OFF for every agent
`scripts/consolidate_orchestrators.py` turned it on for.

Found via live testing, not theorized: `PlanReActPlanner` is purely
instructional (it asks the model to format its own response with
/*PLANNING*/.../*FINAL_ANSWER*/ tags — unlike `BuiltInPlanner`, which wraps
a model's native thinking-config support). With `gemini-3.5-flash`,
compliance is unreliable enough to be a real regression, not just a
cosmetic one: a specialist's ENTIRE response can come back tagged as
planning/reasoning with no `/*FINAL_ANSWER*/` segment at all, which
`playground_api/router.py`'s (correct, ADK-standard) `part.thought`
filtering then hides completely — the user gets "Sorry, I couldn't come up
with an answer" even though the orchestrator routed correctly and the
specialist DID have an answer, it just never got tagged as the final one.

The planner code/wiring itself (`app/agent_runtime/planning_config.py`,
`agent_runtime/builder.py`'s `planner=PlanReActPlanner()` wiring, the
thought-filtering in `playground_api/router.py`) stays — this only flips
the opt-in flag back to its safe default (off), same as SCIL/durable
execution being "off by default" until proven safe for a given agent. Can
be re-enabled per-agent later once compliance is verified good for a
specific model/agent pairing.

Usage (from backend/, so `app.*` imports resolve):
    python scripts/disable_planning.py
"""

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

SEED_MARKER = "disable-planning"


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
        all_agents = (await session.execute(select(Agent))).scalars().all()
        rows = [a for a in all_agents if (a.model_config_json or {}).get("planning", {}).get("enabled") is True]
        print(f"Disabling planning on {len(rows)} agents...")
        for agent in rows:
            agent.model_config_json = {**(agent.model_config_json or {}), "planning": {"enabled": False}}
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
