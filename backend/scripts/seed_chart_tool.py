"""Registers the shared chart-generation tool
(mcp_servers/chart_server.py::generate_chart_tool) and attaches it to the
five existing market_intelligence specialists that currently answer
numerical questions in plain text only: stock_market_analyst,
crypto_analyst, forex_metals_analyst, fund_analyst_agent, and
company_research_copilot.

Unlike seed_slide_reporting_agent.py (which extends one orchestrator),
this script extends FIVE independent, already-live agents -- two of which
(fund_analyst_agent, company_research_copilot) were built via the admin UI
(created_by is None), not seeded by any script. Each agent's live row is
loaded and extended in place (tool attached if missing, one instruction
block appended if missing, its full existing tool/sub-agent list preserved
in the republished snapshot) -- never overwritten wholesale.

Idempotent per-agent: an agent that already has the tool attached AND the
instruction block is left untouched (no version bump). --reset undoes only
what this script added -- detaches the tool and strips the instruction
block from all five agents, then deletes the Tool row -- without touching
anything else about those agents. Real usage leaves tool_call_log rows
pointing at this Tool (tool_id has no ondelete cascade, unlike
invocation_id); --reset nulls that reference rather than deleting the log
rows outright, since those are real historical records of the *agent's*
tool calls, not something this script owns the right to erase.

Uses bare `app.X` imports (not `backend.app.X`) for the same reason
documented in seed_slide_reporting_agent.py: mixing import styles in one
process makes SQLAlchemy see app/models/agents.py imported twice under two
different qualified names, and raises "Table ... already defined for this
MetaData instance" the moment app.logging_hooks (which itself imports bare
`app.models.agents`) is touched.

Usage (from the backend/ directory):
    python scripts/seed_chart_tool.py [--reset]
"""

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import delete, select, update  # noqa: E402

from app.db import async_session_factory  # noqa: E402
from app.logging_hooks import write_audit_log  # noqa: E402
from app.models.agents import Agent, AgentSubagent, AgentTool, AgentVersion  # noqa: E402
from app.models.logs import ConfigAuditLog, ToolCallLog  # noqa: E402
from app.models.tools import Tool  # noqa: E402
from app.models.workspaces import DEFAULT_WORKSPACE_ID  # noqa: E402

SEED_MARKER = "chart-tool-import"
TOOL_NAME = "generate_chart_tool"
MCP_SERVER = "mcp_servers/chart_server.py"

TARGET_AGENT_NAMES = [
    "stock_market_analyst",
    "crypto_analyst",
    "forex_metals_analyst",
    "fund_analyst_agent",
    "company_research_copilot",
]

TOOL_DESCRIPTION = (
    "Render a chart PNG from a numeric series (trailing returns, price/NAV "
    "history, a multi-item comparison) and get back a ready-to-paste "
    "markdown image snippet for your reply."
)

TOOL_INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "chart_type": {"type": "string", "enum": ["bar", "line"]},
        "title": {"type": "string"},
        "x_labels": {"type": "array", "items": {"type": "string"}},
        "series": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "values": {"type": "array", "items": {"type": "number"}},
                },
                "required": ["name", "values"],
            },
        },
        "y_label": {"type": "string", "default": ""},
    },
    "required": ["chart_type", "title", "x_labels", "series"],
}

# Appended to each agent's base_instruction verbatim -- kept as one exact
# string so it can be idempotently detected/stripped by --reset.
#
# Written to explicitly override any numbered checklist above that already
# looks "complete" without it (e.g. fund_analyst_agent's step 2, "for a full
# analysis, always call BOTH of these") -- without this override language, a
# model following that checklist literally never reaches this paragraph for
# a "full"/"complete" analysis request, since its own steps never mention
# charting. Confirmed via a live invocation_log/tool_call_log trace: a
# "complete analysis" question called only the checklist's own tools and
# skipped generate_chart_tool entirely.
INSTRUCTION_BLOCK = (
    "IMPORTANT, and this overrides anything that looks like a complete "
    "checklist above: charting is a REQUIRED part of a complete answer, not "
    "an optional extra step -- this applies even when you're following a "
    "numbered list above for a \"full\"/\"complete\" analysis or a "
    "side-by-side comparison, whose own steps may not mention charting. "
    "Whenever your answer includes a multi-point numeric series -- trailing "
    "returns across periods, price/NAV/exchange-rate history over time, "
    "quarterly revenue, or a comparison across two or more "
    "funds/stocks/coins/currencies -- you must also call generate_chart_tool "
    "with that data (chart_type \"bar\" for period/category comparisons, "
    "\"line\" for a trend over time) and paste its returned markdown image "
    "snippet directly into your reply, in addition to the prose. Don't "
    "replace the numbers with only a chart -- include both -- and don't "
    "consider your answer complete without it."
)


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
        AgentVersion(agent_id=agent.id, version=agent.current_version, snapshot=snapshot, published_by=SEED_MARKER)
    )
    agent.status = "published"
    await write_audit_log(
        session, entity_type="agent", entity_id=agent.id, action="publish",
        actor=SEED_MARKER, diff={"version": agent.current_version}, workspace_id=DEFAULT_WORKSPACE_ID,
    )


async def _find_ancestor_ids(session, agent_id) -> set:
    """Every agent that has `agent_id` as a descendant, at any depth --
    mirrors app/config_api/agents.py::_find_ancestor_ids. A published
    agent's build is cached as a fully-materialized tree (children baked in
    at build time, not keyed on the children's own version), so republishing
    a specialist leaves any already-cached ORCHESTRATOR silently serving the
    old specialist until the orchestrator's own version is bumped too.
    Confirmed the hard way: market_intelligence kept serving a stale
    fund_analyst_agent (missing generate_chart_tool) until it was bumped."""
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


