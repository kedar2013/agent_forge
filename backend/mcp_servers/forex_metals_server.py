"""A real MCP server for currency exchange rates and precious metals spot
prices — frankfurter.app (ECB reference rates, free, no API key) and
gold-api.com (free, no API key). Runs over stdio, spawned as a subprocess by
Agent Forge's mcp_tool (StdioConnectionParams), following the same pattern as
mutual_fund_server.py.

Run standalone for a smoke test:
    python mcp_servers/forex_metals_server.py
"""

from datetime import date, timedelta
from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP

from _http_retry import get_with_retry

mcp = FastMCP("forex-metals")

FX_BASE_URL = "https://api.frankfurter.app"
METAL_BASE_URL = "https://api.gold-api.com/price"

_METAL_SYMBOLS = {
    "gold": "XAU",
    "silver": "XAG",
    "platinum": "XPT",
    "palladium": "XPD",
}


async def _fx_get(path: str, params: dict[str, Any]) -> dict[str, Any] | None:
    async with httpx.AsyncClient(follow_redirects=True) as client:
        try:
            response = await get_with_retry(client, f"{FX_BASE_URL}{path}", params=params, timeout=30.0)
            response.raise_for_status()
            return response.json()
        except Exception:
            return None


@mcp.tool()
async def get_exchange_rate(from_currency: str, to_currency: str) -> str:
    """Get the current exchange rate between two currencies.

    Args:
        from_currency: ISO currency code to convert from, e.g. "USD".
        to_currency: ISO currency code to convert to, e.g. "INR".
    """
    from_currency, to_currency = from_currency.upper(), to_currency.upper()
    data = await _fx_get("/latest", {"from": from_currency, "to": to_currency})
    if data is None or to_currency not in data.get("rates", {}):
        return f"Couldn't fetch exchange rate for {from_currency} -> {to_currency}. Check the currency codes."

    rate = data["rates"][to_currency]
    return f"1 {from_currency} = {rate:,.4f} {to_currency} (as of {data['date']})"


@mcp.tool()
async def convert_currency(amount: float, from_currency: str, to_currency: str) -> str:
    """Convert an amount from one currency to another using today's rate.

    Args:
        amount: The amount to convert.
        from_currency: ISO currency code to convert from, e.g. "USD".
        to_currency: ISO currency code to convert to, e.g. "INR".
    """
    from_currency, to_currency = from_currency.upper(), to_currency.upper()
    data = await _fx_get("/latest", {"amount": amount, "from": from_currency, "to": to_currency})
    if data is None or to_currency not in data.get("rates", {}):
        return f"Couldn't convert {from_currency} -> {to_currency}. Check the currency codes."

    converted = data["rates"][to_currency]
    return f"{amount:,.2f} {from_currency} = {converted:,.2f} {to_currency} (as of {data['date']})"


@mcp.tool()
async def analyze_currency_trend(from_currency: str, to_currency: str) -> str:
    """Analyze how a currency pair has trended over the past year: rate
    changes at 1/3/6/12 months back plus the 52-week high/low, computed from
    real historical ECB reference rates.

    Args:
        from_currency: ISO currency code to convert from, e.g. "USD".
        to_currency: ISO currency code to convert to, e.g. "INR".
    """
    from_currency, to_currency = from_currency.upper(), to_currency.upper()
    today = date.today()
    start = today - timedelta(days=370)
    data = await _fx_get(f"/{start.isoformat()}..{today.isoformat()}", {"from": from_currency, "to": to_currency})
    if data is None or not data.get("rates"):
        return f"Couldn't fetch history for {from_currency} -> {to_currency}. Check the currency codes."

    rows = sorted((date.fromisoformat(d), rates[to_currency]) for d, rates in data["rates"].items() if to_currency in rates)
    if not rows:
        return f"No historical rate data for {from_currency} -> {to_currency}."

    latest_date, latest_rate = rows[-1]
    periods = {"1 month": 30, "3 months": 91, "6 months": 182, "1 year": 365}

    lines = [
        f"{from_currency} -> {to_currency}: {latest_rate:,.4f} (as of {latest_date})",
        "",
        "Trend:",
    ]
    for label, days in periods.items():
        target = latest_date - timedelta(days=days)
        past_rate = None
        for d, r in rows:
            if d <= target:
                past_rate = r
            else:
                break
        if past_rate is None or past_rate <= 0:
            lines.append(f"  {label}: not enough history")
            continue
        change = (latest_rate / past_rate) - 1
        lines.append(f"  {label}: {change * 100:+.2f}%")

    all_rates = [r for _, r in rows]
    lines.append("")
    lines.append(f"52-week high: {max(all_rates):,.4f} {to_currency}")
    lines.append(f"52-week low: {min(all_rates):,.4f} {to_currency}")
    return "\n".join(lines)


@mcp.tool()
async def get_metal_price(metal: str) -> str:
    """Get the current spot price (in USD per troy ounce) for a precious metal.

    Args:
        metal: One of "gold", "silver", "platinum", "palladium".
    """
    symbol = _METAL_SYMBOLS.get(metal.lower())
    if symbol is None:
        return f"Unknown metal '{metal}'. Choose one of: {', '.join(_METAL_SYMBOLS)}."

    async with httpx.AsyncClient() as client:
        try:
            response = await get_with_retry(client, f"{METAL_BASE_URL}/{symbol}", timeout=30.0)
            response.raise_for_status()
            data = response.json()
        except Exception:
            return f"Couldn't fetch the current {metal} price right now."

    price = data.get("price")
    if price is None:
        return f"No price data available for {metal}."

    updated = data.get("updatedAtReadable", "")
    return f"{metal.capitalize()} spot price: ${price:,.2f} per troy ounce" + (f" (updated {updated})" if updated else "")


if __name__ == "__main__":
    mcp.run(transport="stdio")
