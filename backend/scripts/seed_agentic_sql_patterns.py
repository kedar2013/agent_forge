"""Seeds two demonstration agent trees for the revenue_and_returns MySQL
domain (rr_product_master / rr_revenue_returns_monthly — real seeded data,
see app/domains/revenue_and_returns/seed_data.py), each showing one
agentic data-retrieval technique end to end:

1. Self-healing execution loop (error reflection) —
   `self_healing_revenue_analyst`, a standalone agent with one
   `self_healing_sql_tool`. The tool never raises on a bad query; it
   returns the real DB/validation error as its result, so the model sees
   it on the next turn and can rewrite the query itself. Capped at
   `max_retries` (config, default 5) via a tool_context.state counter —
   see app/tool_registry/self_healing_sql_tool.py's module docstring for
   the full mechanism.

2. Query decomposition for complex analytics —
   `revenue_query_orchestrator` (root) + `revenue_query_synthesizer`
   (sub-agent). The orchestrator splits a compound question into up to 3
   independent sub-queries, runs each through the SAME self-healing tool
   (so decomposition and error-reflection compose for free — every
   sub-query self-heals too), storing each JSON result in a scratchpad
   slot (`scratchpad_1`/`_2`/`_3`) via the tool's optional
   `scratchpad_slot` argument. It then silently transfers to the
   synthesizer, which has no SQL tool of its own — only
   `read_scratchpad_tool` — reads back whatever slots were filled, and
   writes the final natural-language answer.

Both tools/agents are read-only against revenue_and_returns; nothing here
can write to the database (see self_healing_sql_tool.py — SELECT-only,
AST-validated, table-allowlisted, forbidden-function-denylisted, same
security posture as every other SQL-executing tool in this app).

Idempotent: `--reset` undoes only what this script created (identified by
`created_by`/`actor` == SEED_MARKER), same pattern as
app/domains/revenue_and_returns/seed_agent.py and
scripts/seed_nl2sql_orchestrator.py.

Usage (from backend/, so `app.*` imports resolve):
    python scripts/seed_agentic_sql_patterns.py [--reset]
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

SEED_MARKER = "agentic-sql-patterns-import"
MODEL_CONFIG = {"model": "gemini-2.5-flash", "temperature": 0.1}

# Shared schema description — both the standalone analyst and the
# orchestrator write raw SQL against the exact same two tables, so both
# instructions need it verbatim. Single source of truth here rather than
# copy-pasted, so a schema change only needs one edit.
SCHEMA_DESCRIPTION = """Tables available (MySQL):

rr_product_master — one row per product/hierarchy node
  product_id (string, PK), product_name (string), sku (string),
  business_unit (string), category (string), sub_category (string),
  region (string), product_level (string: 'L2'|'L3'|'L4'), launch_date (date)

rr_revenue_returns_monthly — one row per product per month
  id (int, PK), product_id (string), product_name (string),
  business_unit (string), category (string), sub_category (string),
  region (string), product_level (string), load_id (int, format YYYYMM,
  e.g. February 2026 = 202602), gross_revenue (decimal), returns_amount
  (decimal), refund_amount (decimal), net_revenue (decimal, =
  gross_revenue - returns_amount - refund_amount), return_rate_pct
  (decimal, = returns_amount / gross_revenue), units_sold (int),
  units_returned (int), num_orders (int)

