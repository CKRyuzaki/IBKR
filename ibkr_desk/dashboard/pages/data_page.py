"""DATA tab: is the Postgres archive healthy, and what is in it?

Top: snapshot health -- per-dataset freshness plus the log of the daily snapshot job, so a failed
or missed snapshot is obvious. Bottom: an explorer showing any dataset as a plot AND a table.
"""

from __future__ import annotations

from dash import dash_table, dcc, html

from ibkr_desk.dashboard import theme
from ibkr_desk.dashboard.data_access import DATASETS, RANGES

HEALTH_COLUMNS = [
    {"name": "Dataset", "id": "dataset", "type": "text"},
    {"name": "Key", "id": "key", "type": "text"},
    {"name": "Rows", "id": "rows", "type": "numeric", "format": {"specifier": ","}},
    {"name": "First", "id": "first", "type": "text"},
    {"name": "Last", "id": "last", "type": "text"},
    {"name": "Lag (bd)", "id": "lag_bd", "type": "numeric"},
    {"name": "Status", "id": "status", "type": "text"},
]
RUN_COLUMNS = [
    {"name": "Run at", "id": "run_at", "type": "text"},
    {"name": "Step", "id": "step", "type": "text"},
    {"name": "Status", "id": "status", "type": "text"},
    {"name": "Detail", "id": "detail", "type": "text"},
]


def _control(label: str, child, **style) -> html.Div:
    return html.Div([html.Label(label), child], className="control", style=style or None)


def build_data_layout() -> html.Div:
    first = next(iter(DATASETS.values()))
    return html.Div(
        [
            dcc.Interval(id="data-interval", interval=30_000),
            html.Div(id="data-banner"),
            html.Div(
                [
                    html.Div(
                        [html.Span("Snapshot health"), html.Button("Refresh", id="data-refresh", className="btn", n_clicks=0)],
                        className="panel-title",
                    ),
                    dash_table.DataTable(
                        id="health-table", columns=HEALTH_COLUMNS, data=[], sort_action="native", page_action="none",
                        style_data_conditional=theme.status_conditional("status"), **theme.TABLE_KW,
                    ),
                ],
                className="panel",
            ),
            html.Div(
                [
                    html.Div("Snapshot job log (ops.snapshot_run)", className="panel-title"),
                    dash_table.DataTable(
                        id="runs-table", columns=RUN_COLUMNS, data=[], page_size=8,
                        style_data_conditional=theme.status_conditional("status"),
                        style_cell_conditional=[{"if": {"column_id": c}, "textAlign": "left"} for c in ("run_at", "step", "status", "detail")],
                        **{k: v for k, v in theme.TABLE_KW.items() if k != "style_cell_conditional"},
                    ),
                ],
                className="panel",
            ),
            html.Div(
                [
                    html.Div("Explorer", className="panel-title"),
                    html.Div(
                        [
                            html.Div(
                                [
                                    _control("Dataset", dcc.Dropdown(
                                        id="ex-dataset", clearable=False, value=first.key,
                                        options=[{"label": d.label, "value": d.key} for d in DATASETS.values()]), minWidth="260px"),
                                    html.Div(id="ex-key1-wrap", className="control", children=[
                                        html.Label("Key", id="ex-key1-label"), dcc.Dropdown(id="ex-key1", clearable=False)]),
                                    html.Div(id="ex-key2-wrap", className="control", children=[
                                        html.Label("Key 2", id="ex-key2-label"), dcc.Dropdown(id="ex-key2", clearable=False)]),
                                    _control("Range", dcc.Dropdown(
                                        id="ex-range", clearable=False, value="1Y",
                                        options=[{"label": r, "value": r} for r in RANGES]), minWidth="110px"),
                                    html.Div(id="ex-type-wrap", className="control", children=[
                                        html.Label("Chart"),
                                        dcc.RadioItems(id="ex-type", value="candle", className="radio", inline=True,
                                                       options=[{"label": "Candles", "value": "candle"}, {"label": "Line", "value": "line"}])]),
                                    _control("Columns (line)", dcc.Dropdown(id="ex-cols", multi=True), minWidth="260px"),
                                ],
                                className="controls",
                            ),
                            html.Div(id="ex-info", className="muted", style={"marginBottom": "6px"}),
                            dcc.Graph(id="ex-graph", style={"height": "420px"}, config={"displaylogo": False}),
                            html.Div("Table (newest first)", className="panel-title", style={"marginTop": "10px"}),
                            dash_table.DataTable(
                                id="ex-table", columns=[], data=[], page_size=15, sort_action="native",
                                export_format="csv", **theme.TABLE_KW,
                            ),
                        ],
                        className="panel-body",
                    ),
                ],
                className="panel",
            ),
        ],
        className="page",
    )
