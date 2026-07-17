"""Seeds a "Market Intelligence" agent family on top of the three new
free/no-key MCP servers (mcp_servers/stocks_server.py, crypto_server.py,
forex_metals_server.py): three specialist agents plus a root orchestrator
that routes to them, following the same pattern as seed_studybuddy_agents.py.

Idempotent: re-running without --reset is a no-op if already seeded
(identified by created_by/actor == 'market-data-import'). --reset deletes
everything this script previously created first.

Usage:
    python scripts/seed_market_agents.py [--reset]
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

SEED_MARKER = "market-data-import"
MODEL_CONFIG = {"model": "gemini-3.5-flash", "temperature": 0.2}

DISCLAIMER = (
    "You provide data and analysis, not investment advice. Never tell the user "
    "to buy/sell/hold, and if asked for a recommendation, clarify you can only "
    "surface data and trends, not personalized financial advice."
)

# tool_name -> (description, input_schema)
STOCK_TOOLS = {
    "search_stocks": (
        "Search for stock/ETF/index ticker symbols by company or fund name.",
        {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
    ),
    "get_stock_quote": (
        "Get the latest price and day-over-day change for a stock, ETF, or index.",
        {"type": "object", "properties": {"symbol": {"type": "string"}}, "required": ["symbol"]},
    ),
    "analyze_stock_performance": (
        "Analyze a stock/ETF/index's trailing returns and 52-week high/low.",
        {"type": "object", "properties": {"symbol": {"type": "string"}}, "required": ["symbol"]},
    ),
}

CRYPTO_TOOLS = {
    "search_coins": (
        "Search for a cryptocurrency's CoinGecko id by name or symbol.",
        {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
    ),
    "get_crypto_price": (
        "Get the current price, 24h change, market cap, and volume for a coin.",
        {
            "type": "object",
            "properties": {
                "coin_id": {"type": "string"},
                "vs_currency": {"type": "string", "default": "usd"},
            },
            "required": ["coin_id"],
        },
    ),
    "get_trending_coins": (
        "Get the top coins currently trending on CoinGecko.",
        {"type": "object", "properties": {}},
    ),
    "analyze_crypto_performance": (
        "Analyze a cryptocurrency's trailing returns (up to 1 year) and 52-week high/low.",
        {
            "type": "object",
            "properties": {
                "coin_id": {"type": "string"},
                "vs_currency": {"type": "string", "default": "usd"},
            },
            "required": ["coin_id"],
        },
    ),
}

FOREX_METALS_TOOLS = {
    "get_exchange_rate": (
        "Get the current exchange rate between two currencies.",
        {
            "type": "object",
            "properties": {"from_currency": {"type": "string"}, "to_currency": {"type": "string"}},
            "required": ["from_currency", "to_currency"],
        },
    ),
    "convert_currency": (
        "Convert an amount from one currency to another using today's rate.",
        {
            "type": "object",
            "properties": {
                "amount": {"type": "number"},
                "from_currency": {"type": "string"},
                "to_currency": {"type": "string"},
            },
            "required": ["amount", "from_currency", "to_currency"],
        },
    ),
    "analyze_currency_trend": (
        "Analyze a currency pair's trend over the past year plus its 52-week high/low.",
        {
            "type": "object",
            "properties": {"from_currency": {"type": "string"}, "to_currency": {"type": "string"}},
            "required": ["from_currency", "to_currency"],
        },
    ),
    "get_metal_price": (
        "Get the current spot price (USD/troy oz) for gold, silver, platinum, or palladium.",
        {"type": "object", "properties": {"metal": {"type": "string"}}, "required": ["metal"]},
    ),
}

SPECIALISTS = {
    "stock_market_analyst": dict(
        description="Looks up tickers, live quotes, and historical performance for stocks, ETFs, and indices worldwide.",
        server="mcp_servers/stocks_server.py",
        tool_specs=STOCK_TOOLS,
        instruction=f"""You are a stock market research specialist. You cover stocks, ETFs,
and indices worldwide (US, Indian NSE/BSE, and others).

