"""Callback translating incoming portfolio websocket messages (Position or AccountValue
payloads, see connection/portfolio_feed.py) into positions-table rows and account summary cards.
"""

from __future__ import annotations

import json
import logging

from dash import Dash, Input, Output, State
from dash.exceptions import PreventUpdate

from ibkr_dashboard.dash_app.components.positions_table import build_account_summary_cards

logger = logging.getLogger(__name__)


def register_portfolio_callbacks(app: Dash) -> None:
    @app.callback(
        Output("positions-cache", "data"),
        Output("positions-table", "data"),
        Output("account-cache", "data"),
        Output("account-summary-cards", "children"),
        Input("ws-portfolio", "message"),
        State("positions-cache", "data"),
        State("account-cache", "data"),
        prevent_initial_call=True,
    )
    def _on_portfolio_message(message, positions_cache, account_cache):
        if not message or not message.get("data"):
            raise PreventUpdate
        try:
            payload = json.loads(message["data"])
        except (TypeError, ValueError):
            logger.warning("Malformed portfolio websocket message ignored: %r", message)
            raise PreventUpdate

        positions_cache = dict(positions_cache or {})
        account_cache = dict(account_cache or {})

        if "tag" in payload:
            account_cache[payload["tag"]] = {"value": payload.get("value"), "currency": payload.get("currency")}
        elif "symbol" in payload:
            positions_cache[payload.get("instrument_id", payload["symbol"])] = payload
        else:
            raise PreventUpdate

        return (
            positions_cache,
            list(positions_cache.values()),
            account_cache,
            build_account_summary_cards(account_cache),
        )
