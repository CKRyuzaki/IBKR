"""GP-style (Bloomberg Graph-Price-like) Plotly price chart.

Range-selector buttons + range-slider + unified crosshover give the pan/zoom/crosshair feel the
user asked for natively via Plotly.js, no extra JS needed. `uirevision` plus using `Patch()` for
live ticks (rather than replacing the whole figure) is what keeps the user's zoom/pan state
intact while data streams in.
"""

from __future__ import annotations

from datetime import datetime

import plotly.graph_objects as go
from dash import Patch

RANGE_BUTTONS = [
    {"count": 1, "label": "1D", "step": "day", "stepmode": "backward"},
    {"count": 5, "label": "5D", "step": "day", "stepmode": "backward"},
    {"count": 1, "label": "1M", "step": "month", "stepmode": "backward"},
    {"count": 6, "label": "6M", "step": "month", "stepmode": "backward"},
    {"count": 1, "label": "1Y", "step": "year", "stepmode": "backward"},
    {"step": "all", "label": "All"},
]


def build_initial_figure(title: str, x: list[datetime], y: list[float]) -> go.Figure:
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=list(x), y=list(y), mode="lines", name=title, line={"width": 1.5}))
    fig.update_layout(
        title=title,
        margin={"l": 40, "r": 20, "t": 40, "b": 20},
        hovermode="x unified",
        xaxis={
            "rangeselector": {"buttons": RANGE_BUTTONS},
            "rangeslider": {"visible": True},
            "showspikes": True,
            "spikemode": "across",
            "spikesnap": "cursor",
        },
        yaxis={"showspikes": True, "spikemode": "across"},
        uirevision=title,
        template="plotly_dark",
    )
    return fig


def append_point_patch(x_value: datetime, y_value: float, trace_index: int = 0) -> Patch:
    patch = Patch()
    patch["data"][trace_index]["x"].append(x_value)
    patch["data"][trace_index]["y"].append(y_value)
    return patch
