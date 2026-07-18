"""A generic, config-driven, read-oriented MySQL query tool — the MySQL
sibling of `sql_tool.py`/`mongo_tool.py`, built on `pymysql` + a pooled
connection (sync driver, run in a worker thread) rather than an async
SQLAlchemy engine, matching the MySQL access pattern already proven in this
repo (`mcp_servers/_db.py`, used by slide_reporting_server.py) instead of
adding a new async MySQL driver dependency.

`config` shape:
    {
      "connection_env_prefix": "CREDIT_FACILITY_MYSQL",  # reads {PREFIX}_HOST/_PORT/_USER/_PASSWORD/_DATABASE
      "query": "SELECT ... WHERE (%(company_id)s IS NULL OR company_id = %(company_id)s) AND ...",
      "optional_scalar_args": ["company_id"],   # arg may be omitted -> bound as None; pair with "(%(x)s IS NULL OR x = %(x)s)" in the query
      "optional_list_args": ["load_ids"],       # arg may be omitted/empty -> query gets "has_<name>" (0/1) plus a safe non-empty
                                                 # dummy tuple for <name> itself, since MySQL rejects "col IN ()" on an empty tuple
                                                 # (confirmed empirically) — pair with "(%(has_x)s = 0 OR x IN %(x)s)"
      "like_wrap_args": ["name_query"],         # wraps the LLM-supplied value in "%...%" for a LIKE clause
      "max_rows": 50
    }

Just like `SqlTool`, the query *structure* (which table, which columns, which
predicates) is fixed at tool-authoring time — this class only ever binds
*values* via pymysql's native `%(name)s` parameterization (which also safely
handles list-valued params for `IN` clauses), so the LLM can't alter the
query shape. Row-level security is layered on top the same generic way as
every other tool type here: whatever reserved keys a `before_tool_callback`-
resolved `AccessPolicy` merged into `args` (see `policy_engine.py` and
`agent_runtime/builder.py`) just become additional bound parameters — the
query's own fixed WHERE clause is what actually enforces them.
"""

import asyncio
import os
from typing import Any

import pymysql
from dbutils.pooled_db import PooledDB
from dotenv import load_dotenv

from app.reliability.resilient_call import resilient_call
from app.tool_registry.base import ConfigDrivenTool
from app.tool_registry.serialize import to_json_safe

# app/config.py's pydantic Settings only bridges a couple of specific keys
# into os.environ — a {prefix}_HOST/_PORT/_USER/_PASSWORD/_DATABASE block
# for some arbitrary domain's connection_env_prefix was never one of them,
# so load .env directly (idempotent, never overrides a real env var already
# set), same pattern as mcp_servers/_db.py.
load_dotenv(os.path.join(os.path.dirname(__file__), "..", "..", ".env"))

_pool_cache: dict[str, PooledDB] = {}

# Never a real id/level in seeded data — a syntactically-safe stand-in for
# an empty IN-list, since `col IN ()` is a MySQL syntax error but `col IN
# ('__none__',)` is always well-formed and simply matches nothing.
_EMPTY_IN_PLACEHOLDER = "__none__"


def _get_pool(prefix: str) -> PooledDB:
    if prefix not in _pool_cache:
        _pool_cache[prefix] = PooledDB(
            creator=pymysql,
            maxconnections=5,
            mincached=1,
            blocking=True,
            host=os.environ.get(f"{prefix}_HOST", "localhost"),
            port=int(os.environ.get(f"{prefix}_PORT", "3306")),
            user=os.environ.get(f"{prefix}_USER", "root"),
            password=os.environ.get(f"{prefix}_PASSWORD", ""),
            database=os.environ[f"{prefix}_DATABASE"],
            cursorclass=pymysql.cursors.DictCursor,
            autocommit=True,
        )
    return _pool_cache[prefix]


class MySQLQueryTool(ConfigDrivenTool):
    def __init__(self, *, name: str, description: str, input_schema: dict, config: dict) -> None:
        super().__init__(name=name, description=description, input_schema=input_schema)
        self._config = config

    async def run_async(self, *, args: dict[str, Any], tool_context) -> Any:
        params = dict(args)
        for name in self._config.get("like_wrap_args", []):
            if params.get(name):
                params[name] = f"%{params[name]}%"
        for name in self._config.get("optional_scalar_args", []):
            params.setdefault(name, None)
        for name in self._config.get("optional_list_args", []):
            values = params.get(name)
            params[f"has_{name}"] = 1 if values else 0
            params[name] = tuple(values) if values else (_EMPTY_IN_PLACEHOLDER,)
        # Any reserved policy key that names an IN-list (e.g. _allowed_levels,
        # _allowed_company_ids) needs the same empty-tuple guard — these are
        # always present (the policy engine fills every branch's keys so the
        # query's fixed OR-chain stays valid regardless of which mode is
        # active), but an empty coverage list must still round-trip safely.
        for key, value in list(params.items()):
            if isinstance(value, (list, tuple)):
                params[key] = tuple(value) if value else (_EMPTY_IN_PLACEHOLDER,)

        max_rows = self._config.get("max_rows", 50)
        prefix = self._config["connection_env_prefix"]
        query = self._config["query"]

        def _run_query() -> list[dict]:
            pool = _get_pool(prefix)
            conn = pool.connection()
            try:
                with conn.cursor() as cur:
                    cur.execute(query, params)
                    return list(cur.fetchmany(max_rows))
            finally:
                conn.close()

        try:
            rows = await resilient_call(f"mysql_tool:{self.name}", lambda: asyncio.to_thread(_run_query))
        except Exception as exc:
            return {"error": f"Query failed: {exc}"}

        return {"row_count": len(rows), "rows": [to_json_safe(r) for r in rows]}
