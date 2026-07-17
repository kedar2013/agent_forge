"""Tests for mcp_servers/chart_server.py and the shared
mcp_servers/_chart_utils.py rendering it (and slide_reporting_server.py)
both use.

Deliberately standalone -- no `app.*` imports, same reasoning as
test_slide_reporting.py (mixing `app.X` and `backend.app.X` imports in one
process causes a pre-existing SQLAlchemy metadata clash unrelated to this
module).

Run from backend/:
    ../.venv/Scripts/python.exe -m pytest tests/test_chart_server.py -v
"""

import os
import re
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "mcp_servers"))

import chart_server as cs  # noqa: E402
import _chart_utils as chart_utils  # noqa: E402

_MARKDOWN_IMAGE_RE = re.compile(r"^!\[(?P<alt>[^\]]*)\]\((?P<url>[^)]+)\)$")


def _cleanup(path: str) -> None:
    if os.path.exists(path):
        os.remove(path)


def test_render_bar_chart_single_series(tmp_path):
    out = str(tmp_path / "bar.png")
    chart_utils.render_bar_chart(["1M", "3M", "1Y"], [{"name": "AAPL", "values": [2.1, 5.4, 18.9]}], out, "% return")
    assert os.path.exists(out)
    assert os.path.getsize(out) > 1000


def test_render_bar_chart_multi_series_with_legend(tmp_path):
    out = str(tmp_path / "bar_multi.png")
    series = [
        {"name": "Fund A", "values": [12.0, 18.0, 9.0]},
        {"name": "Fund B", "values": [15.0, 14.0, 11.0]},
    ]
    chart_utils.render_bar_chart(["1Y", "3Y", "5Y"], series, out, "% CAGR")
    assert os.path.exists(out)
    assert os.path.getsize(out) > 1000


def test_render_line_chart_single_series(tmp_path):
    out = str(tmp_path / "line.png")
    chart_utils.render_line_chart(["2021", "2022", "2023"], [{"name": "revenue", "values": [100.0, 120.0, 140.0]}], out)
    assert os.path.exists(out)
    assert os.path.getsize(out) > 1000


def test_render_line_chart_multi_series_with_legend(tmp_path):
    out = str(tmp_path / "line_multi.png")
    series = [
        {"name": "HDFC Mid Cap", "values": [8.2, 12.1, 18.4, 22.0]},
        {"name": "Edelweiss Mid Cap", "values": [6.5, 10.8, 15.2, 19.7]},
    ]
    chart_utils.render_line_chart(["1M", "3M", "6M", "1Y"], series, out, "% return")
    assert os.path.exists(out)
    assert os.path.getsize(out) > 1000


@pytest.mark.asyncio
async def test_generate_chart_tool_returns_markdown_image():
    result = await cs.generate_chart_tool(
        chart_type="bar",
        title="AAPL trailing returns",
        x_labels=["1M", "3M", "1Y"],
        series=[cs.ChartSeries(name="AAPL", values=[2.1, 5.4, 18.9])],
        y_label="% return",
    )
    match = _MARKDOWN_IMAGE_RE.match(result)
    assert match is not None, result
    assert match.group("alt") == "AAPL trailing returns"
    assert match.group("url").startswith(cs.PUBLIC_BASE_URL + "/generated-images/")
    assert "?token=" in match.group("url")

    filename = match.group("url").rsplit("/", 1)[-1].split("?", 1)[0]
    path = os.path.join(cs.OUTPUT_DIR, filename)
    try:
        assert os.path.exists(path)
    finally:
        _cleanup(path)


@pytest.mark.asyncio
async def test_generate_chart_tool_multi_series_comparison():
    result = await cs.generate_chart_tool(
        chart_type="line",
        title="HDFC vs Edelweiss Mid Cap",
        x_labels=["1M", "3M", "6M", "1Y"],
        series=[
            cs.ChartSeries(name="HDFC Mid Cap", values=[8.2, 12.1, 18.4, 22.0]),
            cs.ChartSeries(name="Edelweiss Mid Cap", values=[6.5, 10.8, 15.2, 19.7]),
        ],
        y_label="% return",
    )
    match = _MARKDOWN_IMAGE_RE.match(result)
    assert match is not None, result
    filename = match.group("url").rsplit("/", 1)[-1].split("?", 1)[0]
    path = os.path.join(cs.OUTPUT_DIR, filename)
    try:
        assert os.path.exists(path)
    finally:
        _cleanup(path)


@pytest.mark.asyncio
async def test_generate_chart_tool_mismatched_series_length_errors_gracefully():
    result = await cs.generate_chart_tool(
        chart_type="bar",
        title="Bad input",
        x_labels=["1M", "3M", "1Y"],
        series=[cs.ChartSeries(name="AAPL", values=[2.1, 5.4])],
    )
    assert result.startswith("Couldn't generate the chart:")


@pytest.mark.asyncio
async def test_generate_chart_tool_empty_series_errors_gracefully():
    result = await cs.generate_chart_tool(
        chart_type="bar", title="No data", x_labels=["1M"], series=[],
    )
    assert result.startswith("Couldn't generate the chart:")
