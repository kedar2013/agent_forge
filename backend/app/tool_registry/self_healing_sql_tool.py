"""Self-healing execution loop (error reflection) for text-to-SQL.

Standard text-to-SQL: generate a query, run it, and if it's wrong the user
sees a database error. This tool instead returns any validation or
execution failure as the tool's own *result* (never raises) — a normal
ADK function-calling turn keeps looping while the model keeps requesting
tool calls, so the model sees the exact error text (e.g. a MySQL "Unknown
column 'rev' in 'field list'") in its own context on the very next turn,
and can rewrite the query using the real column/table name before calling
this tool again. That's the whole mechanism: nothing here "retries" on
the model's behalf — the model does, because the tool is honest about
failures instead of swallowing them.

The loop is capped (`max_retries` in config, default 5) so a model that
can't converge doesn't spin forever: a per-session, per-tool retry counter
lives in `tool_context.state`, incremented on every failure and reset to 0
on the first success. Once the cap is exceeded, the tool stops returning
"try again" errors and instead returns an explicit instruction to give up
and tell the user — the tool enforces the stop condition; it doesn't trust
the model to count its own attempts.

Query decomposition (see read_scratchpad_tool.py): an orchestrator
splitting a compound question into sub-queries can pass an optional
`scratchpad_slot` argument. On success, the JSON result is written to
`tool_context.state[scratchpad_slot]` in addition to being returned
directly — a synthesizer sub-agent (no SQL tool of its own) later reads
those slots back with read_scratchpad_tool and writes the final answer.
This is the same tool used standalone (no scratchpad_slot) for the
plain self-healing use case.

Validation mirrors app/tool_registry/data_query_tool.py's proven
approach almost exactly (real sqlglot AST — single read-only SELECT, an
allow-listed set of tables, a forbidden-function denylist) generalized to
(a) MySQL dialect and (b) a *set* of allowed tables rather than exactly
one, matching nl2sql_tool.py's multi-table shape instead.
"""

import asyncio
import os
import time
from typing import Any

import pymysql
import sqlglot
from dbutils.pooled_db import PooledDB
from dotenv import load_dotenv
from sqlglot import exp

from app.tool_registry.base import ConfigDrivenTool
from app.tool_registry.data_query_tool import _FORBIDDEN_NODE_TYPES, _forbidden_function_call
from app.tool_registry.serialize import to_json_safe

# app/config.py's pydantic Settings only bridges a couple of specific keys
# into os.environ — an arbitrary connection_env_prefix's _HOST/_PORT/_USER/
# _PASSWORD/_DATABASE block was never one of them, so load .env directly
# (idempotent, never overrides a real env var already set) — same pattern
# mysql_tool.py/policy_engine.py already use for the same reason.
load_dotenv(os.path.join(os.path.dirname(__file__), "..", "..", ".env"))

_pool_cache: dict[str, PooledDB] = {}


def _get_pool(prefix: str) -> PooledDB:
    if prefix not in _pool_cache:
        database = os.environ.get(f"{prefix}_DATABASE") or os.environ[f"{prefix}_NAME"]
        _pool_cache[prefix] = PooledDB(
            creator=pymysql,
            maxconnections=5,
            mincached=1,
            blocking=True,
            host=os.environ.get(f"{prefix}_HOST", "localhost"),
            port=int(os.environ.get(f"{prefix}_PORT", "3306")),
            user=os.environ.get(f"{prefix}_USER", "root"),
            password=os.environ.get(f"{prefix}_PASSWORD", ""),
            database=database,
            cursorclass=pymysql.cursors.DictCursor,
            autocommit=True,
        )
    return _pool_cache[prefix]


def _table_short_name(qualified: str) -> str:
    return qualified.split(".")[-1].lower()


def _validate_select_only(sql: str) -> tuple[exp.Expression | None, str | None]:
    """Structural (sqlglot AST), not string/keyword matching — see
    data_query_tool.py's module docstring for why a regex-based version of
    this would be unsafe. Returns (parsed_statement, None) on success or
    (None, error_message) on failure — the error message is what gets
    handed back to the model to self-correct from."""
    try:
        statements = [s for s in sqlglot.parse(sql, dialect="mysql") if s is not None]
    except Exception as exc:
        return None, f"SQL failed to parse: {exc}"

    if len(statements) != 1:
        return None, "Multiple statements are not allowed — write exactly one SELECT query."

    stmt = statements[0]
    if not isinstance(stmt, exp.Select):
        return None, f"Only SELECT (or WITH ... SELECT) queries are allowed, got: {type(stmt).__name__}"

    for node in stmt.walk():
        if isinstance(node, _FORBIDDEN_NODE_TYPES):
            return None, "Query contains a forbidden write/DDL operation."

    func_error = _forbidden_function_call(stmt)
    if func_error:
        return None, func_error

    return stmt, None


