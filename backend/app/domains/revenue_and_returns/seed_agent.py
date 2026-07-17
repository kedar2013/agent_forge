"""Seeds the Postgres-side platform config for Revenue and Returns Analysis:
two `data_entities` rows (the data dictionary for rr_product_master and
rr_revenue_returns_monthly), two `data_query_tool` rows built from them,
and the `revenue_returns_analyst` agent, published standalone (per
`chat_api.list_chat_orchestrators`, any published top-level agent is a
valid /chat target).

No SQL is authored here at all — `query_products`/`query_revenue_data` are
generic `data_query_tool` instances (see
`app/tool_registry/data_query_tool.py`); the LLM writes the SELECT
statement itself at chat time, guided by the schema description
`_hydrate_data_query_tool` (config_api/tools.py) composes from each
entity's field list. This script is the exact same path the "New Domain"
wizard's UI takes — it just calls the pieces directly instead of through
HTTP forms. Mirrors `app.domains.credit_facility.seed_agent` almost
verbatim.

Deliberately no access policy / row-level security here — every user sees
all revenue/returns data (the wizard's "skip — every user sees the same
data" option). To add RLS later, follow credit_facility's
`policy_config.py` pattern: author a `RESOLVER_CONFIG`/`QUERY_RULES` dict
(no code), create an `AccessPolicy` row from it, and pass its id as
`config.policy_id` when building the tools below — nothing else changes.

Run `seed_data.py` first (or after; order doesn't matter for THIS script,
but the agent is useless without data to actually query).

Idempotent: `--reset` undoes only what this script created (identified by
`created_by`/`actor` == SEED_MARKER), mirroring credit_facility's pattern.

Usage (from backend/, so `app.*` imports resolve):
    python -m app.domains.revenue_and_returns.seed_agent [--reset]
"""

import argparse
import asyncio

from sqlalchemy import delete, select

from app.config_api.tools import _hydrate_data_query_tool
from app.db import async_session_factory
from app.logging_hooks import write_audit_log
from app.models.agents import Agent, AgentTool, AgentVersion
from app.models.data_entities import DataEntity
from app.models.logs import ConfigAuditLog, InvocationLog, ToolCallLog
from app.models.tools import Tool
from app.models.workspaces import DEFAULT_WORKSPACE_ID

SEED_MARKER = "revenue-returns-import"
MODEL_CONFIG = {"model": "gemini-3.5-flash", "temperature": 0.1}
MYSQL_CONNECTION = {"type": "mysql", "connection_env_prefix": "REVENUE_RETURNS_MYSQL"}

AGENT_NAME = "revenue_returns_analyst"
AGENT_DESCRIPTION = (
    "Answers questions about product revenue, returns, and refunds — gross/net revenue, "
    "return rates, units sold/returned — across the business unit / category / product hierarchy."
)
AGENT_INSTRUCTION = """You are the Revenue and Returns Analysis specialist. You answer questions
about product revenue, returns, and refunds by writing SQL yourself against the tools'
described schemas — there is no fixed query behind either tool, you write a real
SELECT statement each time.

1. Each tool's own description lists its exact table name and columns (name, type,
   label). Never reference a column that isn't listed, and never guess a table name.
2. If the user names a product (e.g. "Wireless Earbuds Pro") and you don't already
   have its exact product_id, call query_products first with a SELECT that filters
   product_name (e.g. `WHERE product_name LIKE '%Earbuds%'`). If it returns zero
   rows, say so plainly in normal text — never guess a product_id. If it returns
   several plausible matches, do not pick one yourself and do not present them as a
   markdown table — instead respond with ONLY this JSON object, nothing before or
   after it, so the user can pick one with a click instead of retyping a name:
   {"type": "options", "prompt": "<short question, e.g. Which product did you mean?>",
   "options": [{"label": "<product_name> (<sku>)", "value": "<same string as label>"}]}
   Whichever option the user clicks comes back as their next message verbatim —
   treat it exactly as if they had typed that product's full identifying name
   themselves, and proceed to step 4 without re-querying query_products.
3. If a tool call's result contains "error", explain that plainly and do not retry
   with a guessed or invented value.
4. Call query_revenue_data with a SELECT against its table, filtering by the
   resolved product_id (or business_unit/category/region, for rollup questions).
   If the user didn't name a period, add `ORDER BY load_id DESC` and no LIMIT (the
   tool caps rows itself) and present only the first (most recent) row. If they
   asked for "last N months", show the first N rows. If they named specific months,
   filter load_id to those exact YYYYMM values (e.g. February 2026 -> 202602).
5. If asked what products/categories/business units exist, call query_products with
   no WHERE clause (just `SELECT * FROM ...`).
6. Present results as markdown tables using each column's label (from the tool's
   schema description), not its raw column name. When multiple months are shown, add
   a month-over-month trend and call out any unusually high return_rate_pct
   explicitly. Always state which month(s) (load_id) the data is from.
7. Never fabricate numbers. If a tool call returns zero rows, say plainly that no
   data was found for that product/period rather than inventing figures."""

