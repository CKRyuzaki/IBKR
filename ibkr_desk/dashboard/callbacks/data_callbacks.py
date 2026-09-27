"""DATA tab callbacks: snapshot health, dataset controls, and the explorer plot + table."""

from __future__ import annotations

import logging

import pandas as pd
import plotly.graph_objects as go
from dash import Dash, Input, Output, State, ctx, html, no_update
from plotly.subplots import make_subplots

from ibkr_desk.core.config import PostgresConfig
from ibkr_desk.dashboard import data_access as da
from ibkr_desk.dashboard import theme

logger = logging.getLogger(__name__)

OHLC = ("open", "high", "low", "close")
SNAPSHOT_STALE_H = 36  # the job runs daily; older than this means a run was missed


def _opts(values: list[str]) -> list[dict]:
    return [{"label": v, "value": v} for v in values]


def _health_banner(cfg: PostgresConfig, rows: list[dict]):
    stale = [r for r in rows if r["status"] in ("STALE", "EMPTY")]
    warn = [r for r in rows if r["status"] == "WARN"]
    hrs = da.hours_since_last_run(cfg)
    msgs, level = [], "ok"
    if hrs is None:
        msgs.append("No snapshot job has recorded a run yet (ops.snapshot_run is empty).")
        level = "warn"
    elif hrs > SNAPSHOT_STALE_H:
        msgs.append(f"Last snapshot run was {hrs:.0f}h ago — a daily run was missed.")
        level = "bad"
    else:
        msgs.append(f"Last snapshot run {hrs:.1f}h ago.")
    if stale:
        msgs.append("STALE/EMPTY: " + ", ".join(f"{r['key'] or r['dataset']}" for r in stale))
        level = "bad"
    elif warn:
        msgs.append("Lagging: " + ", ".join(f"{r['key'] or r['dataset']}" for r in warn))
        level = "warn" if level == "ok" else level
    if level == "ok":
        msgs.append("All datasets up to date.")
    return html.Div(" ".join(msgs), className=f"banner {level}")