Never reference a column or table not listed above."""

SELF_HEALING_TOOL_NAME = "revenue_self_healing_sql"
SELF_HEALING_TOOL_CONFIG = {
    "connection_env_prefix": "REVENUE_RETURNS_MYSQL",
    "allowed_tables": ["rr_product_master", "rr_revenue_returns_monthly"],
    "max_rows": 200,
    "max_retries": 5,
}
SELF_HEALING_TOOL_SCHEMA = {
    "type": "object",
    "properties": {
        "sql": {"type": "string", "description": "One read-only SELECT statement against the allowed tables."},
        "scratchpad_slot": {
            "type": "string",
            "enum": ["scratchpad_1", "scratchpad_2", "scratchpad_3"],
            "description": (
                "Optional. Only set this when decomposing a multi-part question — "
                "a distinct slot per sub-query so the result can be read back later. "
                "Omit entirely for a single, standalone query."
            ),
        },
    },
    "required": ["sql"],
}
SELF_HEALING_TOOL_DESCRIPTION = (
    "Executes one read-only SELECT against the revenue_and_returns MySQL database. "
    "If the query fails (bad column/table name, syntax error), the error message is "
    "returned as the result — read it, correct the query, and call this tool again "
    "(capped at 5 attempts per question). " + SCHEMA_DESCRIPTION
)

READ_SCRATCHPAD_TOOL_NAME = "read_query_scratchpad"
READ_SCRATCHPAD_TOOL_DESCRIPTION = (
    "Returns whatever sub-query results have already been stored in the scratchpad "
    "(scratchpad_1/2/3) by an earlier query. Takes no arguments. Call this first, "
    "before writing your answer."
)

# --- Agent 1: standalone self-healing analyst -------------------------------

SELF_HEALING_AGENT_NAME = "self_healing_revenue_analyst"
SELF_HEALING_AGENT_DESCRIPTION = (
    "Answers single-question revenue/returns lookups by writing its own SQL, and "
    "automatically corrects its own query if the database rejects it (self-healing "
    "execution loop) instead of surfacing a raw error to the user."
)
SELF_HEALING_AGENT_INSTRUCTION = f"""You are a revenue & returns data analyst. You answer questions by
writing a real SQL SELECT statement yourself and running it with revenue_self_healing_sql
— there is no fixed query behind the tool.

{SCHEMA_DESCRIPTION}

How to use the tool:
1. Write one SELECT statement per question and call revenue_self_healing_sql with it.
   Do not set scratchpad_slot — that's only for multi-part questions handled by a
   different agent.
2. If the result contains "error", read the error message carefully — it usually
   names the exact problem (e.g. an unknown column name, or a table you're not
   allowed to query) — correct your SQL and call the tool again. This is expected
   and normal; don't apologize for it or mention it to the user.
3. If the result says the retry limit was reached ("retries_exhausted"), stop
   calling the tool. Tell the user plainly that the data couldn't be retrieved and
   briefly say why, based on the last error — never fabricate an answer instead.
4. On success, present the rows as a markdown table using clear column labels (not
   raw column names — e.g. "Gross Revenue" not "gross_revenue"), and state which
   month(s) (load_id) the data covers. If the user named a product by name and you
   don't know its product_id, look it up first with a SELECT ... WHERE product_name
   LIKE '%...%' against rr_product_master.
5. Never fabricate numbers. If a query legitimately returns zero rows, say so."""

# --- Agent 2: orchestrator + synthesizer (query decomposition) -------------

ORCHESTRATOR_AGENT_NAME = "revenue_query_orchestrator"
ORCHESTRATOR_AGENT_DESCRIPTION = (
    "Handles compound revenue/returns questions with multiple independent parts "
    "(e.g. comparing two business units, two periods, or two regions) by decomposing "
    "them into separate SQL queries, then handing off to a synthesizer agent for the "
    "final combined answer."
)
ORCHESTRATOR_AGENT_INSTRUCTION = f"""You are the revenue & returns query orchestrator. You handle
questions that have MULTIPLE independent data parts — e.g. "How did Apparel's Q2 revenue
compare to Electronics' Q2 return rate?" has two parts: Apparel Q2 revenue, and
Electronics Q2 return rate.

{SCHEMA_DESCRIPTION}

How to handle a question:
1. If the question has only ONE part (a single lookup, no comparison), just answer
   it yourself: call revenue_self_healing_sql once with a plain SELECT (no
   scratchpad_slot needed), then present the result directly. Do not transfer for a
   single-part question.
2. If the question has TWO OR THREE independent parts, decompose it into that many
   separate SELECT statements — one per part. Call revenue_self_healing_sql once per
   part, giving each call a DIFFERENT scratchpad_slot in order: "scratchpad_1" for
   the first part, "scratchpad_2" for the second, "scratchpad_3" for a third if
   there is one. If any call returns an error, read it and retry with a corrected
   query before moving to the next part (same self-healing behavior as any other
   call to this tool — see the tool's own error messages for what to do, capped at
   5 attempts per part).
3. Once every part has succeeded and is stored in its scratchpad slot, do not write
   the final answer yourself and do not narrate what you're doing — silently call
   transfer_to_agent to hand off to revenue_query_synthesizer, which will read the
   scratchpad and write the final combined answer.
