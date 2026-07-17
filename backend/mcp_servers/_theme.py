"""Shared chart/slide styling for slide_reporting_server.py — one THEME dict
so every chart, table, and slide kind looks like the same deck. Colors come
from the dataviz skill's validated reference palette (light mode, since a
PPTX deck is always rendered on a light/white surface): fixed-order
categorical hues, a single-hue sequential ramp for one-series charts, and
text/gridline tokens kept out of the data-color role.
"""

THEME = {
    # Fixed-order categorical hues -- never cycled, never reordered per-chart.
    "categorical": [
        "#2A78D6",  # blue
        "#1BAF7A",  # aqua
        "#EDA100",  # yellow
        "#008300",  # green
        "#4A3AA7",  # violet
        "#E34948",  # red
        "#E87BA4",  # magenta
        "#EB6834",  # orange
    ],
    # Single-hue sequential ramp (light -> dark blue) for one-series bar/line
    # charts and KPI accents.
    "sequential": "#256ABF",
    "sequential_light": "#9EC5F4",
    # Chart chrome / ink -- text and gridlines never use a data color.
    "surface": "#FCFCFB",
    "ink_primary": "#0B0B0B",
    "ink_secondary": "#52514E",
    "ink_muted": "#898781",
    "gridline": "#E1E0D9",
    "baseline": "#C3C2B7",
    # Brand accent (matches document_export_server.py's table header / this
    # repo's existing brand purple) used for slide titles and table headers.
    "brand": "#5B3FE6",
}

FONT_FAMILY = "Segoe UI"
