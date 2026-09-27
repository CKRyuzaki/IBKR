"""Positions/P&L table for the Portfolio tab, fed live via the portfolio websocket topic."""

from __future__ import annotations

from dash import dash_table, html

_COLUMNS = [
    {"name": "Account", "id": "account"},
    {"name": "Symbol", "id": "symbol"},
    {"name": "Position", "id": "position"},
    {"name": "Avg Cost", "id": "avg_cost"},
    {"name": "Mkt Price", "id": "market_price"},
    {"name": "Mkt Value", "id": "market_value"},
    {"name": "Unrealized P&L", "id": "unrealized_pnl"},
    {"name": "Realized P&L", "id": "realized_pnl"},
]


def build_positions_table() -> html.Div:
    return html.Div(
        [dash_table.DataTable(id="positions-table", columns=_COLUMNS, data=[])],
        className="positions-table-wrapper",
    )


def build_account_summary_cards(cache: dict) -> list:
    tags = ["NetLiquidation", "BuyingPower", "UnrealizedPnL", "RealizedPnL", "GrossPositionValue"]
    cards = []
    for tag in tags:
        info = cache.get(tag, {})
        cards.append(
            html.Div(
                [
                    html.Div(tag, className="account-card-label"),
                    html.Div(
                        f"{info.get('value', '--')} {info.get('currency', '')}".strip(),
                        className="account-card-value",
                    ),
                ],
                className="account-card",
            )
        )
    return cards
