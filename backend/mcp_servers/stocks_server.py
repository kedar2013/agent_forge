"""A real MCP server for global stocks & indices — Yahoo Finance's public,
unauthenticated `chart` and `search` endpoints (free, no API key). Runs over
stdio, spawned as a subprocess by Agent Forge's mcp_tool (StdioConnectionParams),
following the same pattern as mutual_fund_server.py.

Like analyze_fund_performance there, `analyze_stock_performance` computes
real trailing-return figures from daily closes rather than dumping years of
raw price history on the model.

Run standalone for a smoke test:
    python mcp_servers/stocks_server.py
"""

from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP

from _http_retry import get_with_retry

mcp = FastMCP("stocks")

SEARCH_URL = "https://query1.finance.yahoo.com/v1/finance/search"
CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
QUOTE_SUMMARY_URL = "https://query1.finance.yahoo.com/v10/finance/quoteSummary/{symbol}"
CRUMB_URL = "https://query2.finance.yahoo.com/v1/test/getcrumb"

# Yahoo's unauthenticated endpoints reject the default httpx UA.
_HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}


async def _fetch_quote_summary(symbol: str, modules: str) -> dict[str, Any] | None:
    """quoteSummary (fundamentals/company profile) needs a session cookie +
    crumb token, unlike chart/search — fetched fresh each call to keep this
    stateless and simple; still free, no API key."""
    async with httpx.AsyncClient(headers=_HEADERS, follow_redirects=True) as client:
        try:
            await get_with_retry(client, "https://fc.yahoo.com")
            crumb_resp = await get_with_retry(client, CRUMB_URL, timeout=30.0)
            crumb_resp.raise_for_status()
            crumb = crumb_resp.text

            response = await get_with_retry(
                client,
                QUOTE_SUMMARY_URL.format(symbol=symbol),
                params={"modules": modules, "crumb": crumb},
                timeout=30.0,
            )
            response.raise_for_status()
            data = response.json()
        except Exception:
            return None

    results = data.get("quoteSummary", {}).get("result")
    if not results:
        return None
    return results[0]


def _fmt_large_number(n: float | None) -> str:
    if n is None:
        return "n/a"
    for suffix, div in (("T", 1e12), ("B", 1e9), ("M", 1e6)):
        if abs(n) >= div:
            return f"{n / div:,.2f}{suffix}"
    return f"{n:,.0f}"


async def _fetch_chart(symbol: str, range_: str, interval: str) -> dict[str, Any] | None:
    async with httpx.AsyncClient(headers=_HEADERS) as client:
        try:
            response = await get_with_retry(
                client,
                CHART_URL.format(symbol=symbol),
                params={"range": range_, "interval": interval},
                timeout=30.0,
            )
            response.raise_for_status()
            data = response.json()
        except Exception:
            return None

    result = data.get("chart", {}).get("result")
    if not result:
        return None
    return result[0]


@mcp.tool()
async def search_stocks(query: str) -> str:
    """Search for stock/ETF/index ticker symbols by company or fund name.

    Args:
        query: A company, ETF, or index name — e.g. "Apple", "Nifty 50", "Tata Motors".
    """
    async with httpx.AsyncClient(headers=_HEADERS) as client:
        try:
            response = await get_with_retry(
                client, SEARCH_URL, params={"q": query, "quotesCount": 10, "newsCount": 0}, timeout=30.0
            )
            response.raise_for_status()
            quotes = response.json().get("quotes", [])
        except Exception:
            return f"Search failed for '{query}'."

    if not quotes:
        return f"No tickers found matching '{query}'. Try a shorter or different name."

    lines = [f"{len(quotes)} matches for '{query}':"]
    for q in quotes:
        symbol = q.get("symbol")
        name = q.get("shortname") or q.get("longname") or "?"
        exch = q.get("exchange", "?")
        kind = q.get("quoteType", "?")
        lines.append(f"{symbol}: {name} ({kind}, {exch})")
    return "\n".join(lines)


