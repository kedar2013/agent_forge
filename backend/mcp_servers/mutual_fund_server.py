"""A real MCP server for Indian mutual fund analysis — mfapi.in (free, no API
key, daily-updated NAV data sourced from AMFI). Runs over stdio, spawned as a
subprocess by Eärendil's mcp_tool (StdioConnectionParams).

Unlike a thin passthrough, `analyze_fund_performance` computes real return
figures (1M/3M/6M/1Y/3Y/5Y, 52-week high/low) from the raw NAV history rather
than handing an LLM years of daily {date, nav} rows to reason over itself.

Run standalone for a smoke test:
    python mcp_servers/mutual_fund_server.py
"""

from datetime import datetime, timedelta
from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP

from _http_retry import get_with_retry

mcp = FastMCP("mutual-funds")

BASE_URL = "https://api.mfapi.in/mf"


def _parse_date(s: str) -> datetime:
    return datetime.strptime(s, "%d-%m-%Y")


async def _fetch_scheme(scheme_code: int) -> dict[str, Any] | None:
    async with httpx.AsyncClient() as client:
        try:
            response = await get_with_retry(client, f"{BASE_URL}/{scheme_code}", timeout=30.0)
            response.raise_for_status()
            data = response.json()
        except Exception:
            return None
    if data.get("status") != "SUCCESS" or not data.get("data"):
        return None
    return data


@mcp.tool()
async def search_mutual_funds(query: str) -> str:
    """Search for Indian mutual fund schemes by name or fund house.

    Args:
        query: A single distinctive keyword works best — e.g. "HDFC", "Bluechip",
            "Nifty50" — rather than a full scheme name.
    """
    async with httpx.AsyncClient() as client:
        try:
            response = await get_with_retry(client, f"{BASE_URL}/search", params={"q": query}, timeout=30.0)
            response.raise_for_status()
            results = response.json()
        except Exception:
            return f"Search failed for '{query}'."

    if not results:
        return f"No schemes found matching '{query}'. Try a shorter or different keyword."

    lines = [f"{len(results)} matches for '{query}' (showing up to 20):"]
    for r in results[:20]:
        lines.append(f"{r['schemeCode']}: {r['schemeName']}")
    return "\n".join(lines)


@mcp.tool()
async def get_latest_nav(scheme_code: int) -> str:
    """Get today's (or most recent) NAV for a specific mutual fund scheme.

    Args:
        scheme_code: The numeric scheme code (find it via search_mutual_funds first).
    """
    scheme = await _fetch_scheme(scheme_code)
    if scheme is None:
        return f"Couldn't fetch data for scheme code {scheme_code}. Check the code is correct."

    meta = scheme["meta"]
    latest = scheme["data"][0]
    return (
        f"{meta['scheme_name']} ({meta['fund_house']})\n"
        f"Category: {meta['scheme_category']}\n"
        f"NAV as of {latest['date']}: Rs. {latest['nav']}"
    )


def _nav_on_or_before(rows: list[dict], target: datetime) -> float | None:
    """rows are newest-first; finds the NAV closest to (but not after) target."""
    for row in rows:
        if _parse_date(row["date"]) <= target:
            return float(row["nav"])
    return None


