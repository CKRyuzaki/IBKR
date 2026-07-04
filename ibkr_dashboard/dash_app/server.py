"""Dash app factory: builds the tab layout (one per G10 currency + Portfolio) and registers
all callbacks. Real-time pushes come from ws_server.py via the dash-extensions WebSocket
component embedded in each page, not from dcc.Interval polling.
"""

from __future__ import annotations

from pathlib import Path

from dash import Dash, dcc, html

from ibkr_dashboard.connection.contracts import CurrencyUniverse
from ibkr_dashboard.dash_app.callbacks.chart_callbacks import register_chart_callbacks
from ibkr_dashboard.dash_app.callbacks.portfolio_callbacks import register_portfolio_callbacks
from ibkr_dashboard.dash_app.pages.currency_page import build_currency_layout
from ibkr_dashboard.dash_app.pages.portfolio_page import build_portfolio_layout
from ibkr_dashboard.data.storage import Storage

ASSETS_DIR = Path(__file__).resolve().parent / "assets"


def build_app(
    universes: dict[str, CurrencyUniverse],
    storage: Storage,
    ws_host: str,
    ws_port: int,
) -> Dash:
    app = Dash(__name__, assets_folder=str(ASSETS_DIR), suppress_callback_exceptions=True)
    app.title = "IBKR G10 RV Desk"

    tabs = []
    for ccy, universe in universes.items():
        ws_url = f"ws://{ws_host}:{ws_port}/ws/currency/{ccy}"
        tabs.append(dcc.Tab(label=ccy, value=f"tab-{ccy}", children=[build_currency_layout(universe, ws_url)]))
    tabs.append(
        dcc.Tab(
            label="Portfolio",
            value="tab-portfolio",
            children=[build_portfolio_layout(f"ws://{ws_host}:{ws_port}/ws/portfolio")],
        )
    )

    first_ccy = next(iter(universes), None)
    app.layout = html.Div(
        [
            html.H1("IBKR G10 RV Desk (paper account by default)"),
            dcc.Tabs(
                id="main-tabs",
                value=f"tab-{first_ccy}" if first_ccy else "tab-portfolio",
                children=tabs,
            ),
        ],
        className="app-shell",
    )

    register_chart_callbacks(app, storage)
    register_portfolio_callbacks(app)
    return app
