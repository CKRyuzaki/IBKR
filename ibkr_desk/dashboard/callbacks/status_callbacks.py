"""Header chips (always visible) and the STATUS tab cards, driven by the provider registry."""

from __future__ import annotations

from dash import Dash, Input, Output

from ibkr_desk.core.providers import registry
from ibkr_desk.dashboard.pages import status_page


def register_status_callbacks(app: Dash) -> None:
    @app.callback(
        Output("hdr-chips", "children"),
        Output("hdr-clock", "children"),
        Input("hdr-interval", "n_intervals"),
    )
    def _header(_n):
        return status_page.chips(registry.statuses()), status_page.clock()

    @app.callback(Output("status-cards", "children"), Input("status-page-interval", "n_intervals"))
    def _cards(_n):
        return status_page.cards(registry.statuses())
