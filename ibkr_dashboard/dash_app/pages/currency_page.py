"""Factory for a single GP-style currency page, reused across all G10 currencies.

Component ids use Dash's dict/pattern-matching id form ({"type": ..., "ccy": ...}) so one set
of callbacks (registered once in callbacks/chart_callbacks.py) drives every currency page,
instead of registering near-duplicate callbacks per currency.
"""

from __future__ import annotations

from dash import dcc, html
from dash_extensions import WebSocket

from ibkr_dashboard.connection.contracts import CurrencyUniverse, equity_instrument_id, index_instrument_id
from ibkr_dashboard.dash_app.components.price_chart import build_initial_figure
from ibkr_dashboard.dash_app.components.quote_ticker import build_quote_ticker
from ibkr_dashboard.dash_app.components.swap_curve_panel import build_swap_curve_panel
from ibkr_dashboard.swaps.models import RatesSwapInstrument


def build_currency_layout(universe: CurrencyUniverse, ws_url: str) -> html.Div:
    ccy = universe.currency

    instrument_labels: list[tuple[str, str]] = []
    if universe.index:
        instrument_labels.append(
            (index_instrument_id(ccy, universe.index.symbol), universe.index.display_name or universe.index.symbol)
        )
    for eq in universe.equities:
        instrument_labels.append((equity_instrument_id(ccy, eq.symbol), eq.display_name or eq.symbol))

    quote_cache = {iid: {"label": label, "bid": None, "ask": None, "last": None} for iid, label in instrument_labels}
    default_instrument_id = instrument_labels[0][0] if instrument_labels else None
    default_title = instrument_labels[0][1] if instrument_labels else ccy

    swap_placeholders = [
        RatesSwapInstrument(
            currency=ccy, index_basis=s.index_basis, tenor=s.tenor, leg_description=s.leg_description
        )
        for s in universe.swaps
    ]

    return html.Div(
        [
            WebSocket(id={"type": "ws", "ccy": ccy}, url=ws_url),
            dcc.Store(id={"type": "quote-cache", "ccy": ccy}, data=quote_cache),
            dcc.Store(id={"type": "active-instrument", "ccy": ccy}, data=default_instrument_id),
            html.H2(f"{ccy} Desk"),
            html.Div(id={"type": "quote-ticker", "ccy": ccy}, children=build_quote_ticker(quote_cache)),
            dcc.Dropdown(
                id={"type": "instrument-select", "ccy": ccy},
                options=[{"label": label, "value": iid} for iid, label in instrument_labels],
                value=default_instrument_id,
                clearable=False,
                style={"width": "320px", "marginBottom": "8px"},
            ),
            dcc.Graph(
                id={"type": "price-chart", "ccy": ccy},
                figure=build_initial_figure(title=default_title, x=[], y=[]),
                style={"height": "480px"},
            ),
            build_swap_curve_panel(ccy, swap_placeholders),
        ],
        className="currency-page",
    )
