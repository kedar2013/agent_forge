"""Shared matplotlib chart rendering, used by both slide_reporting_server.py
(PPTX decks) and chart_server.py (inline chat images) -- one implementation
so every chart across the app looks like the same visual system. Styling
follows the dataviz skill: fixed-order categorical hues for 2+ series
(never cycled), a single sequential hue with no legend for exactly one
series, recessive hairline gridlines, clean auto-compact axis ticks, and
sparse direct labels (never one per gridline).

`series` is always a list of {"name": str, "values": list[float]} dicts --
one series behaves exactly like a plain single-series chart (no legend,
per the "a single series needs no legend box" rule); 2+ series switch to
grouped bars / multiple lines with a legend.
"""

from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.ticker import FuncFormatter, MaxNLocator  # noqa: E402

from _theme import THEME  # noqa: E402


def fmt_number(value: float) -> str:
    """Auto-compact numeric formatting (1,284 / 12.9K / 4.2M), per the
    dataviz skill's stat-tile/figure convention."""
    abs_v = abs(value)
    if abs_v >= 1_000_000:
        return f"{value / 1_000_000:,.1f}M"
    if abs_v >= 1_000:
        return f"{value / 1_000:,.1f}K"
    if float(value).is_integer():
        return f"{value:,.0f}"
    return f"{value:,.2f}"


def _style_y_axis(ax) -> None:
    """Clean, thousands-comma'd / auto-compact y-axis ticks -- never
    matplotlib's raw scientific-notation offset text (e.g. "1e6"), and few
    enough ticks that adjacent gridlines never round to the same label."""
    ax.yaxis.set_major_locator(MaxNLocator(nbins=5, integer=False))
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _pos: fmt_number(v)))


def _style_axes(ax, y_label: str) -> None:
    ax.spines[["top", "right", "left"]].set_visible(False)
    ax.spines["bottom"].set_color(THEME["baseline"])
    ax.tick_params(axis="x", colors=THEME["ink_secondary"], labelsize=10)
    ax.tick_params(axis="y", colors=THEME["ink_muted"], labelsize=10)
    ax.yaxis.grid(True, color=THEME["gridline"], linewidth=1, zorder=0)
    ax.set_axisbelow(True)
    _style_y_axis(ax)
    if y_label:
        ax.set_ylabel(y_label, color=THEME["ink_secondary"], fontsize=11)


def _add_legend_if_needed(ax, n_series: int) -> None:
    if n_series >= 2:
        ax.legend(
            frameon=False, labelcolor=THEME["ink_secondary"], fontsize=10,
            loc="upper left", bbox_to_anchor=(0, 1.16), ncol=min(n_series, 4),
        )


def render_bar_chart(x_labels: list[str], series: list[dict[str, Any]], out_path: str, y_label: str = "") -> None:
    fig, ax = plt.subplots(figsize=(9, 5), dpi=200)
    fig.patch.set_alpha(0)
    ax.set_facecolor("none")

    n_series = len(series)
    x = list(range(len(x_labels)))

    if n_series == 1:
        values = series[0]["values"]
        bars = ax.bar(x, values, color=THEME["sequential"], width=0.55, zorder=3)
        for bar, value in zip(bars, values):  # direct label at the tip only -- never one per gridline
            ax.text(
                bar.get_x() + bar.get_width() / 2, bar.get_height(),
                fmt_number(value), ha="center", va="bottom", fontsize=9.5, color=THEME["ink_primary"],
            )
    else:
        total_width = 0.8
        bar_width = total_width / n_series
        for i, s in enumerate(series):
            offset = (i - (n_series - 1) / 2) * bar_width
            positions = [xi + offset for xi in x]
            color = THEME["categorical"][i % len(THEME["categorical"])]
            ax.bar(positions, s["values"], width=bar_width * 0.9, color=color, zorder=3, label=s["name"])

    ax.set_xticks(x)
    ax.set_xticklabels(x_labels)
    _style_axes(ax, y_label)
    _add_legend_if_needed(ax, n_series)

    plt.xticks(rotation=30, ha="right")
    fig.tight_layout()
    fig.savefig(out_path, transparent=True)
    plt.close(fig)


def render_line_chart(x_labels: list[str], series: list[dict[str, Any]], out_path: str, y_label: str = "") -> None:
    fig, ax = plt.subplots(figsize=(9, 5), dpi=200)
    fig.patch.set_alpha(0)
    ax.set_facecolor("none")

    n_series = len(series)
    for i, s in enumerate(series):
        color = THEME["sequential"] if n_series == 1 else THEME["categorical"][i % len(THEME["categorical"])]
        values = s["values"]
        ax.plot(x_labels, values, color=color, linewidth=2, marker="o", markersize=5, zorder=3, label=s["name"])
        if values:  # direct label just the endpoint, per dataviz guidance -- never one per point
            ax.annotate(
                fmt_number(values[-1]), xy=(len(x_labels) - 1, values[-1]),
                xytext=(6, 0), textcoords="offset points", fontsize=10, color=THEME["ink_primary"], va="center",
            )

    _style_axes(ax, y_label)
    _add_legend_if_needed(ax, n_series)

    plt.xticks(rotation=30, ha="right")
    fig.tight_layout()
    fig.savefig(out_path, transparent=True)
    plt.close(fig)
