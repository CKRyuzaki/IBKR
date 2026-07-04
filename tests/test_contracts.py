from pathlib import Path

from ib_async import Index, Stock

from ibkr_dashboard.connection.contracts import (
    build_contract_for_equity,
    build_contract_for_index,
    equity_instrument_id,
    index_instrument_id,
    instruments_for_universe,
    load_currency_universe,
)

INSTRUMENTS_DIR = Path(__file__).resolve().parent.parent / "config" / "instruments"


def test_load_usd_universe():
    universe = load_currency_universe("USD", INSTRUMENTS_DIR)
    assert universe.currency == "USD"
    assert universe.index.symbol == "SPX"
    assert len(universe.equities) >= 2
    assert any(s.index_basis == "SOFR_OIS" for s in universe.swaps)


def test_build_contract_for_equity_and_index():
    universe = load_currency_universe("USD", INSTRUMENTS_DIR)
    stock = build_contract_for_equity(universe.equities[0], universe.currency)
    assert isinstance(stock, Stock)
    assert stock.currency == "USD"

    index = build_contract_for_index(universe.index, universe.currency)
    assert isinstance(index, Index)
    assert index.symbol == "SPX"


def test_instrument_ids_are_namespaced_by_currency():
    assert equity_instrument_id("USD", "AAPL") == "USD.EQ.AAPL"
    assert index_instrument_id("EUR", "ESTX50") == "EUR.IDX.ESTX50"


def test_instruments_for_universe_excludes_swaps():
    universe = load_currency_universe("EUR", INSTRUMENTS_DIR)
    instruments = instruments_for_universe(universe)
    assert all("SWAP" not in inst.instrument_id for inst in instruments)
    assert len(instruments) == 1 + len(universe.equities) + len(universe.rate_proxy_futures)