async def _bump_ancestors(session, changed_agent_ids: set) -> None:
    """Only PUBLISHED ancestors need bumping: a draft is always built fresh
    from live config (agent_runtime/builder.py's version=None path is never
    cached), so it has no stale cache entry to invalidate. An archived
    ancestor isn't served at all -- and _republish() unconditionally sets
    status="published", so touching one would silently un-archive it. Learned
    this the hard way: an early version of this function briefly flipped
    'india_fund_orchestrator' from archived back to published as a side
    effect of just bumping its version for cache invalidation."""
    ancestor_ids: set = set()
    for agent_id in changed_agent_ids:
        ancestor_ids |= await _find_ancestor_ids(session, agent_id)
    ancestor_ids -= changed_agent_ids  # already republished directly, don't double-bump

    for ancestor_id in ancestor_ids:
        ancestor = await session.get(Agent, ancestor_id)
        if ancestor is None:
            continue
        if ancestor.status != "published":
            print(f"  skipping ancestor '{ancestor.name}' ({ancestor.status}) -- not live, nothing to invalidate")
            continue
        await _republish(session, ancestor)
        print(f"  bumped ancestor '{ancestor.name}' (now version {ancestor.current_version}) to invalidate its cache")


async def _load_agents(session) -> dict[str, Agent]:
    agents: dict[str, Agent] = {}
    missing = []
    for name in TARGET_AGENT_NAMES:
        agent = (await session.execute(select(Agent).where(Agent.name == name))).scalar_one_or_none()
        if agent is None:
            missing.append(name)
        else:
            agents[name] = agent
    if missing:
        print(f"Agent(s) not found: {', '.join(missing)} -- seed them first.")
        sys.exit(1)
    return agents


async def reset(session) -> None:
    print("Resetting chart-tool wiring...")
    tool = (
        await session.execute(select(Tool).where(Tool.name == TOOL_NAME, Tool.created_by == SEED_MARKER))
    ).scalar_one_or_none()

    agents = {
        name: (await session.execute(select(Agent).where(Agent.name == name))).scalar_one_or_none()
        for name in TARGET_AGENT_NAMES
    }

    changed_ids: set = set()
    for name, agent in agents.items():
        if agent is None:
            continue
        changed = False
        if tool is not None:
            existing_link = (
                await session.execute(
                    select(AgentTool).where(AgentTool.agent_id == agent.id, AgentTool.tool_id == tool.id)
                )
            ).scalar_one_or_none()
            if existing_link is not None:
                await session.execute(
                    delete(AgentTool).where(AgentTool.agent_id == agent.id, AgentTool.tool_id == tool.id)
                )
                changed = True
        if INSTRUCTION_BLOCK in agent.base_instruction:
            agent.base_instruction = (
                agent.base_instruction.replace(f"\n\n{INSTRUCTION_BLOCK}", "")
                .replace(INSTRUCTION_BLOCK, "")
                .rstrip()
            )
            changed = True
        if changed:
            await _republish(session, agent)
            print(f"  reverted {name} (now version {agent.current_version})")
            changed_ids.add(agent.id)

    if changed_ids:
        await _bump_ancestors(session, changed_ids)

    await session.execute(delete(ConfigAuditLog).where(ConfigAuditLog.actor == SEED_MARKER))
    if tool is not None:
        # tool_id has no ondelete cascade -- detach real historical tool-call
        # records rather than deleting them, then it's safe to drop the Tool row.
        await session.execute(update(ToolCallLog).where(ToolCallLog.tool_id == tool.id).values(tool_id=None))
        await session.execute(delete(Tool).where(Tool.id == tool.id))
    await session.commit()


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reset", action="store_true")
    args = parser.parse_args()

    async with async_session_factory() as session:
        if args.reset:
            await reset(session)

        agents = await _load_agents(session)

        tool = (
            await session.execute(select(Tool).where(Tool.name == TOOL_NAME, Tool.created_by == SEED_MARKER))
        ).scalar_one_or_none()
        if tool is None:
            tool = Tool(
                name=TOOL_NAME,
                workspace_id=DEFAULT_WORKSPACE_ID,
                tool_type="mcp_tool",
                description=TOOL_DESCRIPTION,
                config={"transport": "stdio", "command": "python", "args": [MCP_SERVER], "tool_name": TOOL_NAME},
                input_schema=TOOL_INPUT_SCHEMA,
                created_by=SEED_MARKER,
            )
            session.add(tool)
            await session.flush()
            print(f"Created tool '{TOOL_NAME}'.")

        changed_ids: set = set()
        for name, agent in agents.items():
            already_attached = (
                await session.execute(
                    select(AgentTool).where(AgentTool.agent_id == agent.id, AgentTool.tool_id == tool.id)
                )
            ).scalar_one_or_none() is not None
            already_instructed = INSTRUCTION_BLOCK in agent.base_instruction

            if already_attached and already_instructed:
                print(f"'{name}' already wired. Skipping.")
                continue

            if not already_attached:
                session.add(AgentTool(agent_id=agent.id, tool_id=tool.id))
            if not already_instructed:
                agent.base_instruction = agent.base_instruction.rstrip() + f"\n\n{INSTRUCTION_BLOCK}"
            await session.flush()

            await _republish(session, agent)
            changed_ids.add(agent.id)
            print(f"Wired '{name}' (now version {agent.current_version}).")

        if changed_ids:
            await _bump_ancestors(session, changed_ids)
        else:
            print("Nothing to do -- all agents already wired. Use --reset to reseed.")

        await session.commit()


if __name__ == "__main__":
    asyncio.run(main())
