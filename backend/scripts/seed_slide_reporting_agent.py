"""Seeds a "Slide Reporting" specialist agent on top of the new MCP server
(mcp_servers/slide_reporting_server.py) and attaches it as a sub-agent of
the existing "market_intelligence" orchestrator (created by
seed_market_agents.py) -- run that script first if it hasn't been run yet.

Unlike seed_market_agents.py (which creates its orchestrator fresh), this
script EXTENDS a live orchestrator: it loads market_intelligence's current
base_instruction from the database (not a hardcoded constant), so any edits
made via the admin UI since seeding aren't clobbered, and appends one
routing line plus an AgentSubagent edge, then republishes it at
current_version + 1.

Idempotent: re-running without --reset is a no-op if already seeded
(identified by created_by/actor == SEED_MARKER). --reset undoes only what
this script created -- the 4 tools, the specialist agent, the sub-agent
edge, and the routing line in market_intelligence's instruction -- without
touching market_intelligence's own identity or its other specialists.

Usage (from the backend/ directory, same as seed_market_agents.py):
    python scripts/seed_slide_reporting_agent.py [--reset]

Note on imports: this uses bare `app.X` imports (run with cwd=backend/),
not the `backend.app.X` style seed_market_agents.py uses. Mixing the two
styles in one process double-imports app/models/agents.py under two
different qualified names, and SQLAlchemy raises "Table ... already
defined for this MetaData instance" the moment a second module (like
app.logging_hooks, which itself imports bare `app.models.agents`) touches
the same table -- confirmed while building this script. Bare imports avoid
that entirely and are what the app's own modules use internally.
"""

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import delete, select  # noqa: E402

from app.db import async_session_factory  # noqa: E402
from app.logging_hooks import write_audit_log  # noqa: E402
from app.models.agents import Agent, AgentSubagent, AgentTool, AgentVersion  # noqa: E402
from app.models.logs import ConfigAuditLog, InvocationLog, ToolCallLog  # noqa: E402
from app.models.tools import Tool  # noqa: E402
from app.models.workspaces import DEFAULT_WORKSPACE_ID  # noqa: E402

SEED_MARKER = "slide-reporting-import"
MODEL_CONFIG = {"model": "gemini-2.5-flash", "temperature": 0.2}

ORCHESTRATOR_NAME = "market_intelligence_orchestrator"
SPECIALIST_NAME = "slide_reporting_agent"
MCP_SERVER = "mcp_servers/slide_reporting_server.py"

SPECIALIST_DESCRIPTION = (
    "Turns a natural-language sales/orders/revenue question into a chart + "
    "downloadable PowerPoint deck. Use for \"show me a slide/deck/presentation "
    "of X\", \"chart/visualize X\", or \"summarize sales/orders/revenue by X\" "
    "-- prefer this over a plain data answer when the user wants a visual "
    "deliverable."
)

SPECIALIST_INSTRUCTION = """You are the Slide Reporting specialist. You turn a natural-language
sales/orders/revenue question into a polished PowerPoint deck by calling
exactly these four tools, IN THIS ORDER, every time:

1. nl_to_sql_tool(question, context) -- generates a single read-only MySQL
   SELECT statement against the sales_analytics database. You only ever
   produce/execute SELECT statements -- never INSERT/UPDATE/DELETE/DROP/
   ALTER/CREATE, and never more than one statement.
2. sql_execution_tool(sql, max_rows) -- runs the SQL from step 1's "sql"
   field.
   - If this returns an "error", call nl_to_sql_tool exactly ONE more time,
     passing the error message via `context` so it can self-correct, then
     call sql_execution_tool again with the corrected SQL. If it fails a
     second time, stop and tell the user plainly that you couldn't answer
     the question from the data -- do not keep retrying.
3. chart_planner_tool(execution_result_json, question) -- pass it the exact
   JSON sql_execution_tool returned, plus the original question. It decides
   the chart type and slide outline.
4. slide_builder_tool(slide_plan_json, question) -- pass it the exact JSON
   chart_planner_tool returned, plus the original question. It renders and
   saves the PPTX and returns a download link.

When slide_builder_tool succeeds, reply with the download link it returned
plus a short (1-3 sentence) natural-language summary of what the deck shows
-- don't just repeat the raw tool output verbatim. If any step fails after
the one retry, say clearly that you couldn't build the report and briefly
why, instead of guessing or fabricating numbers."""