@mcp.tool()
async def analyze_fund_performance(scheme_code: int) -> str:
    """Analyze a mutual fund's historical performance: trailing returns over
    several periods, and its 52-week high/low. Use this for "how has this fund
    performed" or "what are the returns on X" questions — it computes real
    figures rather than dumping raw NAV history.

    Args:
        scheme_code: The numeric scheme code (find it via search_mutual_funds first).
    """
    scheme = await _fetch_scheme(scheme_code)
    if scheme is None:
        return f"Couldn't fetch data for scheme code {scheme_code}. Check the code is correct."

    meta = scheme["meta"]
    rows = scheme["data"]
    latest_date = _parse_date(rows[0]["date"])
    latest_nav = float(rows[0]["nav"])

    periods = {
        "1 month": 30,
        "3 months": 91,
        "6 months": 182,
        "1 year": 365,
        "3 years": 365 * 3,
        "5 years": 365 * 5,
    }

    lines = [
        f"{meta['scheme_name']} ({meta['fund_house']})",
        f"Category: {meta['scheme_category']}",
        f"Latest NAV: Rs. {latest_nav} (as of {rows[0]['date']})",
        "",
        "Trailing returns:",
    ]
    for label, days in periods.items():
        from datetime import timedelta

        target = latest_date - timedelta(days=days)
        past_nav = _nav_on_or_before(rows, target)
        if past_nav is None or past_nav <= 0:
            lines.append(f"  {label}: not enough history")
            continue
        total_return = (latest_nav / past_nav) - 1
        if days > 365:
            years = days / 365
            cagr = (latest_nav / past_nav) ** (1 / years) - 1
            lines.append(f"  {label}: {total_return * 100:+.2f}% total ({cagr * 100:+.2f}% CAGR)")
        else:
            lines.append(f"  {label}: {total_return * 100:+.2f}%")

    one_year_ago = latest_date.replace(year=latest_date.year - 1)
    one_year_rows = [r for r in rows if _parse_date(r["date"]) >= one_year_ago]
    if one_year_rows:
        navs = [float(r["nav"]) for r in one_year_rows]
        lines.append("")
        lines.append(f"52-week high: Rs. {max(navs):.4f}")
        lines.append(f"52-week low: Rs. {min(navs):.4f}")

    return "\n".join(lines)


def _monthly_series(rows: list[dict]) -> list[tuple[datetime, float]]:
    """rows are newest-first; returns (date, nav) for the last available NAV
    in each calendar month, oldest first — used to compute monthly returns
    without daily noise dominating the volatility estimate."""
    by_month: dict[tuple[int, int], tuple[datetime, float]] = {}
    for row in rows:
        d = _parse_date(row["date"])
        key = (d.year, d.month)
        if key not in by_month or d > by_month[key][0]:
            by_month[key] = (d, float(row["nav"]))
    return sorted(by_month.values(), key=lambda x: x[0])


