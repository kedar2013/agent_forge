"""The Mongo analogue of `sql_tool.py`: a parameterized, structurally-fixed
read-only query tool for MongoDB.

`config` shape:
    {
      "connection_env": "CREDIT_FACILITY_MONGO_URI",  # env var holding the Mongo URI
      "database": "credit_facility",
      "collection": "company_facility_monthly",
      "filter_template": {"company_id": "{{company_id}}", "load_id": {"$in": "{{load_ids}}"}},
      "projection": {"_id": 0},                        # optional, defaults to {"_id": 0}
      "sort": [["load_id", -1]],                        # optional, list of [field, direction] pairs
      "limit": 12,                                       # int, or "{{arg_name}}" to let the LLM bind it
      "max_limit": 24                                    # hard cap regardless of what "limit" resolves to
    }

Just like `SqlTool`, the query *structure* (which collection, which fields
are filtered on, which operators are used) is fixed at tool-authoring time.
A `"{{name}}"` leaf anywhere in `filter_template` (or in `limit`) is replaced
with `args["name"]` verbatim — the LLM can only ever supply *values*, never
new keys/operators, so it can't smuggle in a different query shape. A
`filter_template` entry that resolves to `None` (the arg was omitted) is
dropped from the query entirely, which is what makes optional filter args
work.

Row-level security is layered on top, not baked into this class: if the
`before_tool_callback` registered in `agent_runtime/builder.py` injected a
trusted `_enforced_filter` into `args` (see `policy_engine.py`), it is
ANDed onto the bound filter unconditionally, after all LLM-controlled
binding is done — so a compromised or confused LLM call still can't read
outside the caller's authorized scope.
"""

import os
from typing import Any

from motor.motor_asyncio import AsyncIOMotorClient

from app.reliability.resilient_call import resilient_call
from app.tool_registry._templating import UNSET, bind_template
from app.tool_registry.base import ConfigDrivenTool
from app.tool_registry.serialize import to_json_safe

_client_cache: dict[str, AsyncIOMotorClient] = {}


def _get_client(connection_url: str) -> AsyncIOMotorClient:
    if connection_url not in _client_cache:
        _client_cache[connection_url] = AsyncIOMotorClient(connection_url)
    return _client_cache[connection_url]


class MongoQueryTool(ConfigDrivenTool):
    def __init__(self, *, name: str, description: str, input_schema: dict, config: dict) -> None:
        super().__init__(name=name, description=description, input_schema=input_schema)
        self._config = config

    async def run_async(self, *, args: dict[str, Any], tool_context) -> Any:
        connection_url = os.environ[self._config["connection_env"]]
        client = _get_client(connection_url)
        collection = client[self._config["database"]][self._config["collection"]]

        bound_filter = bind_template(self._config.get("filter_template", {}), args)
        enforced_filter = args.get("_enforced_filter") or {}
        if enforced_filter:
            mongo_filter = {"$and": [bound_filter, enforced_filter]} if bound_filter else enforced_filter
        else:
            mongo_filter = bound_filter

        projection = self._config.get("projection", {"_id": 0})

        limit_config = self._config.get("limit", 50)
        limit = bind_template(limit_config, args) if isinstance(limit_config, str) else limit_config
        if limit is UNSET or not isinstance(limit, int):
            limit = self._config.get("max_limit", 50)
        limit = min(int(limit), self._config.get("max_limit", 100))

        async def _run_query() -> list[dict]:
            cursor = collection.find(mongo_filter, projection)
            sort = self._config.get("sort")
            if sort:
                cursor = cursor.sort([tuple(pair) for pair in sort])
            cursor = cursor.limit(limit)
            return [to_json_safe(doc) async for doc in cursor]

        rows = await resilient_call(f"mongo_tool:{self.name}", _run_query)
        return {"row_count": len(rows), "rows": rows}