# tool_name -> (description, input_schema)
TOOLS = {
    "nl_to_sql_tool": (
        "Turn a natural-language sales question into a single MySQL SELECT "
        "statement against sales_analytics. Always call first.",
        {
            "type": "object",
            "properties": {
                "question": {"type": "string"},
                "context": {"type": "string", "description": "Prior-turn filters, or a previous SQL error to correct."},
            },
            "required": ["question"],
        },
    ),
    "sql_execution_tool": (
        "Execute a single read-only SELECT statement against sales_analytics "
        "and return the rows. Always call second, right after nl_to_sql_tool.",
        {
            "type": "object",
            "properties": {
                "sql": {"type": "string"},
                "max_rows": {"type": "integer", "default": 500},
            },
            "required": ["sql"],
        },
    ),
    "chart_planner_tool": (
        "Decide chart type(s) and a slide outline from a SQL execution "
        "result. Always call third, right after a successful sql_execution_tool.",
        {
            "type": "object",
            "properties": {
                "execution_result_json": {"type": "string"},
                "question": {"type": "string"},
            },
            "required": ["execution_result_json", "question"],
        },
    ),
    "slide_builder_tool": (
        "Render a slide plan into a downloadable PowerPoint deck. Always "
        "call fourth and last.",
        {
            "type": "object",
            "properties": {
                "slide_plan_json": {"type": "string"},
                "question": {"type": "string"},
            },
            "required": ["slide_plan_json", "question"],
        },
    ),
}

