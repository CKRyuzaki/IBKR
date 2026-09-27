"""Normalized data shapes shared across the connection, storage, and dashboard layers."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


class AssetClass(str, Enum):
    EQUITY = "EQUITY"
    INDEX = "INDEX"
    FUTURE = "FUTURE"
    BOND = "BOND"
    SWAP_STUB = "SWAP_STUB"


@dataclass(frozen=True)
class Instrument:
    """Identity of a tradeable/quotable thing, independent of IBKR contract details."""

    instrument_id: str  # e.g. "USD.EQ.AAPL", "EUR.IDX.SX5E", "EUR.SWAP.ESTR.5Y"
    currency: str
    asset_class: AssetClass
    display_name: str
    is_real: bool = True  # False for swap stubs (no live data)


@dataclass(frozen=True)
class Tick:
    instrument_id: str
    field: str  # "bid" | "ask" | "last" | "mid" | "volume"
    value: float
    ts: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass(frozen=True)
class Bar:
    instrument_id: str
    bar_size: str  # matches ib_async barSizeSetting strings, e.g. "1 min", "1 day"
    ts: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float | None = None


@dataclass(frozen=True)
class Position:
    account: str
    instrument_id: str
    symbol: str
    position: float
    avg_cost: float
    market_price: float | None = None
    market_value: float | None = None
    unrealized_pnl: float | None = None
    realized_pnl: float | None = None


@dataclass(frozen=True)
class AccountValue:
    account: str
    tag: str  # e.g. "NetLiquidation", "BuyingPower", "UnrealizedPnL"
    value: str
    currency: str