4. Never fabricate figures. If a part legitimately returns zero rows, store that
   result anyway (don't skip the transfer) — the synthesizer will say plainly that
   part had no data."""

SYNTHESIZER_AGENT_NAME = "revenue_query_synthesizer"
SYNTHESIZER_AGENT_DESCRIPTION = (
    "Reads the sub-query results revenue_query_orchestrator stored in the scratchpad "
    "and writes the final natural-language answer to the user's original compound "
    "question. Never queries the database itself."
)
SYNTHESIZER_AGENT_INSTRUCTION = """You are the revenue & returns synthesis agent. You are only ever
invoked after revenue_query_orchestrator has already run 2 or 3 independent sub-queries
and stored each JSON result in a scratchpad slot. You have no SQL tool of your own — you
never query the database, only read what's already been fetched.

1. Call read_query_scratchpad first, with no arguments, to retrieve whatever results
   are stored (scratchpad_1, scratchpad_2, and/or scratchpad_3 — not every slot will
   necessarily be filled).
2. Write ONE clear, natural-language answer to the user's original question, using
   the retrieved rows. Explicitly attribute each figure to which part of the question
   it answers (e.g. "Apparel's Q2 gross revenue was $X, while Electronics' Q2 return
   rate was Y%") rather than just listing two disconnected tables — actually compare
   or connect them the way the user's question asked.
3. If the scratchpad came back empty or a part legitimately had zero rows, say so
   plainly for that part rather than inventing a number.
4. Never call any SQL tool yourself — you don't have one, by design."""


def _publish_snapshot(agent: Agent, tools: list[Tool], sub_agents: list[Agent] | None = None) -> dict:
    return {
        "name": agent.name,
        "description": agent.description,
        "base_instruction": agent.base_instruction,
        "model_config": agent.model_config_json,
        "output_schema": agent.output_schema,
        "output_key": agent.output_key,
        "tools": [{"id": str(t.id), "name": t.name} for t in tools],
        "skills": [],
        "sub_agents": [{"id": str(a.id), "name": a.name} for a in (sub_agents or [])],
    }


async def _delete_agent_tree(session, agent_names: list[str]) -> None:
    agent_ids = (await session.execute(select(Agent.id).where(Agent.name.in_(agent_names)))).scalars().all()
    if not agent_ids:
        return
    invocation_ids = (
        (await session.execute(select(InvocationLog.id).where(InvocationLog.agent_id.in_(agent_ids))))
        .scalars().all()
    )
    if invocation_ids:
        await session.execute(delete(ToolCallLog).where(ToolCallLog.invocation_id.in_(invocation_ids)))
        await session.execute(delete(InvocationLog).where(InvocationLog.id.in_(invocation_ids)))
    await session.execute(delete(AgentSubagent).where(AgentSubagent.parent_agent_id.in_(agent_ids)))
    await session.execute(delete(AgentSubagent).where(AgentSubagent.child_agent_id.in_(agent_ids)))
    await session.execute(delete(AgentTool).where(AgentTool.agent_id.in_(agent_ids)))
    await session.execute(delete(AgentVersion).where(AgentVersion.agent_id.in_(agent_ids)))
    await session.execute(delete(Agent).where(Agent.id.in_(agent_ids)))


async def reset(session) -> None:
    print("Resetting previously-seeded agentic SQL pattern demo agents...")
    await _delete_agent_tree(
        session,
        [SELF_HEALING_AGENT_NAME, ORCHESTRATOR_AGENT_NAME, SYNTHESIZER_AGENT_NAME],
    )
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

        existing = await session.scalar(select(Agent).where(Agent.name == SELF_HEALING_AGENT_NAME))
        if existing is not None:
            print(f"'{SELF_HEALING_AGENT_NAME}' already seeded. Use --reset to reseed.")
            return

        # One self_healing_sql_tool row, shared by both the standalone
        # analyst and the orchestrator (same connection/tables/config —
        # only how each agent's instruction tells it to use scratchpad_slot
        # differs).
        self_healing_tool = Tool(
            name=SELF_HEALING_TOOL_NAME,
            workspace_id=DEFAULT_WORKSPACE_ID,
            tool_type="self_healing_sql_tool",
            description=SELF_HEALING_TOOL_DESCRIPTION,
            config=SELF_HEALING_TOOL_CONFIG,
            input_schema=SELF_HEALING_TOOL_SCHEMA,
            created_by=SEED_MARKER,
        )
        read_scratchpad_tool = Tool(
            name=READ_SCRATCHPAD_TOOL_NAME,
            workspace_id=DEFAULT_WORKSPACE_ID,
            tool_type="read_scratchpad_tool",
            description=READ_SCRATCHPAD_TOOL_DESCRIPTION,
            config={},
            input_schema={"type": "object", "properties": {}},
            created_by=SEED_MARKER,
        )
        session.add(self_healing_tool)
        session.add(read_scratchpad_tool)
        await session.flush()

        # --- Agent 1: standalone self-healing analyst ---
        self_healing_agent = Agent(
            name=SELF_HEALING_AGENT_NAME,
            workspace_id=DEFAULT_WORKSPACE_ID,
            description=SELF_HEALING_AGENT_DESCRIPTION,
            base_instruction=SELF_HEALING_AGENT_INSTRUCTION,
            model_config_json=MODEL_CONFIG,
            created_by=SEED_MARKER,
        )
        session.add(self_healing_agent)
        await session.flush()
        session.add(AgentTool(agent_id=self_healing_agent.id, tool_id=self_healing_tool.id))
        await session.flush()
        session.add(
            AgentVersion(
                agent_id=self_healing_agent.id,
                version=1,
                snapshot=_publish_snapshot(self_healing_agent, [self_healing_tool]),
                published_by=SEED_MARKER,
            )
        )
        self_healing_agent.status = "published"
        self_healing_agent.current_version = 1
        await write_audit_log(
            session, entity_type="agent", entity_id=self_healing_agent.id, action="publish", actor=SEED_MARKER,
            diff={"version": 1}, workspace_id=DEFAULT_WORKSPACE_ID,
        )
        print(f"Created and published '{SELF_HEALING_AGENT_NAME}'.")

        # --- Agent 2a: synthesizer (published standalone first, same as
        # nl2sql_orchestrator's specialists — a sub_agent must already be a
        # real published agent before it's attached) ---
        synthesizer = Agent(
            name=SYNTHESIZER_AGENT_NAME,
            workspace_id=DEFAULT_WORKSPACE_ID,
            description=SYNTHESIZER_AGENT_DESCRIPTION,
            base_instruction=SYNTHESIZER_AGENT_INSTRUCTION,
            model_config_json=MODEL_CONFIG,
            created_by=SEED_MARKER,
        )
        session.add(synthesizer)
        await session.flush()
        session.add(AgentTool(agent_id=synthesizer.id, tool_id=read_scratchpad_tool.id))
        await session.flush()
        session.add(
            AgentVersion(
                agent_id=synthesizer.id,
                version=1,
                snapshot=_publish_snapshot(synthesizer, [read_scratchpad_tool]),
                published_by=SEED_MARKER,
            )
        )
        synthesizer.status = "published"
        synthesizer.current_version = 1
        await write_audit_log(
            session, entity_type="agent", entity_id=synthesizer.id, action="publish", actor=SEED_MARKER,
            diff={"version": 1}, workspace_id=DEFAULT_WORKSPACE_ID,
        )
        print(f"Created and published '{SYNTHESIZER_AGENT_NAME}'.")

        # --- Agent 2b: orchestrator (root), attaches synthesizer as
        # sub_agent BEFORE its own first publish — see
        # seed_nl2sql_orchestrator.py's comment on why the ordering matters
        # (a snapshot freezes sub_agents at publish time). ---
        orchestrator = Agent(
            name=ORCHESTRATOR_AGENT_NAME,
            workspace_id=DEFAULT_WORKSPACE_ID,
            description=ORCHESTRATOR_AGENT_DESCRIPTION,
            base_instruction=ORCHESTRATOR_AGENT_INSTRUCTION,
            model_config_json=MODEL_CONFIG,
            created_by=SEED_MARKER,
        )
        session.add(orchestrator)
        await session.flush()
        session.add(AgentTool(agent_id=orchestrator.id, tool_id=self_healing_tool.id))
        session.add(AgentSubagent(parent_agent_id=orchestrator.id, child_agent_id=synthesizer.id))
        await session.flush()
        session.add(
            AgentVersion(
                agent_id=orchestrator.id,
                version=1,
                snapshot=_publish_snapshot(orchestrator, [self_healing_tool], [synthesizer]),
                published_by=SEED_MARKER,
            )
        )
        orchestrator.status = "published"
        orchestrator.current_version = 1
        await write_audit_log(
            session, entity_type="agent", entity_id=orchestrator.id, action="publish", actor=SEED_MARKER,
            diff={"version": 1}, workspace_id=DEFAULT_WORKSPACE_ID,
        )
        print(f"Created and published '{ORCHESTRATOR_AGENT_NAME}' with sub-agent '{SYNTHESIZER_AGENT_NAME}'.")

        await session.commit()


if __name__ == "__main__":
    asyncio.run(main())