1. If the user names a company/fund but you don't have a ticker symbol yet,
   call search_stocks to resolve it first.
2. For "what's X trading at" / "current price" questions, call get_stock_quote.
3. For "how has X performed" / "returns over the last year" questions, call
   analyze_stock_performance.
4. Always state the currency and exchange the price/analysis came from.
5. If a lookup fails, say so plainly and suggest the user try a more specific
   name or the exact ticker rather than guessing.

{DISCLAIMER}""",
    ),
    "crypto_analyst": dict(
        description="Looks up prices, trends, and market data for cryptocurrencies.",
        server="mcp_servers/crypto_server.py",
        tool_specs=CRYPTO_TOOLS,
        instruction=f"""You are a cryptocurrency market research specialist.

1. If the user names a coin but you don't have its CoinGecko id yet, call
   search_coins to resolve it first.
2. For "what's X trading at" / current price / market cap questions, call
   get_crypto_price.
3. For "how has X performed" / trend questions, call analyze_crypto_performance
   (note: limited to a 1-year lookback on the free data tier — say so if asked
   for longer history).
4. For "what's hot right now" / trending questions, call get_trending_coins.
5. Default to USD unless the user names another currency.

{DISCLAIMER}""",
    ),
    "forex_metals_analyst": dict(
        description="Looks up currency exchange rates, conversions, and precious metals spot prices.",
        server="mcp_servers/forex_metals_server.py",
        tool_specs=FOREX_METALS_TOOLS,
        instruction=f"""You are a foreign exchange and precious metals specialist.

1. For "what's the rate" questions, call get_exchange_rate.
2. For "convert N of currency A to currency B" questions, call convert_currency.
3. For "how has USD/INR trended" questions, call analyze_currency_trend.
4. For gold/silver/platinum/palladium spot price questions, call get_metal_price.
5. Use ISO currency codes (USD, INR, EUR, ...); if the user gives a currency
   name instead of a code, translate it yourself before calling a tool.

{DISCLAIMER}""",
    ),
}

ORCHESTRATOR_INSTRUCTION = """You are the Market Intelligence orchestrator. You never
answer market-data questions yourself — you always transfer to the right specialist:

