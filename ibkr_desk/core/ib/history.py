"""Historical bar requests with IBKR pacing.

IBKR throttles reqHistoricalData (roughly 60 requests / 10 min, no identical requests within 15 s),
so every caller goes through one `HistoryClient` that spaces requests. It is safe to call from many
concurrent coroutines: they queue on the pacer. Sync callers use `ib.run(client.bars(...))`.
"""

from __future__ import annotations

import asyncio
import logging
import time

import pandas as pd
from ib_async import IB, BarData, Contract

logger = logging.getLogger(__name__)


class Pacer:
    def __init__(self, min_interval_s: float) -> None:
        self._interval = min_interval_s
        self._lock = asyncio.Lock()
        self._last = 0.0

    async def wait(self) -> None:
        async with self._lock:
            gap = time.monotonic() - self._last
            if gap < self._interval:
                await asyncio.sleep(self._interval - gap)
            self._last = time.monotonic()


class HistoryClient:
    def __init__(self, ib: IB, min_interval_s: float = 1.5) -> None:
        self._ib = ib
        self._pacer = Pacer(min_interval_s)

    async def bars(
        self,
        contract: Contract,
        duration: str,
        bar_size: str = "1 day",
        what: str = "TRADES",
        use_rth: bool = True,
        end: str = "",
        format_date: int = 1,
    ) -> list[BarData]:
        """Raw ib_async bars ([] on failure -- callers treat history as best-effort)."""
        await self._pacer.wait()
        try:
            return list(
                await self._ib.reqHistoricalDataAsync(
                    contract, endDateTime=end, durationStr=duration, barSizeSetting=bar_size,
                    whatToShow=what, useRTH=use_rth, formatDate=format_date,
                )
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Historical request failed for %s (%s %s): %s", contract.symbol, duration, bar_size, exc)
            return []


def bars_to_frame(bars: list[BarData]) -> pd.DataFrame:
    """Daily bars -> DataFrame indexed by date with open/high/low/close/volume."""
    if not bars:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
    df = pd.DataFrame(
        [{"date": pd.Timestamp(b.date), "open": b.open, "high": b.high, "low": b.low,
          "close": b.close, "volume": b.volume} for b in bars]
    ).set_index("date")
    df.index.name = "date"
    return df
