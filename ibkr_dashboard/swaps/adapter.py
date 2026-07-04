"""Pluggable interface for sourcing swap/IRS quotes.

IMPORTANT -- READ BEFORE WIRING A REAL ADAPTER:
IBKR's public TWS API documentation (interactivebrokers.github.io/tws-api) does not document a
secType/contract-field spec for OTC interest-rate-swap quotes via reqMktData. Access to cleared
swaps at IBKR is very likely an institutional-only entitlement, and may require FIX CTCI rather
than the standard TWS/IB Gateway socket API that the rest of this project uses via ib_async.

Do NOT invent contract fields here. Once you have the exact spec (from IBKR support, TWS
"contract info" on a real swap instrument, or a reqContractDetails() dump), implement a
RealSwapAdapter below satisfying the same SwapMarketDataAdapter protocol, and flip the single
line in ibkr_dashboard/app.py that constructs the adapter. Nothing else in the pipeline
(storage, pub/sub, dashboard) needs to change.
"""

from __future__ import annotations

import logging
from typing import Protocol

from ibkr_dashboard.swaps.models import RatesSwapInstrument

logger = logging.getLogger(__name__)


class SwapMarketDataAdapter(Protocol):
    def subscribe(self, instrument: RatesSwapInstrument) -> None: ...

    def get_quote(self, instrument: RatesSwapInstrument) -> RatesSwapInstrument: ...


class StubSwapAdapter:
    """No-op placeholder. Always returns quotes with bid/ask/mid = None and is_stub = True."""

    def subscribe(self, instrument: RatesSwapInstrument) -> None:
        logger.debug(
            "Swap subscription for %s is stubbed -- no live data source wired yet",
            instrument.instrument_id,
        )

    def get_quote(self, instrument: RatesSwapInstrument) -> RatesSwapInstrument:
        instrument.bid = None
        instrument.ask = None
        instrument.mid = None
        instrument.as_of = None
        instrument.is_stub = True
        return instrument
