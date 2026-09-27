"""Portfolio tab: live positions + account summary, fed by connection/portfolio_feed.py via
the "portfolio" websocket topic."""

from __future__ import annotations

from dash import dcc, html
from dash_extensions import WebSocket

from ibkr_desk.dashboard.components.positions_table import build_account_summary_cards, build_positions_table


def build_portfolio_layout(ws_url: str) -> html.Div:
    account_cache: dict = {}
    return html.Div(
        [
            WebSocket(id="ws-portfolio", url=ws_url),
            dcc.Store(id="positions-cache", data={}),
            dcc.Store(id="account-cache", data=account_cache),
            html.H2("Portfolio (paper account by default)"),
            html.Div(id="account-summary-cards", children=build_account_summary_cards(account_cache), className="account-summary"),
            build_positions_table(),
        ],
        className="portfolio-page",
    )
