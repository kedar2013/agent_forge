"""Generic, metadata-driven query tool: the LLM writes the SQL, this tool
validates it structurally (via a real `sqlglot` AST — single read-only
SELECT, single allowed table) and mechanically ANDs the caller's
row-level-security predicate onto it before executing, regardless of what
the LLM's own WHERE clause says. All table/column knowledge comes from the
`entity` snapshot frozen into this tool's own config at save time (see
`app.models.data_entities.DataEntity` and `config_api/tools.py`) — the same
Python class serves any domain pointed at it; nothing here is specific to
one table's shape.

Mirrors `mcp_servers/slide_reporting_server.py`'s proven sqlglot-based
validation (single-statement, no DML/DDL, AST-edited LIMIT) almost
verbatim, generalized to (a) any single table instead of a fixed schema,
and (b) row-level security enforcement, which that file's NL2SQL pattern
never needed.

`config` shape (see `config_api/tools.py` for how it gets populated):
    {
      "entity": { "connection": {...}, "source": {"table": "...", ...},
                  "fields": [...], "max_limit": 50 },
      "policy_id": "<uuid or None>",
      "policy_field_names": {"attribute": "...", "id": "...", "exact": "..."}
    }
"""

import asyncio
import os
import time
from typing import Any

import pymysql
import sqlglot
from dbutils.pooled_db import PooledDB
from sqlglot import exp

from app.tool_registry.base import ConfigDrivenTool
from app.tool_registry.serialize import to_json_safe

_pool_cache: dict[str, PooledDB] = {}

_FORBIDDEN_NODE_TYPES = (
    exp.Insert, exp.Update, exp.Delete, exp.Drop, exp.Alter, exp.Create, exp.TruncateTable,
)

# Defense-in-depth against function calls that read/write outside the
# database entirely — a plain "reject INSERT/UPDATE/DDL node types" check
# does NOT catch these, since e.g. `SELECT LOAD_FILE('/etc/passwd')` is a
# syntactically ordinary, single-table-free SELECT. Verified empirically:
# `INTO OUTFILE`/`INTO DUMPFILE` already fail to parse under this sqlglot
# version (an accident of the grammar, not a deliberate control — this list
# is the deliberate one). Every one of these is also excluded by
# validate_single_table's table-membership requirement below whenever a
# real table is in scope, but that check is per-tool (some tools legitimately
# span multiple tables) — this denylist is the one control that applies
# regardless of table shape.
_FORBIDDEN_FUNCTION_NAMES = frozenset(
    {
        "LOAD_FILE",  # MySQL: arbitrary local file read
        "PG_READ_FILE", "PG_READ_BINARY_FILE", "PG_LS_DIR", "PG_LS_LOGDIR", "PG_LS_WALDIR", "PG_STAT_FILE",
        "LO_IMPORT", "LO_EXPORT",  # Postgres: file read/write via large objects
        "DBLINK", "DBLINK_CONNECT", "DBLINK_EXEC",  # Postgres: outbound connections to other servers
        "SLEEP", "BENCHMARK",  # MySQL: timing-based DoS / blind enumeration
        "PG_SLEEP", "PG_SLEEP_FOR", "PG_SLEEP_UNTIL",  # Postgres: same
    }
)


def _forbidden_function_call(parsed: exp.Expression) -> str | None:
    for node in parsed.walk():
        candidate = node[0] if isinstance(node, tuple) else node
        if isinstance(candidate, exp.Func):
            name = (candidate.name or "").upper()
            if name in _FORBIDDEN_FUNCTION_NAMES:
                return f"Query calls a forbidden function ('{name}')."
    return None


def _get_pool(prefix: str) -> PooledDB:
    if prefix not in _pool_cache:
        # _NAME accepted as a fallback for _DATABASE — some existing
        # prefixes (SALES_DB_NAME) predate the _DATABASE convention, and
        # config_api/data_entities.py's introspection accepts both too.
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


def validate_single_select(sql: str, dialect: str = "mysql") -> str | None:
    """Returns an error message if `sql` isn't exactly one read-only SELECT
    statement, else None. Structural (via sqlglot's AST), not string/keyword
    matching — mirrors `slide_reporting_server.py`'s `_validate_single_select`."""
    try:
        statements = [s for s in sqlglot.parse(sql, dialect=dialect) if s is not None]
    except Exception as exc:
        return f"SQL failed to parse: {exc}"

    if len(statements) != 1:
        return "Only a single SQL statement is allowed (no stacked statements)."

    stmt = statements[0]
    if not isinstance(stmt, exp.Select):
        return f"Only SELECT (or WITH ... SELECT) statements are allowed, got: {type(stmt).__name__}"

    for node in stmt.walk():
        if isinstance(node, _FORBIDDEN_NODE_TYPES):
            return "Query contains a forbidden write/DDL operation."

    return _forbidden_function_call(stmt)


def validate_single_table(parsed: exp.Expression, allowed_table: str) -> str | None:
    """Requires the query reference EXACTLY the allowed table — not merely
    "no disallowed table was found". A query with zero table references
    (e.g. `SELECT LOAD_FILE('/etc/passwd')`, or any other FROM-less
    function-only SELECT) used to slip through here silently: an empty
    `tables` set has nothing to subtract the allowed table from, so
    `disallowed` came back empty and the query was accepted. This tool
    exists to query exactly one configured table, so a query touching zero
    (or any other) tables is never legitimate — allowlist by membership,
    not denylist by "nothing bad seen"."""
    tables = {t.name for t in parsed.find_all(exp.Table)}
    if tables != {allowed_table}:
        disallowed = tables - {allowed_table}
        if disallowed:
            return f"Query references table(s) not available to this tool: {', '.join(sorted(disallowed))}"
        return f"Query must reference the '{allowed_table}' table."
    return None