def _cte_names(parsed: exp.Expression) -> set[str]:
    with_clause = parsed.args.get("with_")
    if with_clause is None:
        return set()
    return {cte.alias_or_name.lower() for cte in with_clause.expressions}


def _validate_allowed_tables(parsed: exp.Expression, allowed_tables: list[str]) -> str | None:
    allowed_short = {_table_short_name(t) for t in allowed_tables}
    cte_names = _cte_names(parsed)
    referenced = {t.name.lower() for t in parsed.find_all(exp.Table)} - cte_names
    if not referenced:
        return "Query must reference at least one table."
    disallowed = referenced - allowed_short
    if disallowed:
        return (
            f"Table(s) not available to this tool: {', '.join(sorted(disallowed))}. "
            f"Allowed tables: {', '.join(allowed_tables)}"
        )
    return None


class SelfHealingSqlTool(ConfigDrivenTool):
    """`config` shape:
        {
          "connection_env_prefix": "REVENUE_RETURNS_MYSQL",
          "allowed_tables": ["rr_product_master", "rr_revenue_returns_monthly"],
          "max_rows": 200,
          "max_retries": 5
        }
    """

    def __init__(self, *, name: str, description: str, input_schema: dict, config: dict) -> None:
        super().__init__(name=name, description=description, input_schema=input_schema)
        self._config = config

    def _retry_state_key(self) -> str:
        # Scoped per tool name (not global) so two self-healing tools on the
        # same agent tree don't share one counter.
        return f"_self_healing_retries:{self.name}"

    async def run_async(self, *, args: dict[str, Any], tool_context) -> Any:
        allowed_tables: list[str] = self._config["allowed_tables"]
        max_rows: int = self._config.get("max_rows", 200)
        max_retries: int = self._config.get("max_retries", 5)
        prefix = self._config["connection_env_prefix"]
        scratchpad_slot: str | None = args.get("scratchpad_slot")

        sql = args.get("sql", "")
        state_key = self._retry_state_key()
        retry_count = tool_context.state.get(state_key, 0)

        def _fail(reason: str) -> dict:
            nonlocal retry_count
            retry_count += 1
            tool_context.state[state_key] = retry_count
            if retry_count > max_retries:
                return {
                    "error": (
                        f"Maximum retry attempts ({max_retries}) reached without a working query. "
                        f"Stop retrying. Tell the user the data could not be retrieved and briefly "
                        f"explain why (last error: {reason})."
                    ),
                    "retries_exhausted": True,
                }
            return {
                "error": f"{reason} (attempt {retry_count}/{max_retries}). "
                "Review the error message, correct the query, and call this tool again.",
            }

        if retry_count > max_retries:
            # A prior call already hit the cap and the model called again
            # anyway — keep refusing rather than let the counter climb
            # forever or silently start accepting queries again.
            return _fail("Retry limit already reached for this question")

        parsed, error = _validate_select_only(sql)
        if error:
            return _fail(error)
        error = _validate_allowed_tables(parsed, allowed_tables)
        if error:
            return _fail(error)

        had_own_limit = parsed.args.get("limit") is not None
        if not had_own_limit:
            parsed = parsed.limit(max_rows)
        final_sql = parsed.sql(dialect="mysql")

        def _run_query() -> list[dict]:
            pool = _get_pool(prefix)
            conn = pool.connection()
            try:
                with conn.cursor() as cur:
                    cur.execute("START TRANSACTION READ ONLY")
                    cur.execute(final_sql)
                    rows = list(cur.fetchall())
                    conn.rollback()
                    return rows
            finally:
                conn.close()

        start = time.perf_counter()
        try:
            rows = await asyncio.to_thread(_run_query)
        except Exception as exc:
            # The exact DB engine error (e.g. "Unknown column 'rev' in
            # 'field list'") is what lets the model self-correct — passed
            # through verbatim, not swallowed into a generic message.
            return _fail(str(exc))
        execution_ms = (time.perf_counter() - start) * 1000

        # Success: reset the retry counter so a later, unrelated question
        # in the same session starts with a fresh budget.
        tool_context.state[state_key] = 0

        data = [to_json_safe(r) for r in rows]
        result = {
            "row_count": len(data),
            "columns": list(data[0].keys()) if data else [],
            "rows": data,
            "truncated": (not had_own_limit) and len(data) >= max_rows,
            "execution_ms": round(execution_ms, 2),
        }
        if scratchpad_slot:
            tool_context.state[scratchpad_slot] = result
        return result
