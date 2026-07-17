"""One-off fix: gemini-2.5-flash returns a 404 ("no longer available to new
users") on any freshly-created Gemini API key/project, even though it's
still nominally a stable model for older ones -- see app/config.py's
gemini_model default and every seed script's MODEL_CONFIG, all since moved
to gemini-3.5-flash. That code change only affects NEW agents seeded after
the fix; any agent already sitting in the database (e.g. seeded before this
fix, or built by hand via the Agent Builder UI) still has the old model
baked into its row and keeps 404ing until it's updated directly.

Updates every agent whose model_config_json.model == "gemini-2.5-flash" to
gemini-3.5-flash, in both the live draft AND (if published) the published
snapshot -- editing model_config_json alone would leave the published
snapshot (what /chat and /invoke actually run) frozen on the old model,
same trap documented in republish_stale_model_agents.py. Then walks and
re-bumps every published ancestor orchestrator so no cached tree keeps
serving a stale child.

Idempotent: re-running is a no-op once every agent's model is already
gemini-3.5-flash.

Usage (from the backend/ directory):
    python scripts/migrate_gemini_model.py
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

ACTOR = "gemini-model-migration"
OLD_MODEL = "gemini-2.5-flash"
NEW_MODEL = "gemini-3.5-flash"


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
        actor=ACTOR, diff={"version": agent.current_version, "reason": f"model {OLD_MODEL} -> {NEW_MODEL}"},
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
        agents = (await session.execute(select(Agent))).scalars().all()

        stale = [a for a in agents if (a.model_config_json or {}).get("model") == OLD_MODEL]

        if not stale:
            print(f"Nothing to do -- no agent has model == {OLD_MODEL!r}.")
            return

        changed_ids: set = set()
        for agent in stale:
            config = dict(agent.model_config_json or {})
            config["model"] = NEW_MODEL
            agent.model_config_json = config

            if agent.status == "published":
                old_version = agent.current_version
                await _republish(session, agent)
                print(f"Updated + republished '{agent.name}' v{old_version} -> v{agent.current_version}")
            else:
                await write_audit_log(
                    session, entity_type="agent", entity_id=agent.id, action="update",
                    actor=ACTOR, diff={"model_config.model": [OLD_MODEL, NEW_MODEL]},
                    workspace_id=DEFAULT_WORKSPACE_ID,
                )
                print(f"Updated '{agent.name}' (status={agent.status}, not published -- no republish needed)")
            changed_ids.add(agent.id)

        # Any published ancestor whose own model didn't change still has a
        # cached tree embedding one of the agents above -- bump it too so it
        # stops serving the stale child.
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
        print(f"Done -- {len(stale)} agent(s) migrated from {OLD_MODEL} to {NEW_MODEL}.")


if __name__ == "__main__":
    asyncio.run(main())