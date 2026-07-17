"""Seeds the Postgres-side platform config for Credit Facility Analysis: two
`data_entities` rows (the data dictionary for cf_company_master and
cf_company_facility_monthly), two `access_policies` rows (query access +
search access), two `data_query_tool` rows built from them, and the
`credit_facility_analyst` agent, published standalone (per
`chat_api.list_chat_orchestrators`, any published top-level agent is a
valid /chat target — this isn't a Market Intelligence sub-agent, it's an
unrelated banking domain).

No SQL is authored here at all — `query_companies`/`query_facility_data`
are generic `data_query_tool` instances (see
`app/tool_registry/data_query_tool.py`); the LLM writes the SELECT
statement itself at chat time, guided by the schema description
`_hydrate_data_query_tool` (config_api/tools.py) composes from each
entity's field list. This script is the exact same path the "New Domain"
wizard's UI takes — it just calls the pieces directly instead of through
HTTP forms.

Pure Postgres — no MySQL, no user accounts here. Run `seed_data.py` first
(or after; order doesn't matter for THIS script, but the agent is useless
without data and demo logins to actually test personas with).

Idempotent: `--reset` undoes only what this script created (identified by
`created_by`/`actor` == SEED_MARKER, or access_policies/data_entities
matched by name), mirroring `scripts/seed_slide_reporting_agent.py`'s
pattern.

Usage (from backend/, so `app.*` imports resolve):
    python -m app.domains.credit_facility.seed_agent [--reset]
"""

import argparse
import asyncio

from sqlalchemy import delete, select

from app.config_api.tools import _hydrate_data_query_tool
from app.db import async_session_factory
from app.domains.credit_facility.policy_config import (
    QUERY_POLICY_NAME,
    QUERY_RULES,
    RESOLVER_CONFIG,
    SEARCH_POLICY_NAME,
    SEARCH_RULES,
)
from app.logging_hooks import write_audit_log
from app.models.access_policies import AccessPolicy
from app.models.agents import Agent, AgentTool, AgentVersion
from app.models.data_entities import DataEntity
from app.models.logs import ConfigAuditLog, InvocationLog, ToolCallLog
from app.models.tools import Tool
from app.models.workspaces import DEFAULT_WORKSPACE_ID

SEED_MARKER = "credit-facility-import"
MODEL_CONFIG = {"model": "gemini-2.5-flash", "temperature": 0.1}
MYSQL_CONNECTION = {"type": "mysql", "connection_env_prefix": "CREDIT_FACILITY_MYSQL"}

AGENT_NAME = "credit_facility_analyst"
AGENT_DESCRIPTION = (
    "Answers questions about companies' monthly credit facility usage — limits, "
    "utilization, outstanding balances, overdue amounts — automatically scoped to "
    "the logged-in user's access level (GCM/GSG/Non-GSG/CCB)."
)
AGENT_INSTRUCTION = """You are the Credit Facility Analysis specialist. You answer questions
about companies' credit facility usage by writing SQL yourself against the tools'
described schemas — there is no fixed query behind either tool, you write a real
SELECT statement each time. Data visibility is already scoped to the logged-in
user's access level by the tools themselves — you never need to know or ask about
personas or permissions; if a query is rejected, the tool's "error" field explains
why in plain language.

1. Each tool's own description lists its exact table name and columns (name, type,
   label). Never reference a column that isn't listed, and never guess a table name.
2. If the user names a company (e.g. "Tesla Inc") and you don't already have its
   exact company_id or gfcid, call query_companies first with a SELECT that filters
   company_name (e.g. `WHERE company_name LIKE '%Tesla%'`). If it returns zero rows,
   say so plainly in normal text — never guess a company_id. If it returns several
   plausible matches, do not pick one yourself and do not present them as a markdown
   table — instead respond with ONLY this JSON object, nothing before or after it, so
   the user can pick one with a click instead of retyping a name:
   {"type": "options", "prompt": "<short question, e.g. Which company did you mean?>",
   "options": [{"label": "<company_name> (<gfcid or company_id>)", "value": "<same string as label>"}]}
   Whichever option the user clicks comes back as their next message verbatim —
   treat it exactly as if they had typed that company's full identifying name
   themselves, and proceed to step 4 without re-querying query_companies.
3. If a tool call's result contains "error", explain that plainly (e.g. "I don't
   have visibility into that company at your access level" or "please give me the
   exact facility ID (gfcid) for this company — your access level requires an exact
   reference rather than a name search, so include `WHERE gfcid = '...'` yourself")
   and do not retry with a guessed or invented value.
4. Call query_facility_data with a SELECT against its table, filtering by the
   resolved company_id (or gfcid, if that's what you have). If the user didn't name
   a period, add `ORDER BY load_id DESC` and no LIMIT (the tool caps rows itself) and
   present only the first (most recent) row. If they asked for "last N months", show
   the first N rows. If they named specific months, filter load_id to those exact
   YYYYMM values (e.g. February 2026 -> 202602).
5. If asked what companies they can see, call query_companies with no WHERE clause
   (just `SELECT * FROM ...`) — the tool's own access scoping still applies.
6. Present results as markdown tables using each column's label (from the tool's
   schema description), not its raw column name. When multiple months are shown, add
   a month-over-month utilization trend and call out any overdue amounts explicitly.
   Always state which month(s) (load_id) the data is from.
7. Never fabricate numbers. If a tool call returns zero rows, say plainly that no
   data was found for that company/period rather than inventing figures."""