# Appended to market_intelligence's base_instruction verbatim -- kept as one
# exact string so it can be idempotently detected/stripped by --reset.
ROUTING_LINE = (
    "- slide_reporting_agent: turns a sales/orders/revenue question into a "
    "chart + downloadable PowerPoint deck -- pick this over a plain data "
    "answer when the user asks to \"show me a slide/deck/presentation of "
    "X\", \"chart/visualize X\", or \"summarize sales/orders/revenue by X\"."
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


async def _load_orchestrator(session) -> Agent:
    orchestrator = (
        await session.execute(select(Agent).where(Agent.name == ORCHESTRATOR_NAME))
    ).scalar_one_or_none()
    if orchestrator is None:
        print(
            f"'{ORCHESTRATOR_NAME}' not found -- run scripts/seed_market_agents.py first."
        )
        sys.exit(1)
    return orchestrator


async def _republish_orchestrator(session, orchestrator: Agent) -> None:
    tool_rows = (
        (await session.execute(
            select(Tool).join(AgentTool, AgentTool.tool_id == Tool.id)
            .where(AgentTool.agent_id == orchestrator.id)
        )).scalars().all()
    )
    sub_agent_rows = (
        (await session.execute(
            select(Agent).join(AgentSubagent, AgentSubagent.child_agent_id == Agent.id)
            .where(AgentSubagent.parent_agent_id == orchestrator.id)
        )).scalars().all()
    )

    orchestrator.current_version += 1
    snapshot = _publish_snapshot(orchestrator, tool_rows, sub_agent_rows)
    session.add(
        AgentVersion(agent_id=orchestrator.id, version=orchestrator.current_version,
                     snapshot=snapshot, published_by=SEED_MARKER)
    )
    orchestrator.status = "published"
    await write_audit_log(
        session, entity_type="agent", entity_id=orchestrator.id, action="publish",
        actor=SEED_MARKER, diff={"version": orchestrator.current_version},
        workspace_id=DEFAULT_WORKSPACE_ID,
    )


async def _find_ancestor_ids(session, agent_id) -> set:
    """Every agent that has `agent_id` as a descendant, at any depth --
    mirrors app/config_api/agents.py::_find_ancestor_ids. A published
    agent's build is cached as a fully-materialized tree (children baked in
    at build time, not keyed on the children's own version), so republishing
    market_intelligence isn't enough if IT ALSO has an ancestor -- that
    ancestor's cache entry would keep serving the pre-change tree until its
    own version is bumped too. market_intelligence has none today, but this
    keeps the script correct if that ever changes (see the identical
    real-world case this fixed in scripts/seed_chart_tool.py)."""
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


async def _bump_further_ancestors(session, orchestrator: Agent) -> None:
    """Only PUBLISHED ancestors need bumping -- see the detailed rationale
    (and the archived-agent bug it prevents) in
    scripts/seed_chart_tool.py::_bump_ancestors."""
    for ancestor_id in await _find_ancestor_ids(session, orchestrator.id):
        ancestor = await session.get(Agent, ancestor_id)
        if ancestor is None:
            continue
        if ancestor.status != "published":
            print(f"  skipping ancestor '{ancestor.name}' ({ancestor.status}) -- not live, nothing to invalidate")
            continue
        await _republish_orchestrator(session, ancestor)
        print(f"  bumped ancestor '{ancestor.name}' (now version {ancestor.current_version}) to invalidate its cache")


async def reset(session) -> None:
    print("Resetting previously-seeded slide-reporting agent...")
    specialist = (
        await session.execute(
            select(Agent).where(Agent.name == SPECIALIST_NAME, Agent.created_by == SEED_MARKER)
        )
    ).scalar_one_or_none()

    if specialist is not None:
        invocation_ids = (
            (await session.execute(select(InvocationLog.id).where(InvocationLog.agent_id == specialist.id)))
            .scalars().all()
        )
        if invocation_ids:
            await session.execute(delete(ToolCallLog).where(ToolCallLog.invocation_id.in_(invocation_ids)))
            await session.execute(delete(InvocationLog).where(InvocationLog.id.in_(invocation_ids)))
        await session.execute(delete(AgentSubagent).where(AgentSubagent.child_agent_id == specialist.id))
        await session.execute(delete(AgentTool).where(AgentTool.agent_id == specialist.id))
        await session.execute(delete(AgentVersion).where(AgentVersion.agent_id == specialist.id))
        await session.execute(delete(Agent).where(Agent.id == specialist.id))
        await session.flush()

    await session.execute(delete(ConfigAuditLog).where(ConfigAuditLog.actor == SEED_MARKER))
    await session.execute(delete(Tool).where(Tool.created_by == SEED_MARKER))

    orchestrator = (
        await session.execute(select(Agent).where(Agent.name == ORCHESTRATOR_NAME))
    ).scalar_one_or_none()
    if orchestrator is not None and ROUTING_LINE in orchestrator.base_instruction:
        orchestrator.base_instruction = (
            orchestrator.base_instruction.replace(f"\n\n{ROUTING_LINE}", "")
            .replace(ROUTING_LINE, "")
            .rstrip()
        )
        await _republish_orchestrator(session, orchestrator)
        await _bump_further_ancestors(session, orchestrator)

    await session.commit()


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reset", action="store_true")
    args = parser.parse_args()

    async with async_session_factory() as session:
        if args.reset:
            await reset(session)

        existing = (
            await session.execute(
                select(Agent).where(Agent.name == SPECIALIST_NAME, Agent.created_by == SEED_MARKER)
            )
        ).scalar_one_or_none()
        if existing is not None:
            print(f"'{SPECIALIST_NAME}' already seeded. Use --reset to reseed.")
            return

        orchestrator = await _load_orchestrator(session)

        tool_rows: list[Tool] = []
        for tool_name, (description, input_schema) in TOOLS.items():
            tool = Tool(
                name=tool_name,
                workspace_id=DEFAULT_WORKSPACE_ID,
                tool_type="mcp_tool",
                description=description,
                config={
                    "transport": "stdio",
                    "command": "python",
                    "args": [MCP_SERVER],
                    "tool_name": tool_name,
                },
                input_schema=input_schema,
                created_by=SEED_MARKER,
            )
            session.add(tool)
            tool_rows.append(tool)
        await session.flush()

        specialist = Agent(
            name=SPECIALIST_NAME,
            workspace_id=DEFAULT_WORKSPACE_ID,
            description=SPECIALIST_DESCRIPTION,
            base_instruction=SPECIALIST_INSTRUCTION,
            model_config_json=MODEL_CONFIG,
            created_by=SEED_MARKER,
        )
        session.add(specialist)
        await session.flush()

        for tool in tool_rows:
            session.add(AgentTool(agent_id=specialist.id, tool_id=tool.id))
        await session.flush()

        snapshot = _publish_snapshot(specialist, tool_rows, [])
        session.add(AgentVersion(agent_id=specialist.id, version=1, snapshot=snapshot, published_by=SEED_MARKER))
        specialist.status = "published"
        specialist.current_version = 1
        await write_audit_log(
            session, entity_type="agent", entity_id=specialist.id, action="publish",
            actor=SEED_MARKER, diff={"version": 1}, workspace_id=DEFAULT_WORKSPACE_ID,
        )
        print(f"Created specialist '{SPECIALIST_NAME}' with {len(tool_rows)} tools.")

        session.add(AgentSubagent(parent_agent_id=orchestrator.id, child_agent_id=specialist.id))
        await session.flush()

        if ROUTING_LINE not in orchestrator.base_instruction:
            orchestrator.base_instruction = orchestrator.base_instruction.rstrip() + f"\n\n{ROUTING_LINE}"
        await _republish_orchestrator(session, orchestrator)
        await _bump_further_ancestors(session, orchestrator)

        await session.commit()
        print(
            f"Attached '{SPECIALIST_NAME}' to '{ORCHESTRATOR_NAME}' "
            f"(now version {orchestrator.current_version})."
        )


if __name__ == "__main__":
    asyncio.run(main())
