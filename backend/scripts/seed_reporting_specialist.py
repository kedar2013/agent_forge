"""Seeds `reporting_specialist` — a standalone, domain-agnostic agent that
turns data already in the conversation (or that it fetches itself, if a
data tool is attached to it) into a chart, slide deck, or exported
document. This is the "slide reporting should be generic" fix: every tool
it uses — `chart_planner_tool`/`slide_builder_tool`
(mcp_servers/slide_reporting_server.py), `generate_chart_tool`
(mcp_servers/chart_server.py), `export_to_pdf`/`export_to_excel`
(mcp_servers/document_export_server.py) — was ALREADY domain-agnostic code;
the only thing missing was an agent that bundles them without also dragging
in `nl_to_sql_tool`/`sql_execution_tool`'s sales_analytics-specific NL2SQL.

Reuses the EXISTING `chart_planner_tool`/`slide_builder_tool`/
`generate_chart_tool` Tool rows (looked up by name) rather than duplicating
them — the same row is already attached to multiple other agents (mcp_tool
subprocesses are spawned fresh per call, so sharing a row across agents is
the normal pattern here, see seed_chart_tool.py). Creates new rows only for
`export_to_pdf`/`export_to_excel`, which weren't attached to anything yet.

Proves cross-domain reuse concretely (not just in theory) by attaching
`reporting_specialist` as a sub-agent to TWO unrelated existing
orchestrators/agents:
  - `market_intelligence_orchestrator` (finance/market data)
  - `credit_facility_analyst` (banking/credit risk) — which ALSO gets its
    own `query_facility_data`/`query_companies` `data_query_tool` rows
    attached directly onto reporting_specialist, so it can fetch-and-report
    standalone rather than depending on the parent having already pulled
    data into the conversation.

Idempotent: `--reset` undoes only what this script created (identified by
`created_by`/SEED_MARKER) — the two new export tool rows and the agent
itself — and detaches (but does not delete) the sub-agent edges and the
data_query_tool attachments on credit_facility_analyst, then republishes
the parents back to their pre-attachment tool/sub-agent set.

Usage (from backend/, so `app.*` imports resolve):
    python scripts/seed_reporting_specialist.py [--reset]
"""

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import delete, select  # noqa: E402

from app.agent_runtime.cache import agent_cache  # noqa: E402
from app.db import async_session_factory  # noqa: E402
from app.logging_hooks import write_audit_log  # noqa: E402
from app.models.agents import Agent, AgentSkill, AgentSubagent, AgentTool, AgentVersion  # noqa: E402
from app.models.logs import ConfigAuditLog  # noqa: E402
from app.models.skills import Skill  # noqa: E402
from app.models.tools import Tool  # noqa: E402
from app.models.workspaces import DEFAULT_WORKSPACE_ID  # noqa: E402

SEED_MARKER = "reporting-specialist-import"
MODEL_CONFIG = {"model": "gemini-2.5-flash", "temperature": 0.2}

AGENT_NAME = "reporting_specialist"
AGENT_DESCRIPTION = (
    "Turns data into a chart, slide deck, or exported document — attach it as a "
    "sub-agent to any orchestrator; it never invents data, only presents what's "
    "already in the conversation or what its own attached data tools return."
)
AGENT_INSTRUCTION = """You are the Reporting specialist. You turn data into a chart, a
downloadable slide deck, or an exported PDF/Excel file — you are not a data source
yourself.

1. If a data tool is attached to you (e.g. a data_query_tool), and the user's request
   requires data you don't already have in this conversation, call it first.
2. Otherwise, use whatever data the conversation already contains — the orchestrator
   that transferred to you already gathered it. Never invent numbers.
3. For "chart of X" -> generate_chart_tool. For "slide deck/presentation of X" ->
   chart_planner_tool then slide_builder_tool, in that order, piping each result into
   the next. For "PDF/report of X" -> export_to_pdf (write the markdown yourself).
   For "Excel/spreadsheet of X" -> export_to_excel.
4. If you have no usable data and no data tool of your own, say so plainly rather
   than fabricating a chart or deck from invented numbers.
5. Always relay the download link plainly, plus a one-line summary of what it shows."""

EXPORT_TOOL_SPECS = {
    "export_to_pdf": dict(
        description="Generate a formatted PDF from analysis you've already written, and get a download link.",
        input_schema={
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Short title (used as filename + PDF header)."},
                "markdown_content": {"type": "string", "description": "The write-up in GFM markdown."},
            },
            "required": ["title", "markdown_content"],
        },
    ),
    "export_to_excel": dict(
        description="Generate a formatted Excel spreadsheet from tabular data you've already gathered.",
        input_schema={
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Short title (used as filename)."},
                "sheet_name": {"type": "string", "description": "Worksheet tab name (max 31 chars)."},
                "rows": {
                    "type": "array",
                    "items": {"type": "object"},
                    "description": "Data rows, each a dict of column_name -> value.",
                },
            },
            "required": ["title", "sheet_name", "rows"],
        },
    ),
}

REUSED_TOOL_NAMES = ["chart_planner_tool", "slide_builder_tool", "generate_chart_tool"]

