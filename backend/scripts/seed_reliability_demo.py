"""Seeds `reliability_demo_agent` — the worked example proving saga/
compensation actually fires end-to-end (see app/reliability/compensation.py's
module docstring), not just structurally wired up. Three tools
(app/tool_registry/reservation_demo_tool.py, one class/three modes):

  - reserve_widgets: decrements a tiny demo inventory table. Its own
    config.compensation_tool_id points at release_widgets.
  - release_widgets: increments the inventory back — the compensation
    action itself. NOT attached to the agent (the model never calls it
    directly; only the compensation walk in app/reliability/compensation.py
    invokes it, after a turn fails).
  - confirm_order: a deliberately fragile "finalize" step. Raises when
    called with order_id="FORCE_FAIL", the demo's trigger for a turn-ending
    failure.

The agent has `model_config.durable_execution.enabled = true` — durable
execution (and therefore compensation) is opt-in per agent, off by default
for every other agent on the platform.

Try it once seeded and published (via /playground or /agents/{id}/invoke):
  "Reserve 2 widgets and confirm the order with order_id FORCE_FAIL"
-> reserve_widgets succeeds (available: 5 -> 3), confirm_order raises, the
   turn ends in error, and reserve_widgets' compensation (release_widgets)
   fires automatically — check available is back to 5 and
   tool_call_log.compensation_status = 'compensated' for the reserve call.

Idempotent: `--reset` undoes only what this script created (SEED_MARKER).

Usage (from backend/, so `app.*` imports resolve):
    python scripts/seed_reliability_demo.py [--reset]
"""

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import delete, select  # noqa: E402

from app.agent_runtime.cache import agent_cache  # noqa: E402
from app.db import async_session_factory  # noqa: E402
from app.logging_hooks import write_audit_log  # noqa: E402
from app.models.agents import Agent, AgentTool, AgentVersion  # noqa: E402
from app.models.logs import ConfigAuditLog  # noqa: E402
from app.models.reliability_demo import ReliabilityDemoInventory  # noqa: E402
from app.models.tools import Tool  # noqa: E402
from app.models.workspaces import DEFAULT_WORKSPACE_ID  # noqa: E402

SEED_MARKER = "reliability-demo-import"
MODEL_CONFIG = {"model": "gemini-3.5-flash", "temperature": 0.2, "durable_execution": {"enabled": True}}

AGENT_NAME = "reliability_demo_agent"
AGENT_DESCRIPTION = (
    "Worked example for durable execution's saga/compensation: reserves demo "
    "inventory, then confirms an order — a failed confirmation automatically "
    "releases what was reserved."
)
AGENT_INSTRUCTION = """You help a customer reserve `widgets` from a small demo inventory
and then confirm their order.

1. Always call reserve_widgets FIRST, with the item and quantity the customer wants.
2. If reserve_widgets returns an error (insufficient inventory), tell the customer
   plainly and stop — do not call confirm_order.
3. If reserve succeeded, call confirm_order with the same item/quantity and whatever
   order_id the customer gave you (ask for one if they didn't give one).
4. If confirm_order fails, tell the customer their order could not be confirmed and
   that their reservation has been released — do not try to reserve or confirm again
   yourself."""

DEMO_ITEM = "widgets"
DEMO_STARTING_STOCK = 5

_ITEM_INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "item": {"type": "string", "description": f"Inventory item name, e.g. '{DEMO_ITEM}'."},
        "quantity": {"type": "integer", "description": "How many units."},
    },
    "required": ["item", "quantity"],
}


async def _get_agent(session, name: str) -> Agent | None:
    return await session.scalar(select(Agent).where(Agent.name == name))