- stock_market_analyst: stocks, ETFs, indices (tickers, quotes, historical returns).
- crypto_analyst: cryptocurrencies (prices, trends, what's trending).
- forex_metals_analyst: currency exchange rates/conversion, gold/silver/platinum/palladium prices.

Pick exactly one specialist per message and transfer to it. If a request spans
more than one domain (e.g. "compare gold to Bitcoin this year"), transfer to
the first specialist, let it answer, then transfer to the second for the rest.
If the request is ambiguous, ask a brief clarifying question yourself instead
of transferring."""


async def reset(session) -> None:
    print("Resetting previously-seeded market-data agents...")
    agent_ids = (
        (await session.execute(select(Agent.id).where(Agent.created_by == SEED_MARKER))).scalars().all()
    )
    if agent_ids:
        invocation_ids = (
            (await session.execute(select(InvocationLog.id).where(InvocationLog.agent_id.in_(agent_ids))))
            .scalars()
            .all()
        )
        if invocation_ids:
            await session.execute(delete(ToolCallLog).where(ToolCallLog.invocation_id.in_(invocation_ids)))
            await session.execute(delete(InvocationLog).where(InvocationLog.id.in_(invocation_ids)))
        await session.execute(delete(AgentSubagent).where(AgentSubagent.parent_agent_id.in_(agent_ids)))
        await session.execute(delete(AgentSubagent).where(AgentSubagent.child_agent_id.in_(agent_ids)))
        await session.execute(delete(AgentTool).where(AgentTool.agent_id.in_(agent_ids)))
        await session.execute(delete(AgentVersion).where(AgentVersion.agent_id.in_(agent_ids)))
        await session.execute(delete(Agent).where(Agent.id.in_(agent_ids)))
    await session.execute(delete(ConfigAuditLog).where(ConfigAuditLog.actor == SEED_MARKER))
    await session.execute(delete(Tool).where(Tool.created_by == SEED_MARKER))
    await session.commit()


def _publish_snapshot(agent: Agent, tools: list[Tool], sub_agents: list[Agent]) -> dict:
    return {
        "name": agent.name,
        "description": agent.description,
        "base_instruction": agent.base_instruction,
        "model_config": agent.model_config_json,
        "output_schema": agent.output_schema,
        "output_key": agent.output_key,
        "tools": [{"id": str(t.id), "name": t.name} for t in tools],
        "skills": [],
        "sub_agents": [{"id": str(a.id), "name": a.name} for a in sub_agents],
    }


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reset", action="store_true")
    args = parser.parse_args()

    async with async_session_factory() as session:
        if args.reset:
            await reset(session)

        existing = (
            (await session.execute(select(Agent).where(Agent.created_by == SEED_MARKER))).scalars().all()
        )
        if existing:
            print(f"Market-data agents already seeded ({len(existing)} found). Use --reset to reseed.")
            return

        specialist_rows: dict[str, Agent] = {}
        for name, spec in SPECIALISTS.items():
            tool_rows = []
            for tool_name, (description, input_schema) in spec["tool_specs"].items():
                tool = Tool(
                    name=tool_name,
                    workspace_id=DEFAULT_WORKSPACE_ID,
                    tool_type="mcp_tool",
                    description=description,
                    config={
                        "transport": "stdio",
                        "command": "python",
                        "args": [spec["server"]],
                        "tool_name": tool_name,
                    },
                    input_schema=input_schema,
                    created_by=SEED_MARKER,
                )
                session.add(tool)
                tool_rows.append(tool)
            await session.flush()

            agent = Agent(
                name=name,
                workspace_id=DEFAULT_WORKSPACE_ID,
                description=spec["description"],
                base_instruction=spec["instruction"],
                model_config_json=MODEL_CONFIG,
                created_by=SEED_MARKER,
            )
            session.add(agent)
            await session.flush()

            for tool in tool_rows:
                session.add(AgentTool(agent_id=agent.id, tool_id=tool.id))
            await session.flush()

            snapshot = _publish_snapshot(agent, tool_rows, [])
            session.add(AgentVersion(agent_id=agent.id, version=1, snapshot=snapshot, published_by=SEED_MARKER))
            agent.status = "published"
            agent.current_version = 1
            await write_audit_log(
                session, entity_type="agent", entity_id=agent.id, action="publish", actor=SEED_MARKER,
                diff={"version": 1}, workspace_id=DEFAULT_WORKSPACE_ID,
            )
            specialist_rows[name] = agent
            print(f"Created specialist '{name}' with {len(tool_rows)} tools.")

        orchestrator = Agent(
            name="market_intelligence_orchestrator",
            workspace_id=DEFAULT_WORKSPACE_ID,
            description="Routes market-data questions to the right specialist: stocks, crypto, or forex/metals.",
            base_instruction=ORCHESTRATOR_INSTRUCTION,
            model_config_json=MODEL_CONFIG,
            created_by=SEED_MARKER,
        )
        session.add(orchestrator)
        await session.flush()

        for child in specialist_rows.values():
            session.add(AgentSubagent(parent_agent_id=orchestrator.id, child_agent_id=child.id))
        await session.flush()

        snapshot = _publish_snapshot(orchestrator, [], list(specialist_rows.values()))
        session.add(AgentVersion(agent_id=orchestrator.id, version=1, snapshot=snapshot, published_by=SEED_MARKER))
        orchestrator.status = "published"
        orchestrator.current_version = 1
        await write_audit_log(
            session, entity_type="agent", entity_id=orchestrator.id, action="publish", actor=SEED_MARKER,
            diff={"version": 1}, workspace_id=DEFAULT_WORKSPACE_ID,
        )

        await session.commit()
        print("Created orchestrator 'market_intelligence_orchestrator' with 3 sub-agents.")


if __name__ == "__main__":
    asyncio.run(main())
