"""Data shape for OTC interest-rate-swap quotes.

This module intentionally has no real IBKR wiring yet -- see adapter.py for why.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass
class RatesSwapInstrument:
    currency: str  # "EUR"
    index_basis: str  # "ESTR" | "EURIBOR3M" | "EURIBOR3M_ESTR_BASIS" | ...
    tenor: str  # "2Y", "5Y", "10Y", ...
    leg_description: str  # free text, informational only, e.g. "Fixed vs 3M EURIBOR"
    bid: float | None = None
    ask: float | None = None
    mid: float | None = None
    as_of: datetime | None = None
    is_stub: bool = True

    @property
    def instrument_id(self) -> str:
        return f"{self.currency}.SWAP.{self.index_basis}.{self.tenor}"
