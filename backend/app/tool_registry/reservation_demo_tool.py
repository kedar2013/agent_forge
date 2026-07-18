"""Worked example proving saga/compensation actually fires end-to-end — see
app/reliability/compensation.py's module docstring for what it's
demonstrating, and scripts/seed_reliability_demo.py for how the three modes
below are wired into one small demo agent. Not a real inventory system: a
tiny demo table (`reliability_demo_inventory`) exists purely so 'reserve'
has something real to decrement and 'release' something real to increment
back.

One class, three modes (config: {"mode": "reserve"|"release"|"confirm"}) —
the smallest possible worked example rather than three separate tool
classes:
  - reserve: decrements `available` for `item` by `quantity` (fails,
    returning a soft {"error": ...}, if not enough available). This is the
    step compensation rolls back.
  - release: increments `available` back for `item` by `quantity`. This IS
    the compensation action — referenced by the reserve tool's own
    config.compensation_tool_id, never called by the model directly.
  - confirm: a deliberately fragile "finalize the order" step. RAISES (not a
    soft error dict — the turn needs to actually fail, not just have the
    model narrate a failure) when args["order_id"] == "FORCE_FAIL", the
    demo's trigger for a turn-ending failure that proves reserve's
    compensation (release) actually fires.
"""

import os
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from app.config import get_settings
from app.tool_registry.base import ConfigDrivenTool

_engine_cache: dict[str, AsyncEngine] = {}

# This tool's engine is a plain create_async_engine(connection_url) — unlike
# app/db.py's own engine, it never sets search_path (see sql_tool.py/
# retrieval_tool.py, which use the same bare-engine pattern and rely on a
# schema-qualified table name in their own config instead), so the demo
# table's schema must be spelled out explicitly here.
_TABLE = f"{get_settings().db_schema}.reliability_demo_inventory"


def _get_engine(connection_url: str) -> AsyncEngine:
    if connection_url not in _engine_cache:
        _engine_cache[connection_url] = create_async_engine(connection_url, pool_pre_ping=True)
    return _engine_cache[connection_url]


class ReservationDemoTool(ConfigDrivenTool):
    """`config` shape: {"mode": "reserve"|"release"|"confirm", "connection_env": "DATABASE_URL"}"""

    def __init__(self, *, name: str, description: str, input_schema: dict, config: dict) -> None:
        super().__init__(name=name, description=description, input_schema=input_schema)
        self._config = config

    async def run_async(self, *, args: dict[str, Any], tool_context) -> Any:
        mode = self._config["mode"]
        item = args["item"]

        if mode == "confirm":
            if args.get("order_id") == "FORCE_FAIL":
                raise RuntimeError(
                    "Payment authorization declined for order FORCE_FAIL — the "
                    "reliability demo's deliberate failure trigger."
                )
            return {"item": item, "confirmed": True, "order_id": args.get("order_id")}

        quantity = int(args.get("quantity", 1))
        connection_url = os.environ[self._config.get("connection_env", "DATABASE_URL")]
        engine = _get_engine(connection_url)

        if mode == "reserve":
            async with engine.begin() as conn:
                result = await conn.execute(
                    text(
                        f"UPDATE {_TABLE} SET available = available - :qty "
                        "WHERE item = :item AND available >= :qty RETURNING available"
                    ),
                    {"item": item, "qty": quantity},
                )
                row = result.first()
            if row is None:
                return {"error": f"Insufficient inventory for '{item}'"}
            return {"item": item, "reserved": quantity, "remaining": row[0]}

        if mode == "release":
            async with engine.begin() as conn:
                result = await conn.execute(
                    text(
                        f"UPDATE {_TABLE} SET available = available + :qty "
                        "WHERE item = :item RETURNING available"
                    ),
                    {"item": item, "qty": quantity},
                )
                row = result.first()
            return {"item": item, "released": quantity, "remaining": row[0] if row else None}

        raise ValueError(f"Unknown reservation_demo_tool mode: {mode!r}")
