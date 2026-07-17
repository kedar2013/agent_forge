"""A real MCP server for cryptocurrency market data — CoinGecko's free public
API (no API key required for these endpoints). Runs over stdio, spawned as a
subprocess by Eärendil's mcp_tool (StdioConnectionParams), following the same
pattern as mutual_fund_server.py.

Like analyze_fund_performance there, `analyze_crypto_performance` computes
real trailing-return figures from daily price history rather than dumping
raw series on the model.

Run standalone for a smoke test:
    python mcp_servers/crypto_server.py
"""

from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP

from _http_retry import get_with_retry

mcp = FastMCP("crypto")

BASE_URL = "https://api.coingecko.com/api/v3"


async def _get(path: str, params: dict[str, Any]) -> Any | None:
    async with httpx.AsyncClient() as client:
        try:
            response = await get_with_retry(client, f"{BASE_URL}{path}", params=params, timeout=30.0)
            response.raise_for_status()
            return response.json()
        except Exception:
            return None


@mcp.tool()
async def search_coins(query: str) -> str:
    """Search for a cryptocurrency's CoinGecko id by name or symbol.

    Args:
        query: A coin name or ticker — e.g. "bitcoin", "ETH", "solana".
    """
    data = await _get("/search", {"query": query})
    if data is None:
        return f"Search failed for '{query}'."

    coins = data.get("coins", [])
    if not coins:
        return f"No coins found matching '{query}'."

    lines = [f"{len(coins[:15])} matches for '{query}':"]
    for c in coins[:15]:
        lines.append(f"{c['id']}: {c['name']} ({c['symbol'].upper()}) - market cap rank {c.get('market_cap_rank', 'n/a')}")
    return "\n".join(lines)


@mcp.tool()
async def get_crypto_price(coin_id: str, vs_currency: str = "usd") -> str:
    """Get the current price, 24h change, market cap, and volume for a coin.

    Args:
        coin_id: The CoinGecko coin id (find it via search_coins first) — e.g. "bitcoin".
        vs_currency: Currency to quote in, e.g. "usd", "inr", "eur". Defaults to "usd".
    """
    data = await _get(
        "/simple/price",
        {
            "ids": coin_id,
            "vs_currencies": vs_currency,
            "include_24hr_change": "true",
            "include_market_cap": "true",
            "include_24hr_vol": "true",
        },
    )
    if not data or coin_id not in data:
        return f"Couldn't fetch price for '{coin_id}'. Check the id via search_coins first."

    info = data[coin_id]
    vs = vs_currency.lower()
    price = info.get(vs)
    change = info.get(f"{vs}_24h_change")
    market_cap = info.get(f"{vs}_market_cap")
    volume = info.get(f"{vs}_24h_vol")

    if price is None:
        return f"No price data for '{coin_id}' in {vs_currency.upper()}."

    lines = [f"{coin_id.capitalize()} price: {price:,.4f} {vs_currency.upper()}"]
    if change is not None:
        lines.append(f"24h change: {change:+.2f}%")
    if market_cap:
        lines.append(f"Market cap: {market_cap:,.0f} {vs_currency.upper()}")
    if volume:
        lines.append(f"24h volume: {volume:,.0f} {vs_currency.upper()}")
    return "\n".join(lines)


@mcp.tool()
async def get_trending_coins() -> str:
    """Get the top coins currently trending on CoinGecko (by search popularity)."""
    data = await _get("/search/trending", {})
    if data is None:
        return "Couldn't fetch trending coins right now."

    items = data.get("coins", [])
    if not items:
        return "No trending data available."

    lines = ["Currently trending coins:"]
    for i, item in enumerate(items, start=1):
        c = item["item"]
        lines.append(f"{i}. {c['name']} ({c['symbol'].upper()}) - market cap rank {c.get('market_cap_rank', 'n/a')}")
    return "\n".join(lines)


@mcp.tool()
async def analyze_crypto_performance(coin_id: str, vs_currency: str = "usd") -> str:
    """Analyze a cryptocurrency's performance over the past year: trailing
    returns at 1/3/6/12 months back, and its 52-week high/low. Use this for
    "how has this coin performed" or "what are the returns on X" questions -
    it computes real figures rather than dumping raw price history.

    Note: limited to a 1-year lookback since CoinGecko's free tier does not
    allow longer daily history without a paid API key.

    Args:
        coin_id: The CoinGecko coin id (find it via search_coins first) - e.g. "bitcoin".
        vs_currency: Currency to quote in, e.g. "usd", "inr". Defaults to "usd".
    """
    data = await _get(f"/coins/{coin_id}/market_chart", {"vs_currency": vs_currency, "days": 365})
    if data is None or not data.get("prices"):
        return f"Couldn't fetch history for '{coin_id}'. Check the id via search_coins first."

    rows = [
        (datetime.fromtimestamp(ts / 1000, tz=timezone.utc), price) for ts, price in data["prices"]
    ]
    latest_date, latest_price = rows[-1]

    periods = {"1 month": 30, "3 months": 91, "6 months": 182, "1 year": 365}

    lines = [
        f"{coin_id.capitalize()} - latest price: {latest_price:,.4f} {vs_currency.upper()} (as of {latest_date.date()})",
        "",
        "Trailing returns:",
    ]
    for label, days in periods.items():
        target = latest_date - timedelta(days=days)
        past_price = None
        for date, price in rows:
            if date <= target:
                past_price = price
            else:
                break
        if past_price is None or past_price <= 0:
            lines.append(f"  {label}: not enough history")
            continue
        total_return = (latest_price / past_price) - 1
        lines.append(f"  {label}: {total_return * 100:+.2f}%")

    all_prices = [p for _, p in rows]
    lines.append("")
    lines.append(f"52-week high: {max(all_prices):,.4f} {vs_currency.upper()}")
    lines.append(f"52-week low: {min(all_prices):,.4f} {vs_currency.upper()}")

    return "\n".join(lines)


if __name__ == "__main__":
    mcp.run(transport="stdio")