@mcp.tool()
async def get_stock_quote(symbol: str) -> str:
    """Get the latest price and day-over-day change for a stock, ETF, or index.

    Args:
        symbol: The ticker symbol (find it via search_stocks first) — e.g.
            "AAPL", "^NSEI" for Nifty 50, "TATAMOTORS.NS" for NSE-listed stocks.
    """
    chart = await _fetch_chart(symbol, range_="5d", interval="1d")
    if chart is None:
        return f"Couldn't fetch data for symbol '{symbol}'. Check the symbol is correct."

    meta = chart["meta"]
    price = meta.get("regularMarketPrice")
    prev_close = meta.get("previousClose") or meta.get("chartPreviousClose")
    currency = meta.get("currency", "")
    exchange = meta.get("fullExchangeName", meta.get("exchangeName", ""))
    name = meta.get("shortName") or meta.get("symbol", symbol)

    if price is None:
        return f"No live price available for '{symbol}'."

    lines = [f"{name} ({meta.get('symbol', symbol)}) - {exchange}", f"Price: {currency} {price:,.2f}"]
    if prev_close:
        change = price - prev_close
        pct = (change / prev_close) * 100 if prev_close else 0
        lines.append(f"Change: {change:+,.2f} ({pct:+.2f}%) vs previous close {currency} {prev_close:,.2f}")
    if meta.get("fiftyTwoWeekHigh"):
        lines.append(
            f"52-week range: {currency} {meta['fiftyTwoWeekLow']:,.2f} - {currency} {meta['fiftyTwoWeekHigh']:,.2f}"
        )
    return "\n".join(lines)


def _closes_with_dates(chart: dict[str, Any]) -> list[tuple[datetime, float]]:
    timestamps = chart.get("timestamp", [])
    closes = chart["indicators"]["quote"][0].get("close", [])
    rows = []
    for ts, close in zip(timestamps, closes):
        if close is None:
            continue
        rows.append((datetime.fromtimestamp(ts, tz=timezone.utc), float(close)))
    return rows


def _close_on_or_before(rows: list[tuple[datetime, float]], target: datetime) -> float | None:
    """rows are oldest-first; finds the close closest to (but not after) target."""
    candidate = None
    for date, close in rows:
        if date <= target:
            candidate = close
        else:
            break
    return candidate


@mcp.tool()
async def analyze_stock_performance(symbol: str) -> str:
    """Analyze a stock/ETF/index's historical performance: trailing returns
    over several periods, and its 52-week high/low. Use this for "how has this
    stock performed" or "what are the returns on X" questions — it computes
    real figures rather than dumping raw price history.

    Args:
        symbol: The ticker symbol (find it via search_stocks first).
    """
    chart = await _fetch_chart(symbol, range_="5y", interval="1d")
    if chart is None:
        return f"Couldn't fetch data for symbol '{symbol}'. Check the symbol is correct."

    meta = chart["meta"]
    currency = meta.get("currency", "")
    name = meta.get("shortName") or meta.get("symbol", symbol)
    rows = _closes_with_dates(chart)
    if not rows:
        return f"No historical price data available for '{symbol}'."

    latest_date, latest_close = rows[-1]

    periods = {
        "1 month": 30,
        "3 months": 91,
        "6 months": 182,
        "1 year": 365,
        "3 years": 365 * 3,
        "5 years": 365 * 5,
    }

    lines = [
        f"{name} ({meta.get('symbol', symbol)})",
        f"Latest close: {currency} {latest_close:,.2f} (as of {latest_date.date()})",
        "",
        "Trailing returns:",
    ]
    for label, days in periods.items():
        target = latest_date - timedelta(days=days)
        past_close = _close_on_or_before(rows, target)
        if past_close is None or past_close <= 0:
            lines.append(f"  {label}: not enough history")
            continue
        total_return = (latest_close / past_close) - 1
        if days > 365:
            years = days / 365
            cagr = (latest_close / past_close) ** (1 / years) - 1
            lines.append(f"  {label}: {total_return * 100:+.2f}% total ({cagr * 100:+.2f}% CAGR)")
        else:
            lines.append(f"  {label}: {total_return * 100:+.2f}%")

    one_year_ago = latest_date - timedelta(days=365)
    one_year_closes = [c for d, c in rows if d >= one_year_ago]
    if one_year_closes:
        lines.append("")
        lines.append(f"52-week high: {currency} {max(one_year_closes):,.2f}")
        lines.append(f"52-week low: {currency} {min(one_year_closes):,.2f}")

    return "\n".join(lines)


@mcp.tool()
async def get_company_profile(symbol: str) -> str:
    """Get a company's business profile: sector, industry, headquarters,
    website, and a description of what it does. Not for financial figures —
    use get_company_fundamentals for those.

    Args:
        symbol: The ticker symbol (find it via search_stocks first).
    """
    result = await _fetch_quote_summary(symbol, "assetProfile")
    profile = result.get("assetProfile") if result else None
    if not profile:
        return f"Couldn't fetch a company profile for '{symbol}'. It may be an index or ETF, which have no profile."

    lines = []
    location = ", ".join(
        p for p in [profile.get("city"), profile.get("state"), profile.get("country")] if p
    )
    if profile.get("sector"):
        lines.append(f"Sector: {profile['sector']}")
    if profile.get("industry"):
        lines.append(f"Industry: {profile['industry']}")
    if location:
        lines.append(f"Headquarters: {location}")
    if profile.get("website"):
        lines.append(f"Website: {profile['website']}")
    if profile.get("fullTimeEmployees"):
        lines.append(f"Employees: {profile['fullTimeEmployees']:,}")
    if profile.get("longBusinessSummary"):
        lines.append("")
        lines.append(profile["longBusinessSummary"])
    return "\n".join(lines) if lines else f"No profile details available for '{symbol}'."


