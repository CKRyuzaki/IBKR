"""Bloomberg-terminal look: black canvas, amber labels, green/red for up/down, dense monospace.

One place for colours so the CSS (assets/style.css), Plotly figures and DataTables agree.
The plotly template is registered as "bloomberg" and made the default on import.
"""

from __future__ import annotations

import plotly.graph_objects as go
import plotly.io as pio

BLACK = "#000000"
PANEL = "#0b0b0b"
GRID = "#262626"
BORDER = "#3a3a3a"
AMBER = "#FFA028"  # labels, headers, primary series
TEXT = "#E6E6E6"
DIM = "#8a8a8a"
UP = "#00D27A"
DOWN = "#FF433D"
WARN = "#FFD400"
BLUE = "#3D8BFF"
CYAN = "#22D3EE"

FONT = "Consolas, 'Lucida Console', 'Courier New', monospace"

COLORWAY = [AMBER, CYAN, UP, BLUE, DOWN, "#C792EA", WARN, "#F5F5F5"]

_axis = dict(gridcolor=GRID, zerolinecolor=GRID, linecolor=BORDER, tickfont=dict(color=DIM), automargin=True)

pio.templates["bloomberg"] = go.layout.Template(
    layout=go.Layout(
        paper_bgcolor=BLACK,
        plot_bgcolor=BLACK,
        font=dict(family=FONT, color=TEXT, size=12),
        colorway=COLORWAY,
        title=dict(font=dict(color=AMBER, size=14)),
        xaxis=_axis,
        yaxis=_axis,
        legend=dict(bgcolor="rgba(0,0,0,0)", font=dict(color=TEXT)),
        hoverlabel=dict(bgcolor=PANEL, bordercolor=AMBER, font=dict(family=FONT, color=TEXT)),
        margin=dict(l=50, r=20, t=40, b=30),
    )
)
pio.templates.default = "bloomberg"


def empty_figure(message: str) -> go.Figure:
    fig = go.Figure()
    fig.add_annotation(text=message, showarrow=False, font=dict(color=DIM, size=14), xref="paper", yref="paper", x=0.5, y=0.5)
    fig.update_xaxes(visible=False)
    fig.update_yaxes(visible=False)
    return fig


# --- DataTable styling (dash_table ignores CSS for many inner elements, so pass style props) ---
TABLE_KW = dict(
    style_table={"overflowX": "auto"},
    style_header={
        "backgroundColor": PANEL, "color": AMBER, "fontWeight": "bold", "border": f"1px solid {BORDER}",
        "textTransform": "uppercase", "fontSize": "11px",
    },
    style_cell={
        "backgroundColor": BLACK, "color": TEXT, "border": f"1px solid {GRID}", "fontFamily": FONT,
        "fontSize": "12px", "padding": "3px 8px", "textAlign": "right", "minWidth": "60px",
    },
    style_cell_conditional=[{"if": {"column_type": "text"}, "textAlign": "left"}],
    style_filter={"backgroundColor": PANEL, "color": TEXT},
)


def status_conditional(col: str) -> list[dict]:
    """Colour a status column by its text: OK green, WARN yellow, STALE/FAIL/EMPTY red."""
    rules = []
    for word, colour in (("OK", UP), ("WARN", WARN), ("STALE", DOWN), ("FAIL", DOWN), ("EMPTY", DOWN)):
        rules.append({"if": {"filter_query": f'{{{col}}} = "{word}"', "column_id": col}, "color": colour, "fontWeight": "bold"})
    return rules
