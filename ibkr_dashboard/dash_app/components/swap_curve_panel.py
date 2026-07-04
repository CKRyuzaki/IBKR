"""Swap/IRS curve panel -- always visibly labeled as a placeholder until a real adapter is
wired in (see ibkr_dashboard/swaps/adapter.py)."""

from __future__ import annotations

from dash import dash_table, html

from ibkr_dashboard.swaps.models import RatesSwapInstrument


def build_swap_curve_panel(currency: str, swaps: list[RatesSwapInstrument]) -> html.Div:
    columns = [
        {"name": "Tenor", "id": "tenor"},
        {"name": "Basis", "id": "index_basis"},
        {"name": "Bid", "id": "bid"},
        {"name": "Ask", "id": "ask"},
        {"name": "Mid", "id": "mid"},
    ]
    data = [
        {
            "tenor": s.tenor,
            "index_basis": s.index_basis,
            "bid": s.bid if s.bid is not None else "--",
            "ask": s.ask if s.ask is not None else "--",
            "mid": s.mid if s.mid is not None else "--",
        }
        for s in swaps
    ]
    return html.Div(
        [
            html.Div(
                "Swap/IRS data is not wired to a live source yet -- placeholder rows only. "
                "See ibkr_dashboard/swaps/adapter.py.",
                className="swap-stub-banner",
            ),
            dash_table.DataTable(
                id=f"swap-table-{currency}",
                columns=columns,
                data=data,
                style_cell={"textAlign": "center"},
            ),
        ],
        className="swap-curve-panel",
    )