@mcp.tool()
async def get_company_fundamentals(symbol: str) -> str:
    """Get a company's key financial fundamentals: market cap, P/E ratio,
    EPS, dividend yield, and beta. Not for price history — use
    analyze_stock_performance for trailing returns.

    Args:
        symbol: The ticker symbol (find it via search_stocks first).
    """
    result = await _fetch_quote_summary(symbol, "summaryDetail,defaultKeyStatistics,price")
    if not result:
        return f"Couldn't fetch fundamentals for '{symbol}'. It may be an index, which has no company fundamentals."

    summary = result.get("summaryDetail", {})
    stats = result.get("defaultKeyStatistics", {})
    price_info = result.get("price", {})

    def _raw(block: dict, key: str) -> float | None:
        val = block.get(key)
        if isinstance(val, dict):
            return val.get("raw")
        return val

    currency = price_info.get("currency", "")
    name = price_info.get("longName") or price_info.get("shortName") or symbol
    market_cap = _raw(summary, "marketCap") or _raw(price_info, "marketCap")
    pe_ratio = _raw(summary, "trailingPE")
    forward_pe = _raw(summary, "forwardPE")
    eps = _raw(stats, "trailingEps")
    dividend_yield = _raw(summary, "dividendYield")
    beta = _raw(summary, "beta")

    lines = [f"{name} ({symbol}) fundamentals:"]
    lines.append(f"Market cap: {currency} {_fmt_large_number(market_cap)}")
    if pe_ratio:
        lines.append(f"P/E ratio (trailing): {pe_ratio:.2f}")
    if forward_pe:
        lines.append(f"P/E ratio (forward): {forward_pe:.2f}")
    if eps:
        lines.append(f"EPS (trailing): {currency} {eps:.2f}")
    if dividend_yield:
        lines.append(f"Dividend yield: {dividend_yield * 100:.2f}%")
    if beta:
        lines.append(f"Beta: {beta:.2f}")
    return "\n".join(lines)


@mcp.tool()
async def get_revenue_trend(symbol: str) -> str:
    """Get a company's quarterly revenue for the last 4 reported quarters,
    with quarter-over-quarter growth — real reported figures, not estimates.

    Args:
        symbol: The ticker symbol (find it via search_stocks first).
    """
    result = await _fetch_quote_summary(symbol, "incomeStatementHistoryQuarterly,price")
    rows = (result or {}).get("incomeStatementHistoryQuarterly", {}).get("incomeStatementHistory", [])
    if not rows:
        return f"Couldn't fetch revenue history for '{symbol}'. It may be an index or ETF, which report no revenue."

    currency = (result.get("price") or {}).get("currency", "")
    lines = [f"{symbol} quarterly revenue (most recent first):"]
    prev_revenue = None
    for row in rows:
        end_date = row.get("endDate", {}).get("fmt", "?")
        revenue = row.get("totalRevenue", {}).get("raw")
        if revenue is None:
            continue
        line = f"  {end_date}: {currency} {_fmt_large_number(revenue)}"
        if prev_revenue:
            change = (revenue / prev_revenue - 1) * 100
            line += f" ({change:+.1f}% vs prior quarter)"
        lines.append(line)
        prev_revenue = revenue
    return "\n".join(lines)