# Which existing standalone/orchestrator agents get reporting_specialist
# attached as a sub-agent, proving it serves more than one domain, plus the
# routing line appended to each parent's own base_instruction so the model
# reliably knows when to hand off (this repo's convention — see
# seed_slide_reporting_agent.py, which does the same for slide_reporting_agent
# — rather than relying only on ADK's automatic sub-agent description exposure).
ATTACH_TO = {
    "market_intelligence_orchestrator": (
        "\n- reporting_specialist: turn already-fetched data into a chart, slide deck, "
        "or exported PDF/Excel (e.g. \"make me a slide deck of that\", \"export this as PDF\")."
    ),
    "credit_facility_analyst": (
        "\n\nIf the user asks for a chart, slide deck, or exported PDF/Excel of credit "
        "facility data, transfer to reporting_specialist rather than trying to build one "
        "yourself."
    ),
}

# Additionally attached directly onto reporting_specialist (not just its
# parent) so it can fetch-and-report standalone for credit_facility_analyst.
CREDIT_FACILITY_DATA_TOOLS = ["query_companies", "query_facility_data"]


async def _get_agent(session, name: str) -> Agent | None:
    return await session.scalar(select(Agent).where(Agent.name == name))


async def _get_tool(session, name: str) -> Tool | None:
    return await session.scalar(select(Tool).where(Tool.name == name))


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
    print("Resetting previously-seeded reporting_specialist...")
    agent = await _get_agent(session, AGENT_NAME)
    if agent is not None:
        for parent_name in ATTACH_TO:
            parent = await _get_agent(session, parent_name)
            if parent is not None:
                await session.execute(
                    delete(AgentSubagent).where(
                        AgentSubagent.parent_agent_id == parent.id, AgentSubagent.child_agent_id == agent.id
                    )
                )
                await session.flush()
                await _republish(session, parent)
        await session.execute(delete(AgentTool).where(AgentTool.agent_id == agent.id))
        await session.execute(delete(AgentVersion).where(AgentVersion.agent_id == agent.id))
        await session.execute(delete(Agent).where(Agent.id == agent.id))
    await session.execute(delete(ConfigAuditLog).where(ConfigAuditLog.actor == SEED_MARKER))
    await session.execute(delete(Tool).where(Tool.created_by == SEED_MARKER))
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

        tool_rows: list[Tool] = []
        for name in REUSED_TOOL_NAMES:
            tool = await _get_tool(session, name)
            if tool is None:
                print(f"Expected an existing tool named '{name}' but found none — run its owning seed script first.")
                return
            tool_rows.append(tool)

        for tool_name, spec in EXPORT_TOOL_SPECS.items():
            tool = Tool(
                name=tool_name,
                workspace_id=DEFAULT_WORKSPACE_ID,
                tool_type="mcp_tool",
                description=spec["description"],
                config={
                    "transport": "stdio",
                    "command": "python",
                    "args": ["mcp_servers/document_export_server.py"],
                    "tool_name": tool_name,
                },
                input_schema=spec["input_schema"],
                created_by=SEED_MARKER,
            )
            session.add(tool)
            tool_rows.append(tool)
        await session.flush()

        agent = Agent(
            name=AGENT_NAME,
            workspace_id=DEFAULT_WORKSPACE_ID,
            description=AGENT_DESCRIPTION,
            base_instruction=AGENT_INSTRUCTION,
            model_config_json=MODEL_CONFIG,
            created_by=SEED_MARKER,
        )
        session.add(agent)
        await session.flush()

        for tool in tool_rows:
            session.add(AgentTool(agent_id=agent.id, tool_id=tool.id))
        await session.flush()

        # Publish standalone first (version 1) so it's independently testable.
        await _republish(session, agent)
        await write_audit_log(
            session, entity_type="agent", entity_id=agent.id, action="publish", actor=SEED_MARKER,
            diff={"version": agent.current_version}, workspace_id=DEFAULT_WORKSPACE_ID,
        )
        print(f"Created and published '{AGENT_NAME}' with {len(tool_rows)} tools.")

        # Give credit_facility_analyst's own data tools to reporting_specialist
        # too, so it can fetch-and-report standalone under that parent.
        cf_agent = await _get_agent(session, "credit_facility_analyst")
        if cf_agent is not None:
            for name in CREDIT_FACILITY_DATA_TOOLS:
                data_tool = await _get_tool(session, name)
                if data_tool is not None:
                    session.add(AgentTool(agent_id=agent.id, tool_id=data_tool.id))
            await session.flush()
            await _republish(session, agent)  # re-snapshot reporting_specialist with the data tools included

        for parent_name, routing_line in ATTACH_TO.items():
            parent = await _get_agent(session, parent_name)
            if parent is None:
                print(f"'{parent_name}' not found — skipping attachment.")
                continue
            session.add(AgentSubagent(parent_agent_id=parent.id, child_agent_id=agent.id))
            if AGENT_NAME not in parent.base_instruction:
                parent.base_instruction = parent.base_instruction + routing_line
            await session.flush()
            await _republish(session, parent)
            print(f"Attached '{AGENT_NAME}' as a sub-agent of '{parent_name}' (now version {parent.current_version}).")

        await session.commit()


if __name__ == "__main__":
    asyncio.run(main())