def _where_conjuncts(parsed: exp.Expression) -> list[exp.Expression]:
    """The WHERE clause's top-level AND-connected conditions — deliberately
    does NOT descend into OR branches, since a predicate hidden behind an OR
    doesn't actually constrain the result set the way a real filter would
    (e.g. `WHERE gfcid = 'x' OR 1=1` must not count as "filtered by gfcid")."""
    where = parsed.args.get("where")
    if where is None:
        return []
    condition = where.this
    if isinstance(condition, exp.And):
        return list(condition.flatten())
    return [condition]


def has_literal_equality(parsed: exp.Expression, column: str) -> bool:
    """True if the query's WHERE clause has a top-level equality comparing
    `column` to a literal value — the check behind EXACT-mode access (the
    caller must already know the value, not discover it by browsing)."""
    column_lower = column.lower()
    for leaf in _where_conjuncts(parsed):
        if not isinstance(leaf, exp.EQ):
            continue
        left, right = leaf.this, leaf.expression
        for a, b in ((left, right), (right, left)):
            if isinstance(a, exp.Column) and a.name.lower() == column_lower and isinstance(b, exp.Literal):
                return True
    return False


def build_policy_condition(
    policy_field_names: dict[str, str], args: dict[str, Any]
) -> tuple[exp.Expression | None, str | None]:
    """Builds the RLS predicate from the reserved keys
    `before_tool_callback`/`policy_engine.py` already injected into `args`
    (see `agent_runtime/builder.py` — unmodified by this tool). Values are
    always rendered through `exp.Literal`, never string-concatenated, even
    though they come from a trusted server-side lookup rather than the LLM.
    Returns `(condition, None)`, `(None, deny_reason)`, or `(None, None)`
    when no predicate is needed (GLOBAL) or enforcement happens elsewhere
    (EXACT — see `has_literal_equality`)."""
    mode = args.get("_policy_mode")
    if mode in (None, "GLOBAL"):
        return None, None

    if mode == "ATTRIBUTE_SCOPED":
        field = policy_field_names.get("attribute")
        if not field:
            return None, "This tool has no attribute column configured for its access policy."
        values = args.get("_attr_values") or []
        return exp.In(this=exp.column(field), expressions=[exp.Literal.string(str(v)) for v in values]), None

    if mode == "ID_SCOPED":
        field = policy_field_names.get("id")
        if not field:
            return None, "This tool has no id column configured for its access policy."
        values = args.get("_id_values") or []
        return exp.In(this=exp.column(field), expressions=[exp.Literal.string(str(v)) for v in values]), None

    if mode == "EXACT":
        return None, None  # enforced post-parse by has_literal_equality, not injected

    # Unrecognized mode: fail closed, never open.
    return exp.EQ(this=exp.Literal.number(1), expression=exp.Literal.number(0)), None


class DataQueryTool(ConfigDrivenTool):
    def __init__(self, *, name: str, description: str, input_schema: dict, config: dict) -> None:
        super().__init__(name=name, description=description, input_schema=input_schema)
        self._config = config

    async def run_async(self, *, args: dict[str, Any], tool_context) -> Any:
        entity = self._config["entity"]
        connection = entity["connection"]
        source = entity["source"]
        max_limit = entity.get("max_limit", 100)
        policy_field_names = self._config.get("policy_field_names") or {}

        sql = args.get("sql", "")
        error = validate_single_select(sql)
        if error:
            return {"error": error}

        parsed = sqlglot.parse_one(sql, dialect="mysql")

        table = source.get("table")
        error = validate_single_table(parsed, table)
        if error:
            return {"error": error}

        if args.get("_policy_mode") == "EXACT":
            exact_field = policy_field_names.get("exact")
            if not exact_field or not has_literal_equality(parsed, exact_field):
                return {
                    "error": f"Your access level requires an exact '{exact_field or 'reference'}' filter in "
                    "the query's WHERE clause — no browsing or searching is permitted."
                }

        condition, deny_reason = build_policy_condition(policy_field_names, args)
        if deny_reason:
            return {"error": deny_reason}
        if condition is not None:
            parsed = parsed.where(condition, append=True)

        had_own_limit = parsed.args.get("limit") is not None
        if not had_own_limit:
            parsed = parsed.limit(max_limit)

        final_sql = parsed.sql(dialect="mysql")
        prefix = connection["connection_env_prefix"]

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
            return {"error": f"Query failed: {exc}"}
        execution_ms = (time.perf_counter() - start) * 1000

        data = [to_json_safe(r) for r in rows]
        # Same {row_count, columns, data, truncated, execution_ms} contract
        # mcp_servers/slide_reporting_server.py's sql_execution_tool already
        # returns — makes this tool a drop-in data source for
        # chart_planner_tool/slide_builder_tool (see reporting_specialist),
        # not just a same-shaped-by-coincidence sibling.
        return {
            "row_count": len(data),
            "columns": list(data[0].keys()) if data else [],
            "data": data,
            "truncated": (not had_own_limit) and len(data) >= max_limit,
            "execution_ms": round(execution_ms, 2),
        }
