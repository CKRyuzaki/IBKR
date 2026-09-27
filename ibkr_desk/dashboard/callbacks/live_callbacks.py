"""LIVE tab callbacks: refresh the blotter + banner from the QuoteBook, chart the selected row."""

from __future__ import annotations

from datetime import datetime, timezone

import plotly.graph_objects as go
from dash import Dash, Input, Output
from dash import html

from ibkr_desk.core.providers import ConnState, registry
from ibkr_desk.dashboard import theme
from ibkr_desk.dashboard.pages.live_page import STALE_AFTER_S
from ibkr_desk.dashboard.pages.status_page import _dur
from ibkr_desk.live.quote_book import QuoteBook


def _banner(rows: list[dict]):
    feeds = [s for s in registry.statuses() if s.kind == "market_data"]
    down = [s for s in feeds if s.state in (ConnState.DISCONNECTED, ConnState.ERROR)]
    ages = [r["age_s"] for r in rows if r["age_s"] is not None]
    if down:
        names = ", ".join(s.name for s in down)
        return html.Div(f"{names} DISCONNECTED — showing last known quotes. {down[0].detail}", className="banner bad")
    if not rows:
        return html.Div("No instruments subscribed.", className="banner warn")
    if not ages:
        return html.Div("Connected — waiting for the first tick…", className="banner warn")
    if min(ages) > STALE_AFTER_S:
        return html.Div(
            f"Connected but no ticks for {_dur(min(ages))} — market may be closed, or the market-data "
            "subscription is missing.", className="banner warn")
    return html.Div(f"{len(ages)}/{len(rows)} instruments ticking · last tick {_dur(min(ages))} ago", className="banner ok")


def register_live_callbacks(app: Dash, book: QuoteBook) -> None:
    @app.callback(
        Output("live-table", "data"),
        Output("live-banner", "children"),
        Input("live-interval", "n_intervals"),
        Input("live-ccy", "value"),
    )
    def _table(_n, ccys):
        rows = sorted(book.snapshot(), key=lambda r: (r["ccy"], r["name"]))
        if ccys:
            rows = [r for r in rows if r["ccy"] in ccys]
        return rows, _banner(rows)

    @app.callback(
        Output("live-chart", "figure"),
        Output("live-chart-title", "children"),
        Input("live-interval", "n_intervals"),
        Input("live-table", "active_cell"),
    )
    def _chart(_n, active_cell):
        iid = active_cell.get("row_id") if active_cell else None
        if iid is None:  # default: the instrument with the most ticks so far
            snap = {r["id"]: len(book.history(r["id"])) for r in book.snapshot()}
            iid = max(snap, key=snap.get) if snap else None
        hist = book.history(iid) if iid else []
        if not hist:
            return theme.empty_figure("Select an instrument once ticks are flowing"), "Tick chart"
        x = [datetime.fromtimestamp(t, tz=timezone.utc) for t, _ in hist]
        y = [p for _, p in hist]
        fig = go.Figure(go.Scatter(x=x, y=y, mode="lines", line={"color": theme.AMBER, "width": 1.5}, name=iid))
        fig.update_layout(uirevision=iid, margin={"l": 50, "r": 20, "t": 10, "b": 30}, hovermode="x unified")
        return fig, f"Tick chart — {iid} ({len(hist)} ticks)"
