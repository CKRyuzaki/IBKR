"""Bootstraps the `bars` table via reqHistoricalData at startup, so GP-style longer-lookback
charts have data immediately rather than waiting for live ticks to accumulate.
"""

from __future__ import annotations

import logging

from ib_async import Contract

from ibkr_dashboard.connection.contracts import (
    CurrencyUniverse,
    build_contract_for_equity,
    build_contract_for_future,
    build_contract_for_index,
    equity_instrument_id,
    future_instrument_id,
    index_instrument_id,
)
from ibkr_dashboard.connection.ib_client import IBConnectionManager
from ibkr_dashboard.data.models import Bar
from ibkr_dashboard.data.storage import Storage
from ibkr_dashboard.settings import BarBackfillDays
from ibkr_dashboard.utils.time_utils import as_utc_datetime

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
) -> None:
    ib = connection.ib
    for bar_size, duration in _bar_specs(days):
        try:
            bars = await ib.reqHistoricalDataAsync(
                contract,
                endDateTime="",
                durationStr=duration,
                barSizeSetting=bar_size,
                whatToShow="TRADES",
                useRTH=True,
                formatDate=2,
            )
        except Exception as exc:  # noqa: BLE001 -- backfill is best-effort, never fatal
            logger.warning("Historical backfill failed for %s (%s): %s", instrument_id, bar_size, exc)
            continue
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
            for b in bars
        ]
        storage.insert_bars(normalized)
        logger.info("Backfilled %d %s bars for %s", len(normalized), bar_size, instrument_id)


async def backfill_universe(
    connection: IBConnectionManager,
    storage: Storage,
    universe: CurrencyUniverse,
    days: BarBackfillDays,
) -> None:
    ccy = universe.currency
    entries: list[tuple[Contract, str]] = []
    if universe.index:
        entries.append(
            (build_contract_for_index(universe.index, ccy), index_instrument_id(ccy, universe.index.symbol))
        )
    for eq in universe.equities:
        entries.append((build_contract_for_equity(eq, ccy), equity_instrument_id(ccy, eq.symbol)))
    for fut in universe.rate_proxy_futures:
        entries.append((build_contract_for_future(fut, ccy), future_instrument_id(ccy, fut.symbol)))

    for contract, instrument_id in entries:
        try:
            qualified = await connection.ib.qualifyContractsAsync(contract)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not qualify contract for backfill of %s: %s", instrument_id, exc)
            continue
        if not qualified:
            continue
        await backfill_instrument(connection, storage, qualified[0], instrument_id, days)
