"""Bootstraps the SQLite `bars` table via reqHistoricalData at startup, so GP-style longer-lookback
charts have data immediately rather than waiting for live ticks to accumulate.

Requests go through the connection's shared, paced `HistoryClient` (core/ib/history.py).
"""

from __future__ import annotations

import logging

from ib_async import Contract

from ibkr_desk.core.ib.connection import IBConnectionManager
from ibkr_desk.core.ib.contracts import qualify_async
from ibkr_desk.core.models import Bar
from ibkr_desk.core.time_utils import as_utc_datetime
from ibkr_desk.live.quote_book import QuoteBook
from ibkr_desk.settings import BarBackfillDays
from ibkr_desk.storage.sqlite import Storage
from ibkr_desk.universe import CurrencyUniverse, contracts_for_universe

logger = logging.getLogger(__name__)


def _bar_specs(days: BarBackfillDays) -> list[tuple[str, str]]:
    return [
        ("1 min", f"{days.intraday_1min} D"),
        ("1 day", f"{days.daily} D"),
    ]


async def backfill_instrument(
    connection: IBConnectionManager,
    storage: Storage,
    contract: Contract,
    instrument_id: str,
    days: BarBackfillDays,
    quote_book: QuoteBook | None = None,
) -> None:
    for bar_size, duration in _bar_specs(days):
        raw = await connection.history.bars(
            contract, duration, bar_size, what="TRADES", use_rth=True, format_date=2
        )
        normalized = [
            Bar(
                instrument_id=instrument_id,
                bar_size=bar_size,
                ts=as_utc_datetime(b.date),
                open=b.open,
                high=b.high,
                low=b.low,
                close=b.close,
                volume=getattr(b, "volume", None),
            )
            for b in raw
        ]
        storage.insert_bars(normalized)
        logger.info("Backfilled %d %s bars for %s", len(normalized), bar_size, instrument_id)

    if quote_book is not None:
        # No live tick yet (e.g. market closed) -- show the last backfilled close instead of a
        # blank row. `QuoteBook.seed` is a no-op once a real tick has already arrived.
        latest = storage.latest_bar(instrument_id, "1 min") or storage.latest_bar(instrument_id, "1 day")
        if latest is not None and latest.close is not None:
            quote_book.seed(instrument_id, latest.close, latest.ts)


async def backfill_universe(
    connection: IBConnectionManager,
    storage: Storage,
    universe: CurrencyUniverse,
    days: BarBackfillDays,
    quote_book: QuoteBook | None = None,
) -> None:
    for contract, instrument_id in contracts_for_universe(universe):
        qualified = await qualify_async(connection.ib, contract)
        if qualified is None:
            continue
        await backfill_instrument(connection, storage, qualified, instrument_id, days, quote_book)
