"""Loads per-currency instrument universe YAML files and builds ib_async Contract objects.

Equities/indices/futures are "real" -- built into genuine ib_async Contract objects that get
qualified and subscribed against IBKR. Swap entries are data-only (see ibkr_desk.swaps) and
never turn into an ib_async Contract here, since we don't have a verified IBKR contract spec for
OTC swaps yet.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from ib_async import Contract
from pydantic import BaseModel

from ibkr_desk.core.ib import contracts as ibc
from ibkr_desk.core.models import AssetClass, Instrument


class EquityEntry(BaseModel):
    symbol: str
    exchange: str = "SMART"
    primary_exchange: str | None = None
    display_name: str | None = None


class IndexEntry(BaseModel):
    symbol: str
    exchange: str
    display_name: str | None = None


class FutureEntry(BaseModel):
    symbol: str
    exchange: str
    display_name: str | None = None
    description: str | None = None


class SwapEntry(BaseModel):
    index_basis: str  # e.g. "SOFR_OIS", "EURIBOR3M", "EURIBOR3M_ESTR_BASIS"
    tenor: str  # e.g. "2Y", "5Y", "10Y"
    leg_description: str


class CurrencyUniverse(BaseModel):
    currency: str
    index: IndexEntry | None = None
    equities: list[EquityEntry] = []
    rate_proxy_futures: list[FutureEntry] = []
    swaps: list[SwapEntry] = []


def load_currency_universe(currency: str, instruments_dir: Path) -> CurrencyUniverse:
    path = instruments_dir / f"{currency.lower()}.yaml"
    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    return CurrencyUniverse(**raw)


def equity_instrument_id(currency: str, symbol: str) -> str:
    return f"{currency}.EQ.{symbol}"


def index_instrument_id(currency: str, symbol: str) -> str:
    return f"{currency}.IDX.{symbol}"


def future_instrument_id(currency: str, symbol: str) -> str:
    return f"{currency}.FUT.{symbol}"


def build_contract_for_equity(entry: EquityEntry, currency: str) -> Contract:
    return ibc.stock(entry.symbol, entry.exchange, currency, entry.primary_exchange)


def build_contract_for_index(entry: IndexEntry, currency: str) -> Contract:
    return ibc.index(entry.symbol, entry.exchange, currency)


def build_contract_for_future(entry: FutureEntry, currency: str) -> Contract:
    # Front-month continuous resolution is left to qualifyContracts()/reqContractDetails()
    # picking the nearest expiry when no explicit lastTradeDateOrContractMonth is given.
    return ibc.future(entry.symbol, entry.exchange, currency)


def instruments_for_universe(universe: CurrencyUniverse) -> list[Instrument]:
    """Real (non-stub) instrument identities for this currency, for storage/labeling."""
    out: list[Instrument] = []
    if universe.index:
        out.append(
            Instrument(
                instrument_id=index_instrument_id(universe.currency, universe.index.symbol),
                currency=universe.currency,
                asset_class=AssetClass.INDEX,
                display_name=universe.index.display_name or universe.index.symbol,
            )
        )
    for eq in universe.equities:
        out.append(
            Instrument(
                instrument_id=equity_instrument_id(universe.currency, eq.symbol),
                currency=universe.currency,
                asset_class=AssetClass.EQUITY,
                display_name=eq.display_name or eq.symbol,
            )
        )
    for fut in universe.rate_proxy_futures:
        out.append(
            Instrument(
                instrument_id=future_instrument_id(universe.currency, fut.symbol),
                currency=universe.currency,
                asset_class=AssetClass.FUTURE,
                display_name=fut.display_name or fut.symbol,
            )
        )
    return out


def contracts_for_universe(universe: CurrencyUniverse) -> list[tuple[Contract, str]]:
    """(unqualified contract, instrument_id) for every real instrument in the universe."""
    ccy = universe.currency
    out: list[tuple[Contract, str]] = []
    if universe.index:
        out.append((build_contract_for_index(universe.index, ccy), index_instrument_id(ccy, universe.index.symbol)))
    for eq in universe.equities:
        out.append((build_contract_for_equity(eq, ccy), equity_instrument_id(ccy, eq.symbol)))
    for fut in universe.rate_proxy_futures:
        out.append((build_contract_for_future(fut, ccy), future_instrument_id(ccy, fut.symbol)))
    return out
