"""LIVE tab: blotter of every subscribed instrument (bid/ask/last/spread/age) plus a tick chart of
the selected row. Read-only: it only displays what the market-data providers publish."""

from __future__ import annotations

from dash import dash_table, dcc, html

from ibkr_desk.dashboard import theme

COLUMNS = [
    {"name": "Ccy", "id": "ccy", "type": "text"},
    {"name": "Instrument", "id": "name", "type": "text"},
    {"name": "Bid", "id": "bid", "type": "numeric", "format": {"specifier": ".4f"}},
    {"name": "Ask", "id": "ask", "type": "numeric", "format": {"specifier": ".4f"}},
    {"name": "Last", "id": "last", "type": "numeric", "format": {"specifier": ".4f"}},
    {"name": "Spread", "id": "spread", "type": "numeric", "format": {"specifier": ".4f"}},
    {"name": "", "id": "dir", "type": "text"},
    {"name": "Age (s)", "id": "age_s", "type": "numeric"},
]

STALE_AFTER_S = 120


def build_live_layout(currencies: list[str]) -> html.Div:
    return html.Div(
        [
            dcc.Interval(id="live-interval", interval=500),
            html.Div(id="live-banner"),
            html.Div(
                [
                    html.Div(
                        [
                            html.Label("Currency"),
                            dcc.Dropdown(
                                id="live-ccy", multi=True, placeholder="ALL",
                                options=[{"label": c, "value": c} for c in currencies],
                            ),
                        ],
                        className="control", style={"minWidth": "280px"},
                    ),
                    html.Div("Click a row to chart its ticks.", className="muted"),
                ],
                className="controls",
            ),
            html.Div(
                [
                    html.Div("Live quotes", className="panel-title"),
                    dash_table.DataTable(
                        id="live-table", columns=COLUMNS, data=[], sort_action="native", page_action="none",
                        style_data_conditional=[
                            {"if": {"filter_query": '{dir} = "▲"', "column_id": ["dir", "last"]}, "color": theme.UP},
                            {"if": {"filter_query": '{dir} = "▼"', "column_id": ["dir", "last"]}, "color": theme.DOWN},
                            {"if": {"column_id": "bid"}, "color": theme.DOWN},
                            {"if": {"column_id": "ask"}, "color": theme.UP},
                            {"if": {"column_id": "name"}, "color": theme.AMBER},
                            {"if": {"filter_query": f"{{age_s}} > {STALE_AFTER_S}", "column_id": "age_s"}, "color": theme.WARN},
                            {"if": {"filter_query": "{age_s} is nil", "column_id": "age_s"}, "color": theme.DIM},
                            {"if": {"state": "active"}, "backgroundColor": "#2a1c00", "border": f"1px solid {theme.AMBER}"},
                        ],
                        **{**theme.TABLE_KW, "style_table": {"maxHeight": "380px", "overflowY": "auto", "overflowX": "auto"}},
                        fixed_rows={"headers": True},
                    ),
                ],
                className="panel",
            ),
            html.Div(
                [
                    html.Div("Tick chart", id="live-chart-title", className="panel-title"),
                    dcc.Graph(id="live-chart", style={"height": "320px"}, config={"displaylogo": False}),
                ],
                className="panel",
            ),
        ],
        className="page",
    )
