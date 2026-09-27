"""Dash app factory: header (connection chips) + tabs LIVE | CHARTS | PORTFOLIO | DATA | STATUS.

- LIVE       blotter of every subscribed instrument, refreshed from the server-side QuoteBook.
- CHARTS     one GP-style page per G10 currency; real-time pushes come from ws_server.py via the
             dash-extensions WebSocket component, not dcc.Interval polling.
- PORTFOLIO  positions + account summary (websocket).
- DATA       Postgres snapshot health + time-series explorer (plot and table).
- STATUS     connection state of every registered provider (core/providers.py).
The dashboard only reads: it never places orders.
"""

from __future__ import annotations

from pathlib import Path

from dash import Dash, dcc, html

from ibkr_desk.dashboard import theme  # noqa: F401  (registers the "bloomberg" plotly template)
from ibkr_desk.dashboard.callbacks.chart_callbacks import register_chart_callbacks
from ibkr_desk.dashboard.callbacks.data_callbacks import register_data_callbacks
from ibkr_desk.dashboard.callbacks.live_callbacks import register_live_callbacks
from ibkr_desk.dashboard.callbacks.portfolio_callbacks import register_portfolio_callbacks
from ibkr_desk.dashboard.callbacks.status_callbacks import register_status_callbacks
from ibkr_desk.dashboard.pages.currency_page import build_currency_layout
from ibkr_desk.dashboard.pages.data_page import build_data_layout
from ibkr_desk.dashboard.pages.live_page import build_live_layout
from ibkr_desk.dashboard.pages.portfolio_page import build_portfolio_layout
from ibkr_desk.dashboard.pages.status_page import build_status_layout
from ibkr_desk.live.quote_book import QuoteBook
from ibkr_desk.settings import Settings
from ibkr_desk.storage.sqlite import Storage
from ibkr_desk.universe import CurrencyUniverse

ASSETS_DIR = Path(__file__).resolve().parent / "assets"


def _tab(label: str, value: str, children, sub: bool = False) -> dcc.Tab:
    cls = "bb-tab-sub" if sub else "bb-tab"
    return dcc.Tab(label=label, value=value, className=cls, selected_className=f"{cls}--selected", children=children)


def build_app(
    universes: dict[str, CurrencyUniverse],
    storage: Storage,
    ws_host: str,
    ws_port: int,
    settings: Settings,
    quote_book: QuoteBook,
) -> Dash:
    app = Dash(__name__, assets_folder=str(ASSETS_DIR), suppress_callback_exceptions=True, title="IBKR DESK")

    ccy_tabs = [
        _tab(ccy, f"ccy-{ccy}", build_currency_layout(u, f"ws://{ws_host}:{ws_port}/ws/currency/{ccy}"), sub=True)
        for ccy, u in universes.items()
    ]
    charts = html.Div(
        dcc.Tabs(id="ccy-tabs", value=f"ccy-{next(iter(universes))}" if universes else None,
                 children=ccy_tabs, parent_className="bb-tabs", className="bb-tabs"),
        className="page",
    )

    app.layout = html.Div(
        [
            dcc.Interval(id="hdr-interval", interval=2000),
            html.Div(
                [
                    html.Span("IBKR DESK", className="hdr-title"),
                    html.Span(f"{settings.ibkr.mode.upper()} · read-only dashboard", className="hdr-mode"),
                    html.Div(id="hdr-chips", className="chips"),
                    html.Span(className="hdr-spacer"),
                    html.Span(id="hdr-clock", className="hdr-clock"),
                ],
                className="hdr",
            ),
            dcc.Tabs(
                id="main-tabs", value=settings.dashboard.default_tab, parent_className="bb-tabs", className="bb-tabs",
                children=[
                    _tab("LIVE", "live", build_live_layout(list(universes))),
                    _tab("CHARTS", "charts", charts),
                    _tab("PORTFOLIO", "portfolio", build_portfolio_layout(f"ws://{ws_host}:{ws_port}/ws/portfolio")),
                    _tab("DATA", "data", build_data_layout()),
                    _tab("STATUS", "status", build_status_layout()),
                ],
            ),
        ],
        className="app-shell",
    )

    register_status_callbacks(app)
    register_live_callbacks(app, quote_book)
    register_data_callbacks(app, settings.postgres)
    register_chart_callbacks(app, storage)
    register_portfolio_callbacks(app)
    return app