@mcp.tool()
async def predict_fund_trend(scheme_code: int) -> str:
    """Deep trend analysis for an Indian mutual fund: volatility, maximum
    drawdown, and a statistical NAV projection for 6/12 months computed from
    the fund's own historical trend and volatility.

    This is a mathematical extrapolation of the past, NOT a forecast,
    guarantee, or investment advice — say so plainly when presenting it, and
    never use this for stocks, crypto, or any non-mutual-fund asset.

    Args:
        scheme_code: The numeric scheme code (find it via search_mutual_funds first).
    """
    scheme = await _fetch_scheme(scheme_code)
    if scheme is None:
        return f"Couldn't fetch data for scheme code {scheme_code}. Check the code is correct."

    meta = scheme["meta"]
    rows = scheme["data"]
    monthly = _monthly_series(rows)
    if len(monthly) < 13:
        return (
            f"{meta['scheme_name']} doesn't have enough NAV history yet "
            "(need at least ~1 year of data) for a reliable trend analysis."
        )

    monthly_returns = [
        (monthly[i][1] / monthly[i - 1][1]) - 1 for i in range(1, len(monthly))
    ]
    recent_returns = monthly_returns[-36:]  # up to 3 years of monthly returns
    mean_monthly = sum(recent_returns) / len(recent_returns)
    variance = sum((r - mean_monthly) ** 2 for r in recent_returns) / len(recent_returns)
    monthly_vol = variance ** 0.5
    annualized_vol = monthly_vol * (12 ** 0.5)

    navs_recent = [nav for _, nav in monthly[-37:]] if len(monthly) >= 37 else [nav for _, nav in monthly]
    peak = navs_recent[0]
    max_drawdown = 0.0
    for nav in navs_recent:
        peak = max(peak, nav)
        drawdown = (nav / peak) - 1
        max_drawdown = min(max_drawdown, drawdown)

    positive_months = sum(1 for r in recent_returns if r > 0)

    latest_date, latest_nav = monthly[-1]
    years_of_history = min(3, (latest_date - monthly[0][0]).days / 365)
    cagr_window_nav = None
    for date, nav in reversed(monthly):
        if (latest_date - date).days / 365 >= years_of_history - 0.05:
            cagr_window_nav = nav
            break
    trend_cagr = (
        (latest_nav / cagr_window_nav) ** (1 / years_of_history) - 1
        if cagr_window_nav and years_of_history > 0
        else mean_monthly * 12
    )
    monthly_trend_return = (1 + trend_cagr) ** (1 / 12) - 1

    lines = [
        f"{meta['scheme_name']} ({meta['fund_house']}) - trend & projection analysis",
        "(Statistical extrapolation of historical NAV data - NOT a forecast, guarantee, "
        "or investment advice. Mutual fund investments are subject to market risk and "
        "past performance does not indicate future results.)",
        "",
        f"Volatility (annualized, from monthly returns): {annualized_vol * 100:.2f}%",
        f"Maximum drawdown (peak-to-trough, recent history): {max_drawdown * 100:.2f}%",
        f"Positive months: {positive_months} of {len(recent_returns)} "
        f"({positive_months / len(recent_returns) * 100:.0f}%)",
        f"Trend basis: {trend_cagr * 100:+.2f}% CAGR over the trailing {years_of_history:.1f} years",
        "",
        "Projected NAV if this trend and volatility continue unchanged "
        "(central estimate, with a rough uncertainty range):",
    ]
    for label, months in (("6 months", 6), ("12 months", 12)):
        expected_total_return = (1 + monthly_trend_return) ** months - 1
        band = monthly_vol * (months ** 0.5)
        expected_nav = latest_nav * (1 + expected_total_return)
        low_nav = latest_nav * (1 + expected_total_return - band)
        high_nav = latest_nav * (1 + expected_total_return + band)
        lines.append(
            f"  {label}: Rs. {expected_nav:.2f} (rough range Rs. {max(low_nav, 0):.2f} - Rs. {high_nav:.2f})"
        )

    lines.append("")
    lines.append(
        "This projection only extrapolates past average growth and volatility using "
        "compound math - it does not account for market conditions, fund manager "
        "changes, economic events, or anything else that could change future "
        "performance. Treat it as one data point, not a prediction of what will "
        "actually happen."
    )
    return "\n".join(lines)


# One well-established, real scheme per sector, used purely as a historical
# performance proxy for that sector — not a recommendation to invest in this
# specific scheme. Picked from real search_mutual_funds results (see session
# notes), favoring Direct/Growth options where available for a cleaner signal.
_SECTOR_PROXIES: dict[str, int] = {
    "Banking & Financial Services": 101862,
    "Technology / IT": 120594,
    "Pharma & Healthcare": 102431,
    "Infrastructure": 105602,
    "FMCG": 120587,
    "Energy & Natural Resources": 108202,
    "Auto": 150643,
    "Consumption": 153015,
    "Realty": 153060,
    "PSU Banking": 154278,
}


