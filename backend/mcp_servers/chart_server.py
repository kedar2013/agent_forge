"""A real MCP server exposing ONE shared charting tool
(generate_chart_tool) that any agent can call to turn a numeric series it
already has (trailing returns, NAV/price history, quarterly revenue, a
multi-fund/stock/coin comparison) into an inline chart image for its chat
reply -- pure local computation (matplotlib via _chart_utils.py), no
external API. Runs over stdio, spawned as a subprocess by Eärendil's
mcp_tool (StdioConnectionParams), following the same pattern as the other
mcp_servers/*.py files.

This is deliberately the ONE place chart rendering lives for chat replies:
mcp_servers/slide_reporting_server.py (PPTX decks) and this file both call
the same _chart_utils.render_bar_chart/render_line_chart, so every chart
across the app -- whether it ends up in a slide deck or a chat bubble --
uses the same palette/marks/axis styling.

Files are written to backend/generated_images/, which app/main.py mounts at
/generated-images -- the same directory app/tool_registry/image_gen_tool.py
already uses. Returns a ready-to-paste MARKDOWN IMAGE SNIPPET (not just a
bare URL) using an ABSOLUTE URL via BACKEND_PUBLIC_URL, for the same reason
document_export_server.py does: the frontend (Vite dev server) runs on a
different origin/port than the backend, so a relative /generated-images/...
link would resolve against the frontend's origin and 404.

Run standalone for a smoke test:
    python mcp_servers/chart_server.py
"""

import os
import uuid
from typing import Literal

from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel

from _chart_utils import render_bar_chart, render_line_chart
from _signed_urls import sign_filename

mcp = FastMCP("chart-generation")

# Matches the directory app/main.py mounts at /generated-images, regardless
# of the process's current working directory -- same convention
# app/tool_registry/image_gen_tool.py uses for this same directory.
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "..", "generated_images")
PUBLIC_BASE_URL = os.environ.get("BACKEND_PUBLIC_URL", "http://127.0.0.1:8000")

_MAX_SERIES = 8
_MAX_POINTS_PER_SERIES = 30


class ChartSeries(BaseModel):
    name: str
    values: list[float]


@mcp.tool()
async def generate_chart_tool(
    chart_type: Literal["bar", "line"],
    title: str,
    x_labels: list[str],
    series: list[ChartSeries],
    y_label: str = "",
) -> str:
    """Render a chart PNG from numeric data you already have, and get back a
    ready-to-paste markdown image snippet -- just include the returned
    string directly in your reply and it will render inline for the user.
    Use this whenever your answer includes a multi-point numeric series:
    trailing returns across periods, price/NAV history over time, quarterly
    revenue, or a comparison across two or more funds/stocks/coins/
    currencies. Don't use it in place of the numbers -- include both the
    chart and the prose explanation.

    Args:
        chart_type: "bar" for category-vs-value or period-vs-value
            comparisons (e.g. trailing returns by period, revenue by
            quarter); "line" for a trend over an ordered sequence (e.g.
            price/NAV history, a multi-year trend).
        title: A short, specific title (e.g. "HDFC Mid Cap vs Edelweiss Mid
            Cap -- trailing returns").
        x_labels: The category/period labels along the x-axis (e.g. ["1M",
            "3M", "6M", "1Y"] or ["2021", "2022", "2023", "2024"]). Every
            series must have exactly this many values, in the same order.
        series: One entry per line/fund/stock/coin being shown -- a single
            entry renders as a plain single-series chart (no legend); two
            or more render as a grouped bar / multi-line chart with a
            legend, one color per series in a fixed, non-cycled order.
        y_label: What the values represent (e.g. "% return", "price (USD)",
            "revenue ($M)"). Leave blank if obvious from the title.
    """
    if not x_labels:
        return "Couldn't generate the chart: no x-axis labels were provided."
    if not series:
        return "Couldn't generate the chart: no data series were provided."
    if len(series) > _MAX_SERIES:
        return f"Couldn't generate the chart: at most {_MAX_SERIES} series are supported for readability."
    if len(x_labels) > _MAX_POINTS_PER_SERIES:
        return f"Couldn't generate the chart: at most {_MAX_POINTS_PER_SERIES} points are supported for readability."
    for s in series:
        if len(s.values) != len(x_labels):
            return (
                f"Couldn't generate the chart: series '{s.name}' has {len(s.values)} values "
                f"but there are {len(x_labels)} x-axis labels -- they must match."
            )

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    filename = f"{uuid.uuid4().hex}.png"
    path = os.path.join(OUTPUT_DIR, filename)
    series_dicts = [{"name": s.name, "values": s.values} for s in series]

    try:
        if chart_type == "bar":
            render_bar_chart(x_labels, series_dicts, path, y_label)
        else:
            render_line_chart(x_labels, series_dicts, path, y_label)
    except Exception as exc:  # noqa: BLE001 -- surfaced to the agent, not the caller
        return f"Couldn't generate the chart: {exc}"

    token = sign_filename("generated-images", filename)
    return f"![{title}]({PUBLIC_BASE_URL}/generated-images/{filename}?token={token})"


if __name__ == "__main__":
    mcp.run(transport="stdio")