PRODUCT_FIELDS = [
    {"name": "product_id", "label": "Product ID", "type": "string", "filterable": True, "visible": True},
    {"name": "product_name", "label": "Product Name", "type": "string", "searchable": True, "visible": True},
    {"name": "sku", "label": "SKU", "type": "string", "filterable": True, "visible": True},
    {"name": "business_unit", "label": "Business Unit", "type": "string", "visible": True, "filterable": True},
    {"name": "category", "label": "Category", "type": "string", "visible": True, "filterable": True},
    {"name": "sub_category", "label": "Sub-Category", "type": "string", "visible": True},
    {"name": "region", "label": "Region", "type": "string", "filterable": True, "visible": True},
    {
        "name": "product_level", "label": "Level", "type": "string",
        "filterable": True, "visible": True, "enum": ["L2", "L3", "L4"],
    },
    {"name": "launch_date", "label": "Launch Date", "type": "date", "visible": True},
]

REVENUE_FIELDS = PRODUCT_FIELDS + [
    {"name": "load_id", "label": "Month (YYYYMM)", "type": "integer", "filterable": True, "visible": True},
    {
        "name": "gross_revenue", "label": "Gross Revenue", "type": "decimal",
        "measure": True, "format": "currency", "visible": True,
    },
    {
        "name": "returns_amount", "label": "Returns Amount", "type": "decimal",
        "measure": True, "format": "currency", "visible": True,
    },
    {
        "name": "refund_amount", "label": "Refund Amount", "type": "decimal",
        "measure": True, "format": "currency", "visible": True,
    },
    {
        "name": "net_revenue", "label": "Net Revenue", "type": "decimal",
        "measure": True, "format": "currency", "visible": True,
    },
    {
        "name": "return_rate_pct", "label": "Return Rate %", "type": "decimal",
        "measure": True, "format": "percent", "visible": True,
    },
    {
        "name": "units_sold", "label": "Units Sold", "type": "integer",
        "measure": True, "format": "integer", "visible": True,
    },
    {
        "name": "units_returned", "label": "Units Returned", "type": "integer",
        "measure": True, "format": "integer", "visible": True,
    },
    {
        "name": "num_orders", "label": "Number of Orders", "type": "integer",
        "measure": True, "format": "integer", "visible": True,
    },
]

ENTITY_SPECS = {
    "rr_products": dict(
        description="Product master for Revenue and Returns Analysis — hierarchy, region, level.",
        source={"table": "rr_product_master", "primary_key": "product_id"},
        fields=PRODUCT_FIELDS,
        default_sort={"field": "product_name", "dir": "asc"},
        default_limit=20,
        max_limit=50,
    ),
    "rr_revenue_data": dict(
        description="Monthly revenue and returns per product for Revenue and Returns Analysis.",
        source={"table": "rr_revenue_returns_monthly", "primary_key": "id"},
        fields=REVENUE_FIELDS,
        default_sort={"field": "load_id", "dir": "desc"},
        default_limit=12,
        max_limit=24,
    ),
}

# tool_name -> entity name (no policy — see module docstring)
TOOL_SPECS = {
    "query_products": "rr_products",
    "query_revenue_data": "rr_revenue_data",
}