@mcp.tool()
async def get_quarterly_earnings(symbol: str) -> str:
    """Get a company's EPS actual-vs-estimate for the last 4 reported
    quarters (with surprise %), plus the analyst estimate for the upcoming
    quarter — real reported figures for the past, consensus estimates for
    what hasn't happened yet.

    Args:
        symbol: The ticker symbol (find it via search_stocks first).
    """
    result = await _fetch_quote_summary(symbol, "earningsHistory,earningsTrend")
    if not result:
        return f"Couldn't fetch earnings history for '{symbol}'."

    history = result.get("earningsHistory", {}).get("history", [])
    lines = [f"{symbol} quarterly EPS (actual vs. estimate, most recent first):"]
    for row in history:
        quarter_end = row.get("quarter", {}).get("fmt", "?")
        actual = row.get("epsActual", {}).get("raw")
        estimate = row.get("epsEstimate", {}).get("raw")
        surprise = row.get("surprisePercent", {}).get("raw")
        if actual is None:
            continue
        line = f"  Q ending {quarter_end}: actual {actual:.2f} vs estimate {estimate:.2f}"
        if surprise is not None:
            line += f" ({surprise * 100:+.2f}% surprise)"
        lines.append(line)

    trend = result.get("earningsTrend", {}).get("trend", [])
    upcoming = next((t for t in trend if t.get("period") == "0q"), None)
    if upcoming:
        est = upcoming.get("earningsEstimate", {})
        avg = est.get("avg", {}).get("raw")
        num_analysts = est.get("numberOfAnalysts", {}).get("raw")
        if avg is not None:
            lines.append("")
            lines.append(
                f"Upcoming quarter (ending {upcoming.get('endDate', '?')}): "
                f"consensus estimate {avg:.2f} EPS from {num_analysts or '?'} analysts"
            )
    return "\n".join(lines)


@mcp.tool()
async def get_analyst_sentiment(symbol: str) -> str:
    """Get current analyst sentiment: buy/hold/sell recommendation counts,
    plus the most recent rating changes and price targets.

    Args:
        symbol: The ticker symbol (find it via search_stocks first).
    """
    result = await _fetch_quote_summary(symbol, "recommendationTrend,upgradeDowngradeHistory")
    if not result:
        return f"Couldn't fetch analyst sentiment for '{symbol}'."

    lines = [f"Analyst sentiment for {symbol}:"]
    trend = result.get("recommendationTrend", {}).get("trend", [])
    current = next((t for t in trend if t.get("period") == "0m"), None)
    if current:
        lines.append(
            f"Current ratings: {current.get('strongBuy', 0)} strong buy, {current.get('buy', 0)} buy, "
            f"{current.get('hold', 0)} hold, {current.get('sell', 0)} sell, {current.get('strongSell', 0)} strong sell"
        )

    history = result.get("upgradeDowngradeHistory", {}).get("history", [])[:5]
    if history:
        lines.append("")
        lines.append("Most recent rating actions:")
        for h in history:
            date = datetime.fromtimestamp(h["epochGradeDate"], tz=timezone.utc).strftime("%Y-%m-%d")
            target = h.get("currentPriceTarget")
            target_str = f", price target {target}" if target else ""
            lines.append(f"  [{date}] {h.get('firm', '?')}: {h.get('action', '?')} to {h.get('toGrade', '?')}{target_str}")
    return "\n".join(lines)


@mcp.tool()
async def get_regulatory_filings(symbol: str) -> str:
    """Get a company's recent SEC regulatory filings (10-K, 10-Q, 20-F, 6-K,
    8-K, etc.) with dates, types, and links to the actual filing.

    Args:
        symbol: The ticker symbol (find it via search_stocks first).
    """
    result = await _fetch_quote_summary(symbol, "secFilings")
    filings = (result or {}).get("secFilings", {}).get("filings", [])
    if not filings:
        return f"No SEC filings found for '{symbol}' — it may not be SEC-registered (e.g. a non-US-listed company)."

    lines = [f"Recent SEC filings for {symbol}:"]
    for f in filings[:8]:
        lines.append(f"  [{f.get('date', '?')}] {f.get('type', '?')}: {f.get('title', '?')} - {f.get('edgarUrl', '')}")
    return "\n".join(lines)


@mcp.tool()
async def get_company_news(query: str) -> str:
    """Get recent news headlines related to a company or ticker.

    Args:
        query: A company name or ticker symbol, e.g. "Apple" or "AAPL".
    """
    async with httpx.AsyncClient(headers=_HEADERS) as client:
        try:
            response = await get_with_retry(
                client, SEARCH_URL, params={"q": query, "quotesCount": 0, "newsCount": 8}, timeout=30.0
            )
            response.raise_for_status()
            news = response.json().get("news", [])
        except Exception:
            return f"Couldn't fetch news for '{query}'."

    if not news:
        return f"No recent news found for '{query}'."

    lines = [f"Recent headlines for '{query}':"]
    for item in news:
        published = datetime.fromtimestamp(item["providerPublishTime"], tz=timezone.utc).strftime("%Y-%m-%d")
        lines.append(f"- [{published}] {item['title']} ({item['publisher']})")
    return "\n".join(lines)


if __name__ == "__main__":
    mcp.run(transport="stdio")
