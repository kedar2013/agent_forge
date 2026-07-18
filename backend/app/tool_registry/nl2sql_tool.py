"""Two tools that together let an agent turn a natural-language question into
SQL, run it safely, and get real rows back — the standard "text-to-SQL agent"
pattern (schema tool + guarded query tool), since this ADK version's own
`DataAgentToolset` is a wrapper around a managed GCP Data Agent resource, not
something usable against an arbitrary local Postgres database.

Safety is layered, not just prompted:
  1. The query must parse as a single SELECT/WITH statement — no other
     statement type, no stacked statements. Structural, via a real sqlglot
     AST (see app/tool_registry/data_query_tool.py for the sibling
     single-table version of this same approach) — NOT regex/keyword
     matching. A regex-based predecessor of this validator had two real
     bypasses a real AST walk doesn't have: (a) `FROM a, b` old-style
     comma-joins only matched the FIRST table after `FROM`/`JOIN`, so a
     second table smuggled in via a comma never got checked against the
     allow-list; (b) a table-less, function-only SELECT (e.g.
     `SELECT pg_read_file('/etc/passwd')`) has no FROM/JOIN keyword at all,
     so the old table-allowlist check saw nothing to reject.
  2. A denylist rejects specific dangerous function calls (file read/write,
     cross-server connections, timing-based DoS) regardless of whether the
     query also references an allowed table — see
     data_query_tool._FORBIDDEN_FUNCTION_NAMES for the Postgres entries this
     mirrors.
  3. Every referenced table must be in the tool's configured allow-list, AND
     at least one must be referenced — a table-less query is never a
     legitimate use of this tool.
  4. The query itself runs inside a Postgres `SET TRANSACTION READ ONLY`
     transaction — enforced by the database engine, not just app-level
     validation, so a query that slips past 1-3 still can't write anything.
  5. Row count is capped and a LIMIT is appended if the query doesn't have one.
"""

import os
from typing import Any

import sqlglot
from sqlglot import exp
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from app.reliability.resilient_call import resilient_call
from app.tool_registry.base import ConfigDrivenTool
from app.tool_registry.data_query_tool import _forbidden_function_call
from app.tool_registry.serialize import to_json_safe

_engine_cache: dict[str, AsyncEngine] = {}

_FORBIDDEN_NODE_TYPES = (
    exp.Insert, exp.Update, exp.Delete, exp.Drop, exp.Alter, exp.Create, exp.TruncateTable,
)


def _get_engine(connection_url: str) -> AsyncEngine:
    if connection_url not in _engine_cache:
        _engine_cache[connection_url] = create_async_engine(connection_url, pool_pre_ping=True)
    return _engine_cache[connection_url]


def _table_short_name(qualified: str) -> str:
    return qualified.split(".")[-1].lower()


class DbSchemaTool(ConfigDrivenTool):
    """Reports column names/types for a configured allow-list of tables, so
    an agent can generate correct SQL without guessing at column names.

    `config` shape:
        {
          "connection_env": "DATABASE_URL",
          "allowed_tables": ["agent_forge.invocation_log", "agent_forge.agents", ...]
        }
    """

    def __init__(self, *, name: str, description: str, input_schema: dict, config: dict) -> None:
        super().__init__(name=name, description=description, input_schema=input_schema)
        self._config = config

    async def run_async(self, *, args: dict[str, Any], tool_context) -> Any:
        connection_url = os.environ[self._config["connection_env"]]
        engine = _get_engine(connection_url)
        allowed_tables: list[str] = self._config["allowed_tables"]

        async def _load_schema() -> list[dict]:
            tables_info = []
            async with engine.connect() as conn:
                for qualified in allowed_tables:
                    schema_name, table_name = qualified.split(".") if "." in qualified else ("public", qualified)
                    result = await conn.execute(
                        text(
                            "SELECT column_name, data_type FROM information_schema.columns "
                            "WHERE table_schema = :schema AND table_name = :table "
                            "ORDER BY ordinal_position"
                        ),
                        {"schema": schema_name, "table": table_name},
                    )
                    columns = [{"column": r.column_name, "type": r.data_type} for r in result.fetchall()]
                    tables_info.append({"table": qualified, "columns": columns})
            return tables_info

        tables_info = await resilient_call(f"nl2sql_schema:{self.name}", _load_schema)
        return {"tables": tables_info}