async def reset(session) -> None:
    print("Resetting previously-seeded reliability_demo_agent...")
    agent = await _get_agent(session, AGENT_NAME)
    if agent is not None:
        await session.execute(delete(AgentTool).where(AgentTool.agent_id == agent.id))
        await session.execute(delete(AgentVersion).where(AgentVersion.agent_id == agent.id))
        await session.execute(delete(Agent).where(Agent.id == agent.id))
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

        existing = await _get_agent(session, AGENT_NAME)
        if existing is not None:
            print(f"'{AGENT_NAME}' already seeded. Use --reset to reseed.")
            return

        inventory_row = await session.get(ReliabilityDemoInventory, DEMO_ITEM)
        if inventory_row is None:
            session.add(ReliabilityDemoInventory(item=DEMO_ITEM, available=DEMO_STARTING_STOCK))
            await session.flush()

        release_tool = Tool(
            name="release_widgets",
            workspace_id=DEFAULT_WORKSPACE_ID,
            tool_type="reservation_demo_tool",
            description="Releases previously reserved demo inventory back to available stock.",
            config={"mode": "release", "connection_env": "DATABASE_URL"},
            input_schema=_ITEM_INPUT_SCHEMA,
            created_by=SEED_MARKER,
        )
        session.add(release_tool)
        await session.flush()  # need release_tool.id before reserve_tool's config can reference it

        reserve_tool = Tool(
            name="reserve_widgets",
            workspace_id=DEFAULT_WORKSPACE_ID,
            tool_type="reservation_demo_tool",
            description="Reserves demo inventory for an order (fails if insufficient stock).",
            config={
                "mode": "reserve",
                "connection_env": "DATABASE_URL",
                "compensation_tool_id": str(release_tool.id),
            },
            input_schema=_ITEM_INPUT_SCHEMA,
            created_by=SEED_MARKER,
        )
        confirm_tool = Tool(
            name="confirm_order",
            workspace_id=DEFAULT_WORKSPACE_ID,
            tool_type="reservation_demo_tool",
            description=(
                "Finalizes a reserved order. Deliberately fails for order_id='FORCE_FAIL' — "
                "this is the reliability demo's own failure trigger, not a real payment system."
            ),
            config={"mode": "confirm", "connection_env": "DATABASE_URL"},
            input_schema={
                "type": "object",
                "properties": {
                    "item": {"type": "string"},
                    "quantity": {"type": "integer"},
                    "order_id": {"type": "string"},
                },
                "required": ["item", "quantity", "order_id"],
            },
            created_by=SEED_MARKER,
        )
        session.add(reserve_tool)
        session.add(confirm_tool)
        await session.flush()

        agent = Agent(
            name=AGENT_NAME,
            workspace_id=DEFAULT_WORKSPACE_ID,
            description=AGENT_DESCRIPTION,
            base_instruction=AGENT_INSTRUCTION,
            model_config_json=MODEL_CONFIG,
            created_by=SEED_MARKER,
        )
        session.add(agent)
        await session.flush()

        # release_widgets is deliberately NOT attached — only the
        # compensation walk (app/reliability/compensation.py) ever calls it.
        session.add(AgentTool(agent_id=agent.id, tool_id=reserve_tool.id))
        session.add(AgentTool(agent_id=agent.id, tool_id=confirm_tool.id))
        await session.flush()

        snapshot = {
            "name": agent.name,
            "description": agent.description,
            "base_instruction": agent.base_instruction,
            "model_config": agent.model_config_json,
            "output_schema": agent.output_schema,
            "output_key": agent.output_key,
            "tools": [
                {"id": str(reserve_tool.id), "name": reserve_tool.name},
                {"id": str(confirm_tool.id), "name": confirm_tool.name},
            ],
            "skills": [],
            "sub_agents": [],
        }
        agent.current_version = 1
        agent.status = "published"
        session.add(AgentVersion(agent_id=agent.id, version=1, snapshot=snapshot, published_by=SEED_MARKER))
        await session.flush()
        agent_cache.invalidate(agent.id)

        await write_audit_log(
            session,
            entity_type="agent",
            entity_id=agent.id,
            action="publish",
            actor=SEED_MARKER,
            diff={"version": agent.current_version},
            workspace_id=DEFAULT_WORKSPACE_ID,
        )
        await session.commit()
        print(f"Created and published '{AGENT_NAME}' (durable_execution enabled) with demo inventory reset to "
              f"{DEMO_STARTING_STOCK} '{DEMO_ITEM}'.")


if __name__ == "__main__":
    asyncio.run(main())
