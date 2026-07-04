"""Callbacks translating incoming websocket tick messages (see dash_app/ws_server.py) into
Patch()-based chart/quote updates -- the mechanism that keeps pan/zoom/crosshair state intact
while live ticks stream in, instead of a Streamlit-style full rerun. Registered once with
MATCH pattern-matching ids so the same callbacks drive every currency page.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone

from dash import MATCH, Dash, Input, Output, State, no_update
from dash.exceptions import PreventUpdate

from ibkr_dashboard.dash_app.components.price_chart import append_point_patch, build_initial_figure
from ibkr_dashboard.dash_app.components.quote_ticker import build_quote_ticker_children
from ibkr_dashboard.data.storage import Storage

logger = logging.getLogger(__name__)


def register_chart_callbacks(app: Dash, storage: Storage) -> None:
    @app.callback(
        Output({"type": "quote-cache", "ccy": MATCH}, "data"),
        Output({"type": "quote-ticker", "ccy": MATCH}, "children"),
        Output({"type": "price-chart", "ccy": MATCH}, "figure"),
        Input({"type": "ws", "ccy": MATCH}, "message"),
        State({"type": "quote-cache", "ccy": MATCH}, "data"),
        State({"type": "active-instrument", "ccy": MATCH}, "data"),
        prevent_initial_call=True,
    )
    def _on_tick(message, cache, active_instrument_id):
        if not message or not message.get("data"):
            raise PreventUpdate
        try:
            tick = json.loads(message["data"])
        except (TypeError, ValueError):
            logger.warning("Malformed websocket message ignored: %r", message)
            raise PreventUpdate

        instrument_id = tick.get("instrument_id")
        tick_field = tick.get("field")
        value = tick.get("value")
        ts = tick.get("ts")
        if instrument_id is None or tick_field not in ("bid", "ask", "last"):
            raise PreventUpdate

        cache = dict(cache or {})
        entry = dict(cache.get(instrument_id, {}))
        entry[tick_field] = value
        cache[instrument_id] = entry

        ticker_children = build_quote_ticker_children(cache)

        figure_update = no_update
        if instrument_id == active_instrument_id and tick_field == "last":
            x_value = datetime.fromisoformat(ts) if ts else datetime.now(timezone.utc)
            figure_update = append_point_patch(x_value, value)

        return cache, ticker_children, figure_update

    @app.callback(
        Output({"type": "active-instrument", "ccy": MATCH}, "data"),
        Output({"type": "price-chart", "ccy": MATCH}, "figure", allow_duplicate=True),
        Input({"type": "instrument-select", "ccy": MATCH}, "value"),
        prevent_initial_call=True,
    )
    def _on_instrument_change(instrument_id):
        if not instrument_id:
            raise PreventUpdate
        end = datetime.now(timezone.utc)
        start = end - timedelta(days=1)
        bars = storage.query_bars(instrument_id, "1 min", start, end)
        x = [b.ts for b in bars]
        y = [b.close for b in bars]
        figure = build_initial_figure(title=instrument_id, x=x, y=y)
        return instrument_id, figure
