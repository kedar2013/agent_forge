"""One-off fix: the user updated every agent's model from gemini-2.5-flash
(deprecated, 404s) to gemini-2.5-flash via the Agent Builder UI, but editing
an agent only touches its LIVE draft row -- the PUBLISHED snapshot (what
/chat and /invoke actually run, and what's cached in AgentCache) stays
frozen at whatever it was last published with. Republishes every agent
whose published snapshot's model doesn't match its current live draft, then
walks and re-bumps every PUBLISHED ancestor orchestrator so no cached tree
keeps serving a stale child (same pattern as scripts/audit_fix_agents.py).

Usage (from the backend/ directory):
    python scripts/republish_stale_model_agents.py
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select  # noqa: E402

from app.db import async_session_factory  # noqa: E402
from app.logging_hooks import write_audit_log  # noqa: E402
from app.models.agents import Agent, AgentSubagent, AgentTool, AgentVersion  # noqa: E402
from app.models.tools import Tool  # noqa: E402
from app.models.workspaces import DEFAULT_WORKSPACE_ID  # noqa: E402

ACTOR = "model-migration-fix"


def _publish_snapshot(agent: Agent, tools: list[Tool], sub_agents: list[Agent]) -> dict:
    return {
        "name": agent.name,
        "description": agent.description,
        "base_instruction": agent.base_instruction,
        "model_config": agent.model_config_json,
        "output_schema": agent.output_schema,
        "output_key": agent.output_key,
        "tools": [{"id": str(t.id), "name": t.name} for t in tools],
        "skills": [],
        "sub_agents": [{"id": str(a.id), "name": a.name} for a in sub_agents],
    }


async def _republish(session, agent: Agent) -> None:
    tool_rows = (
        (await session.execute(
            select(Tool).join(AgentTool, AgentTool.tool_id == Tool.id).where(AgentTool.agent_id == agent.id)
        )).scalars().all()
    )
    sub_agent_rows = (
        (await session.execute(
            select(Agent).join(AgentSubagent, AgentSubagent.child_agent_id == Agent.id)
            .where(AgentSubagent.parent_agent_id == agent.id)
        )).scalars().all()
    )
    agent.current_version += 1
    snapshot = _publish_snapshot(agent, tool_rows, sub_agent_rows)
    session.add(
        AgentVersion(agent_id=agent.id, version=agent.current_version, snapshot=snapshot, published_by=ACTOR)
    )
    agent.status = "published"
    await write_audit_log(
        session, entity_type="agent", entity_id=agent.id, action="publish",
        actor=ACTOR, diff={"version": agent.current_version, "reason": "model migration republish"},
        workspace_id=DEFAULT_WORKSPACE_ID,
    )


async def _find_ancestor_ids(session, agent_id) -> set:
    ancestors: set = set()
    frontier = [agent_id]
    while frontier:
        result = await session.execute(
            select(AgentSubagent.parent_agent_id).where(AgentSubagent.child_agent_id.in_(frontier))
        )
        next_frontier = []
        for (node,) in result:
            if node not in ancestors:
                ancestors.add(node)
                next_frontier.append(node)
        frontier = next_frontier
    return ancestors


async def main() -> None:
    async with async_session_factory() as session:
        agents = (await session.execute(select(Agent).where(Agent.status == "published"))).scalars().all()

        stale: list[Agent] = []
        for agent in agents:
            version_row = (
                await session.execute(
                    select(AgentVersion).where(
                        AgentVersion.agent_id == agent.id, AgentVersion.version == agent.current_version
                    )
                )
            ).scalar_one_or_none()
            if version_row is None:
                continue
            snap_model = (version_row.snapshot or {}).get("model_config", {}).get("model")
            live_model = (agent.model_config_json or {}).get("model")
            if snap_model != live_model:
                stale.append(agent)

        if not stale:
            print("Nothing to do -- every published snapshot already matches its live draft's model.")
            return

        changed_ids: set = {a.id for a in stale}
        for agent in stale:
            old_version = agent.current_version
            await _republish(session, agent)
            print(f"Republished '{agent.name}' v{old_version} -> v{agent.current_version} "
                  f"(model now '{(agent.model_config_json or {}).get('model')}')")

        # Any ancestor not already republished directly (e.g. an orchestrator
        # whose OWN model didn't change but whose cached tree embeds one of
        # the agents above) still needs its cache entry invalidated.
        ancestor_ids: set = set()
        for agent_id in changed_ids:
            ancestor_ids |= await _find_ancestor_ids(session, agent_id)
        ancestor_ids -= changed_ids

        for ancestor_id in ancestor_ids:
            ancestor = await session.get(Agent, ancestor_id)
            if ancestor is None or ancestor.status != "published":
                continue
            await _republish(session, ancestor)
            print(f"  bumped ancestor '{ancestor.name}' (now version {ancestor.current_version}) "
                  f"to invalidate its cache")

        await session.commit()
        print(f"Done -- {len(stale)} agent(s) republished.")


if __name__ == "__main__":
    asyncio.run(main())
