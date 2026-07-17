"""Pooled MySQL connection helper for the `sales_analytics` reporting
database, used by slide_reporting_server.py. Kept separate from
app/db.py (which is Postgres/asyncpg, for the main agent_forge app) since
this is a different database engine entirely, read by a standalone MCP
server subprocess that doesn't share the FastAPI process's config.

Reads SALES_DB_HOST/PORT/USER/PASSWORD/NAME from backend/.env directly
(path-independent of CWD, same pattern OUTPUT_DIR uses in
document_export_server.py) rather than through app/config.py.
"""

import os

import pymysql
from dbutils.pooled_db import PooledDB
from dotenv import load_dotenv

_ENV_PATH = os.path.join(os.path.dirname(__file__), "..", ".env")
load_dotenv(_ENV_PATH)
# google-genai (used directly by nl_to_sql_tool/chart_planner_tool for their
# own LLM calls) reads GOOGLE_API_KEY; app/config.py bridges the same way
# for the main FastAPI process, but this MCP server is a separate subprocess
# that doesn't share that process's env unless it inherited it at spawn time.
os.environ.setdefault("GOOGLE_API_KEY", os.environ.get("GEMINI_API_KEY", ""))

_POOL: PooledDB | None = None


def _get_pool() -> PooledDB:
    global _POOL
    if _POOL is None:
        _POOL = PooledDB(
            creator=pymysql,
            maxconnections=5,
            mincached=1,
            blocking=True,
            host=os.environ.get("SALES_DB_HOST", "localhost"),
            port=int(os.environ.get("SALES_DB_PORT", "3306")),
            user=os.environ.get("SALES_DB_USER", "root"),
            password=os.environ.get("SALES_DB_PASSWORD", ""),
            database=os.environ.get("SALES_DB_NAME", "sales_analytics"),
            cursorclass=pymysql.cursors.DictCursor,
            autocommit=True,
        )
    return _POOL


def get_connection():
    """A pooled, read-only-intent MySQL connection. Caller is responsible
    for closing it (returns it to the pool rather than actually disconnecting)."""
    return _get_pool().connection()