def _validate_select_only(sql: str) -> tuple[exp.Expression | None, str | None]:
    """Structural (sqlglot AST), not string/keyword matching — see module
    docstring for why the regex predecessor of this function was unsafe.
    Returns (parsed_statement, None) on success or (None, error_message)."""
    try:
        statements = [s for s in sqlglot.parse(sql, dialect="postgres") if s is not None]
    except Exception as exc:
        return None, f"SQL failed to parse: {exc}"

    if len(statements) != 1:
        return None, "Multiple statements are not allowed — write one SELECT query."

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
    """CTE-defined names (`WITH recent AS (...) SELECT * FROM recent`)
    aren't real tables and were never meant to be checked against the
    allow-list — sqlglot's table walk picks them up as ordinary `exp.Table`
    references (they're referenced the same way a real table is), so they
    must be excluded explicitly or a query using its own CTE alias would be
    rejected as touching an "unauthorized table"."""
    with_clause = parsed.args.get("with_")
    if with_clause is None:
        return set()
    return {cte.alias_or_name.lower() for cte in with_clause.expressions}


def _validate_allowed_tables(parsed: exp.Expression, allowed_tables: list[str]) -> str | None:
    """Requires every referenced (non-CTE) table be in the allow-list, AND
    that at least one real table is referenced at all — a table-less query
    (e.g. a function-only SELECT) is never a legitimate use of this tool.
    AST-based (`find_all(exp.Table)` walks the whole tree, including
    subqueries and every side of a comma-separated FROM list), unlike the
    regex predecessor this replaces, which only matched a table name
    immediately following a literal `FROM`/`JOIN` keyword — `FROM a, b`
    silently let `b` through unchecked."""
    allowed_short = {_table_short_name(t) for t in allowed_tables}
    cte_names = _cte_names(parsed)
    referenced = {t.name.lower() for t in parsed.find_all(exp.Table)} - cte_names
    if not referenced:
        return "Query must reference at least one table."
    disallowed = referenced - allowed_short
    if disallowed:
        return f"Table(s) not available to this tool: {', '.join(sorted(disallowed))}. Allowed tables: {', '.join(allowed_tables)}"
    return None


class Nl2SqlQueryTool(ConfigDrivenTool):
    """Executes an LLM-generated SQL SELECT statement, guarded (see module
    docstring) so it can only ever read, and only from an allow-listed set
    of tables.

    `config` shape:
        {
          "connection_env": "DATABASE_URL",
          "allowed_tables": ["agent_forge.invocation_log", ...],
          "max_rows": 500
        }
    """

    def __init__(self, *, name: str, description: str, input_schema: dict, config: dict) -> None:
        super().__init__(name=name, description=description, input_schema=input_schema)
        self._config = config

    async def run_async(self, *, args: dict[str, Any], tool_context) -> Any:
        sql = args["sql"]
        allowed_tables: list[str] = self._config["allowed_tables"]
        max_rows: int = self._config.get("max_rows", 500)

        parsed, error = _validate_select_only(sql)
        if error:
            return {"error": error}
        error = _validate_allowed_tables(parsed, allowed_tables)
        if error:
            return {"error": error}

        # AST edit, never string concatenation — mirrors
        # data_query_tool.py's _ensure_limit pattern.
        had_own_limit = parsed.args.get("limit") is not None
        if not had_own_limit:
            parsed = parsed.limit(max_rows)
        final_sql = parsed.sql(dialect="postgres")

        connection_url = os.environ[self._config["connection_env"]]
        engine = _get_engine(connection_url)

        async def _run_query() -> list[dict]:
            async with engine.connect() as conn:
                await conn.execute(text("SET TRANSACTION READ ONLY"))
                result = await conn.execute(text(final_sql))
                rows = [to_json_safe(dict(row._mapping)) for row in result.fetchall()[:max_rows]]
                await conn.rollback()
            return rows

        try:
            rows = await resilient_call(f"nl2sql_query:{self.name}", _run_query)
        except Exception as exc:
            return {"error": f"Query failed: {exc}"}

        return {"row_count": len(rows), "rows": rows}