COMPANY_FIELDS = [
    {"name": "company_id", "label": "Company ID", "type": "string", "filterable": True, "visible": True},
    {"name": "company_name", "label": "Company Name", "type": "string", "searchable": True, "visible": True},
    {"name": "gfcid", "label": "GFCID", "type": "string", "filterable": True, "visible": True},
    {"name": "l2", "label": "Sector", "type": "string", "visible": True},
    {"name": "l3", "label": "Group", "type": "string", "visible": True},
    {"name": "l4", "label": "Entity", "type": "string", "visible": True},
    {
        "name": "company_level", "label": "Level", "type": "string",
        "filterable": True, "visible": True, "enum": ["L2", "L3", "L4"],
    },
]

FACILITY_FIELDS = COMPANY_FIELDS + [
    {"name": "load_id", "label": "Month (YYYYMM)", "type": "integer", "filterable": True, "visible": True},
    {
        "name": "total_facility_limit", "label": "Facility Limit", "type": "decimal",
        "measure": True, "format": "currency", "visible": True,
    },
    {
        "name": "utilized_amount", "label": "Utilized Amount", "type": "decimal",
        "measure": True, "format": "currency", "visible": True,
    },
    {
        "name": "available_amount", "label": "Available Amount", "type": "decimal",
        "measure": True, "format": "currency", "visible": True,
    },
    {
        "name": "utilization_pct", "label": "Utilization %", "type": "decimal",
        "measure": True, "format": "percent", "visible": True,
    },
    {
        "name": "outstanding_balance", "label": "Outstanding Balance", "type": "decimal",
        "measure": True, "format": "currency", "visible": True,
    },
    {
        "name": "overdue_amount", "label": "Overdue Amount", "type": "decimal",
        "measure": True, "format": "currency", "visible": True,
    },
    {
        "name": "interest_accrued", "label": "Interest Accrued", "type": "decimal",
        "measure": True, "format": "currency", "visible": True,
    },
    {
        "name": "num_transactions", "label": "Number of Transactions", "type": "integer",
        "measure": True, "format": "integer", "visible": True,
    },
]

ENTITY_SPECS = {
    "cf_companies": dict(
        description="Company master for Credit Facility Analysis — hierarchy, gfcid, level.",
        source={"table": "cf_company_master", "primary_key": "company_id"},
        fields=COMPANY_FIELDS,
        default_sort={"field": "company_name", "dir": "asc"},
        default_limit=20,
        max_limit=50,
    ),
    "cf_facility_data": dict(
        description="Monthly credit facility usage per company for Credit Facility Analysis.",
        source={"table": "cf_company_facility_monthly", "primary_key": "id"},
        fields=FACILITY_FIELDS,
        default_sort={"field": "load_id", "dir": "desc"},
        default_limit=12,
        max_limit=24,
    ),
}

# tool_name -> (description override, entity name, policy name)
TOOL_SPECS = {
    "query_companies": ("cf_companies", SEARCH_POLICY_NAME),
    "query_facility_data": ("cf_facility_data", QUERY_POLICY_NAME),
}


async def _get_or_create_policy(session, name: str, rules: dict, description: str) -> AccessPolicy:
    existing = await session.scalar(select(AccessPolicy).where(AccessPolicy.name == name))
    if existing:
        return existing
    policy = AccessPolicy(
        workspace_id=DEFAULT_WORKSPACE_ID, name=name, description=description,
        resolver_config=RESOLVER_CONFIG, rules=rules,
    )
    session.add(policy)
    await session.flush()
    return policy


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
    print("Resetting previously-seeded credit-facility agent config...")
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
    await session.execute(delete(AccessPolicy).where(AccessPolicy.name.in_([QUERY_POLICY_NAME, SEARCH_POLICY_NAME])))
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

        query_policy = await _get_or_create_policy(
            session, QUERY_POLICY_NAME, QUERY_RULES, "Row-level scope for credit facility data lookups."
        )
        search_policy = await _get_or_create_policy(
            session, SEARCH_POLICY_NAME, SEARCH_RULES, "Row-level scope for credit facility company search (denies CCB)."
        )
        policy_by_name = {QUERY_POLICY_NAME: query_policy, SEARCH_POLICY_NAME: search_policy}

        entities_by_name = {
            name: await _get_or_create_entity(session, name, spec) for name, spec in ENTITY_SPECS.items()
        }

        tool_rows: list[Tool] = []
        for tool_name, (entity_name, policy_name) in TOOL_SPECS.items():
            fields = {
                "config": {
                    "entity_id": str(entities_by_name[entity_name].id),
                    "policy_id": str(policy_by_name[policy_name].id),
                },
            }
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
        print(f"Created and published '{AGENT_NAME}' with {len(tool_rows)} tools, 2 access policies, 2 data entities.")


if __name__ == "__main__":
    asyncio.run(main())