@mcp.tool()
async def scan_sector_trends() -> str:
    """Compare historical performance across major Indian equity sectors
    (banking, IT, pharma, infrastructure, FMCG, energy, auto, consumption,
    realty, PSU banking), using one representative fund per sector as a
    proxy. Use this for "which sectors have done well" / "what sectors
    should I look at" questions — it ranks by real trailing returns, it does
    not recommend a sector to invest in.

    Mutual funds only — never use this pattern for stocks/crypto/forex.
    """
    now = datetime.now()
    periods = {"3 months": 91, "6 months": 182, "1 year": 365, "3 years": 365 * 3}
    rows: list[dict[str, Any]] = []

    for sector, scheme_code in _SECTOR_PROXIES.items():
        scheme = await _fetch_scheme(scheme_code)
        if scheme is None:
            continue
        data = scheme["data"]
        latest_date = _parse_date(data[0]["date"])
        latest_nav = float(data[0]["nav"])
        returns: dict[str, float | None] = {}
        for label, days in periods.items():
            past_nav = _nav_on_or_before(data, latest_date - timedelta(days=days))
            returns[label] = (latest_nav / past_nav - 1) if past_nav and past_nav > 0 else None
        rows.append({"sector": sector, "fund": scheme["meta"]["scheme_name"], "returns": returns})

    if not rows:
        return "Couldn't fetch sector data right now - try again shortly."

    rows.sort(key=lambda r: (r["returns"].get("1 year") is None, -(r["returns"].get("1 year") or -999)))

    lines = [
        "Sector performance comparison (using one representative fund per sector as "
        "a historical proxy - real trailing returns, not a recommendation; sector "
        "leadership rotates and past winners often underperform later):",
        "",
        f"As of {now.strftime('%Y-%m-%d')}, ranked by 1-year return:",
    ]
    for row in rows:
        r = row["returns"]

        def _fmt(label: str) -> str:
            v = r.get(label)
            return f"{v * 100:+.2f}%" if v is not None else "n/a"

        lines.append(
            f"  {row['sector']}: 3M {_fmt('3 months')}, 6M {_fmt('6 months')}, "
            f"1Y {_fmt('1 year')}, 3Y {_fmt('3 years')} (proxy: {row['fund']})"
        )

    lines.append("")
    lines.append(
        "This compares fund categories, not the sector economy directly, and each "
        "proxy fund's own stock selection and fees affect its numbers. Use this to "
        "spot broad historical trends, not as investment advice."
    )
    return "\n".join(lines)


@mcp.tool()
async def project_sip_growth(scheme_code: int, monthly_amount: float, years: float) -> str:
    """Project the future value of a monthly SIP (systematic investment plan)
    into a specific mutual fund, using that fund's own trailing 3-year CAGR
    as the growth assumption — real compound-interest math on a real
    historical trend, not a guess.

    This is a projection assuming the historical trend continues, NOT a
    guarantee. Mutual funds only.

    Args:
        scheme_code: The numeric scheme code (find it via search_mutual_funds first).
        monthly_amount: Rupees invested each month, e.g. 10000.
        years: Number of years to project, e.g. 1, 3, 5.
    """
    scheme = await _fetch_scheme(scheme_code)
    if scheme is None:
        return f"Couldn't fetch data for scheme code {scheme_code}. Check the code is correct."

    monthly = _monthly_series(scheme["data"])
    if len(monthly) < 13:
        return f"{scheme['meta']['scheme_name']} doesn't have enough history yet for a reliable SIP projection."

    latest_date, latest_nav = monthly[-1]
    lookback_years = min(3, (latest_date - monthly[0][0]).days / 365)
    window_nav = None
    for date, nav in reversed(monthly):
        if (latest_date - date).days / 365 >= lookback_years - 0.05:
            window_nav = nav
            break
    trend_cagr = (latest_nav / window_nav) ** (1 / lookback_years) - 1 if window_nav and lookback_years > 0 else 0.0
    monthly_rate = (1 + trend_cagr) ** (1 / 12) - 1

    months = round(years * 12)
    if monthly_rate > 0:
        future_value = monthly_amount * (((1 + monthly_rate) ** months - 1) / monthly_rate) * (1 + monthly_rate)
    else:
        future_value = monthly_amount * months
    total_invested = monthly_amount * months
    gain = future_value - total_invested

    lines = [
        f"SIP projection for {scheme['meta']['scheme_name']} ({scheme['meta']['fund_house']})",
        f"Assumption: Rs. {monthly_amount:,.0f}/month for {years:g} years ({months} months), "
        f"growing at this fund's trailing {lookback_years:.1f}-year CAGR of {trend_cagr * 100:+.2f}%.",
        "",
        f"Total invested: Rs. {total_invested:,.0f}",
        f"Projected value: Rs. {future_value:,.0f}",
        f"Projected gain: Rs. {gain:,.0f} ({(gain / total_invested * 100) if total_invested else 0:+.2f}%)",
        "",
        "This assumes the fund's historical trend continues unchanged for the whole "
        "period, which real markets never do exactly - actual returns will differ, "
        "possibly by a lot, in either direction. This is a projection for planning "
        "purposes, not a guarantee or investment advice.",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    mcp.run(transport="stdio")