def register_data_callbacks(app: Dash, pg: PostgresConfig) -> None:
    # ---- snapshot health -------------------------------------------------------------------
    @app.callback(
        Output("data-banner", "children"),
        Output("health-table", "data"),
        Output("runs-table", "data"),
        Input("data-interval", "n_intervals"),
        Input("data-refresh", "n_clicks"),
    )
    def _health(_n, _clicks):
        try:
            rows = da.freshness(pg)
            runs = da.snapshot_runs(pg)
            return _health_banner(pg, rows), rows, runs
        except Exception as exc:  # noqa: BLE001 -- show the problem instead of a blank panel
            logger.warning("health query failed: %s", exc)
            return html.Div(da.postgres_error(exc), className="banner bad"), [], []

    # ---- explorer controls -------------------------------------------------------------------
    @app.callback(
        Output("ex-key1", "options"), Output("ex-key1", "value"), Output("ex-key1-label", "children"),
        Output("ex-key2", "options"), Output("ex-key2", "value"), Output("ex-key2-label", "children"),
        Output("ex-key2-wrap", "style"), Output("ex-type-wrap", "style"),
        Output("ex-cols", "options"), Output("ex-cols", "value"),
        Input("ex-dataset", "value"), Input("ex-key1", "value"),
        State("ex-key2", "value"),
    )
    def _controls(ds_key, key1, key2):
        ds = da.DATASETS[ds_key]
        try:
            if ctx.triggered_id == "ex-key1":  # only the dependent key changes
                k2 = da.distinct_values(pg, ds, ds.keys[1][0], {ds.keys[0][0]: key1}) if len(ds.keys) > 1 else []
                return (no_update,) * 3 + (_opts(k2), da.default_key(pg, ds, 1, k2, key1), no_update) + (no_update,) * 4
            k1_all = da.distinct_values(pg, ds, ds.keys[0][0])
            k1 = da.default_key(pg, ds, 0, k1_all)
            k2_all = da.distinct_values(pg, ds, ds.keys[1][0], {ds.keys[0][0]: k1}) if len(ds.keys) > 1 else []
        except Exception as exc:  # noqa: BLE001
            logger.warning("explorer controls failed: %s", exc)
            k1_all, k1, k2_all = [], None, []
        cols_default = ["close"] if "close" in ds.value_cols else [ds.value_cols[0]]
        return (
            _opts(k1_all), k1, ds.keys[0][1],
            _opts(k2_all), da.default_key(pg, ds, 1, k2_all, k1), ds.keys[1][1] if len(ds.keys) > 1 else "",
            {} if len(ds.keys) > 1 else {"display": "none"},
            {} if ds.ohlc else {"display": "none"},
            _opts(list(ds.value_cols)), cols_default,
        )

    # ---- explorer plot + table -----------------------------------------------------------------
    @app.callback(
        Output("ex-graph", "figure"), Output("ex-table", "columns"), Output("ex-table", "data"),
        Output("ex-info", "children"),
        Input("ex-dataset", "value"), Input("ex-key1", "value"), Input("ex-key2", "value"),
        Input("ex-range", "value"), Input("ex-type", "value"), Input("ex-cols", "value"),
        Input("data-refresh", "n_clicks"),
    )
    def _explore(ds_key, key1, key2, range_key, chart_type, cols, _clicks):
        ds = da.DATASETS[ds_key]
        keys = {ds.keys[0][0]: key1}
        if len(ds.keys) > 1:
            keys[ds.keys[1][0]] = key2
        if not key1:
            return theme.empty_figure("No data for this dataset yet"), [], [], ""
        try:
            df = da.fetch_series(pg, ds, keys, range_key)
        except Exception as exc:  # noqa: BLE001
            return theme.empty_figure(da.postgres_error(exc)), [], [], da.postgres_error(exc)
        if df.empty:
            return theme.empty_figure("No rows in this range"), [], [], "0 rows"

        title = " · ".join(str(v) for v in keys.values() if v)
        fig = _figure(df, ds, chart_type, cols or [], title)
        table = df.sort_values("date", ascending=False).copy()
        table["date"] = table["date"].astype(str)
        columns = [{"name": c, "id": c, "type": "text" if c == "date" else "numeric",
                    "format": {"specifier": ",.4f" if c != "volume" else ",.0f"}} for c in table.columns]
        info = f"{len(df):,} rows · {df['date'].min()} → {df['date'].max()} · {title}"
        return fig, columns, table.to_dict("records"), info


def _figure(df: pd.DataFrame, ds: da.Dataset, chart_type: str, cols: list[str], title: str) -> go.Figure:
    has_volume = "volume" in df.columns and df["volume"].notna().any()
    if ds.ohlc and chart_type == "candle" and all(c in df.columns and df[c].notna().any() for c in OHLC):
        fig = make_subplots(rows=2 if has_volume else 1, cols=1, shared_xaxes=True, vertical_spacing=0.03,
                            row_heights=[0.75, 0.25] if has_volume else [1])
        fig.add_trace(go.Candlestick(
            x=df["date"], open=df["open"], high=df["high"], low=df["low"], close=df["close"], name=title,
            increasing_line_color=theme.UP, decreasing_line_color=theme.DOWN,
            increasing_fillcolor=theme.UP, decreasing_fillcolor=theme.DOWN), row=1, col=1)
        if has_volume:
            fig.add_trace(go.Bar(x=df["date"], y=df["volume"], name="volume", marker_color=theme.AMBER, opacity=0.6), row=2, col=1)
        fig.update_layout(xaxis_rangeslider_visible=False, showlegend=False)
    else:
        fig = go.Figure()
        for c in cols or [ds.value_cols[0]]:
            if c in df.columns:
                fig.add_trace(go.Scatter(x=df["date"], y=df[c], mode="lines", name=c, line={"width": 1.5}))
    fig.update_layout(title=title, hovermode="x unified", uirevision=title, margin={"l": 55, "r": 20, "t": 40, "b": 30})
    return fig
