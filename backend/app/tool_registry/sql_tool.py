import os
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from app.tool_registry.base import ConfigDrivenTool
from app.tool_registry.serialize import to_json_safe

_engine_cache: dict[str, AsyncEngine] = {}


def _get_engine(connection_url: str) -> AsyncEngine:
    if connection_url not in _engine_cache:
        _engine_cache[connection_url] = create_async_engine(connection_url, pool_pre_ping=True)
    return _engine_cache[connection_url]


class SqlTool(ConfigDrivenTool):
    """Parameterized, allow-listed SQL query tool.

    `config` shape:
        {
          "connection_env": "AGENT_FORGE_READONLY_DB_URL",  # env var holding the DSN
          "query_template": "SELECT * FROM company WHERE industry = :industry LIMIT :limit"
        }

    The query structure is fixed at tool-creation time by whoever authored the
    tool row — this class only ever binds *parameter values* via SQLAlchemy's
    `text()` bindparams. The LLM-supplied `args` can never alter the query
    structure itself, which is what prevents injection through a crafted tool
    call.
    """

    def __init__(self, *, name: str, description: str, input_schema: dict, config: dict) -> None:
        super().__init__(name=name, description=description, input_schema=input_schema)
        self._config = config

    async def run_async(self, *, args: dict[str, Any], tool_context) -> Any:
        connection_url = os.environ[self._config["connection_env"]]
        engine = _get_engine(connection_url)
        query = text(self._config["query_template"])

        async with engine.connect() as conn:
            result = await conn.execute(query, args)
            rows = [to_json_safe(dict(row._mapping)) for row in result.fetchall()]

        return {"row_count": len(rows), "rows": rows}