async def _get_or_create_entity(session, name: str, spec: dict) -> DataEntity:
    existing = await session.scalar(select(DataEntity).where(DataEntity.name == name))
    if existing:
        return existing
    entity = DataEntity(
        workspace_id=DEFAULT_WORKSPACE_ID, name=name, description=spec["description"],
        connection=MYSQL_CONNECTION, source=spec["source"], fields=spec["fields"],
        default_sort=spec["default_sort"], default_limit=spec["default_limit"], max_limit=spec["max_limit"],
    )
    session.add(entity)
    await session.flush()
    return entity


def _publish_snapshot(agent: Agent, tools: list[Tool]) -> dict:
    return {
        "name": agent.name, "description": agent.description, "base_instruction": agent.base_instruction,
        "model_config": agent.model_config_json, "output_schema": agent.output_schema,
        "output_key": agent.output_key, "tools": [{"id": str(t.id), "name": t.name} for t in tools],
        "skills": [], "sub_agents": [],
    }


async def reset(session) -> None:
    print("Resetting previously-seeded revenue-returns agent config...")
    agent_ids = (await session.execute(select(Agent.id).where(Agent.created_by == SEED_MARKER))).scalars().all()
    if agent_ids:
        invocation_ids = (
            (await session.execute(select(InvocationLog.id).where(InvocationLog.agent_id.in_(agent_ids))))
            .scalars().all()
        )
        if invocation_ids:
            await session.execute(delete(ToolCallLog).where(ToolCallLog.invocation_id.in_(invocation_ids)))
            await session.execute(delete(InvocationLog).where(InvocationLog.id.in_(invocation_ids)))
        await session.execute(delete(AgentTool).where(AgentTool.agent_id.in_(agent_ids)))
        await session.execute(delete(AgentVersion).where(AgentVersion.agent_id.in_(agent_ids)))
        await session.execute(delete(Agent).where(Agent.id.in_(agent_ids)))
    await session.execute(delete(ConfigAuditLog).where(ConfigAuditLog.actor == SEED_MARKER))
    await session.execute(delete(Tool).where(Tool.created_by == SEED_MARKER))
    await session.execute(delete(DataEntity).where(DataEntity.name.in_(list(ENTITY_SPECS))))
    await session.commit()


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reset", action="store_true")
    args = parser.parse_args()

    async with async_session_factory() as session:
        if args.reset:
            await reset(session)

        existing_agent = await session.scalar(select(Agent).where(Agent.created_by == SEED_MARKER))
        if existing_agent:
            print(f"'{AGENT_NAME}' already seeded. Use --reset to reseed.")
            return

        entities_by_name = {
            name: await _get_or_create_entity(session, name, spec) for name, spec in ENTITY_SPECS.items()
        }

        tool_rows: list[Tool] = []
        for tool_name, entity_name in TOOL_SPECS.items():
            fields = {"config": {"entity_id": str(entities_by_name[entity_name].id), "policy_id": None}}
            await _hydrate_data_query_tool(session, DEFAULT_WORKSPACE_ID, fields)
            tool = Tool(
                name=tool_name, workspace_id=DEFAULT_WORKSPACE_ID, tool_type="data_query_tool",
                description=fields["description"], config=fields["config"], input_schema=fields["input_schema"],
                created_by=SEED_MARKER,
            )
            session.add(tool)
            tool_rows.append(tool)
        await session.flush()

        agent = Agent(
            name=AGENT_NAME, workspace_id=DEFAULT_WORKSPACE_ID, description=AGENT_DESCRIPTION,
            base_instruction=AGENT_INSTRUCTION, model_config_json=MODEL_CONFIG, created_by=SEED_MARKER,
        )
        session.add(agent)
        await session.flush()

        for tool in tool_rows:
            session.add(AgentTool(agent_id=agent.id, tool_id=tool.id))
        await session.flush()

        snapshot = _publish_snapshot(agent, tool_rows)
        session.add(AgentVersion(agent_id=agent.id, version=1, snapshot=snapshot, published_by=SEED_MARKER))
        agent.status = "published"
        agent.current_version = 1
        await write_audit_log(
            session, entity_type="agent", entity_id=agent.id, action="publish", actor=SEED_MARKER,
            diff={"version": 1}, workspace_id=DEFAULT_WORKSPACE_ID,
        )

        await session.commit()
        print(f"Created and published '{AGENT_NAME}' with {len(tool_rows)} tools, 2 data entities.")


if __name__ == "__main__":
    asyncio.run(main())
