"""Subscribes to live IBKR market data for real (non-stub) instruments and republishes
normalized ticks onto the pub/sub broker + SQLite storage.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone

from ib_async import Contract, Ticker

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
from ibkr_dashboard.data.models import Tick
from ibkr_dashboard.data.pubsub import Broker
from ibkr_dashboard.data.storage import Storage

logger = logging.getLogger(__name__)


class MarketDataService:
    def __init__(
        self,
        connection: IBConnectionManager,
        broker: Broker,
        storage: Storage,
        throttle_ms: int = 250,
    ) -> None:
        self._connection = connection
        self._broker = broker
        self._storage = storage
        self._throttle_seconds = throttle_ms / 1000
        self._last_publish: dict[tuple[str, str], float] = {}
        self._contract_to_instrument_id: dict[int, str] = {}

        # ib.pendingTickersEvent fires once per socket read with the set of Tickers that
        # changed -- more broadly documented/stable across ib_insync/ib_async than relying
        # on a per-Ticker update event.
        connection.ib.pendingTickersEvent += self._on_pending_tickers

    def subscribe_universe(self, universe: CurrencyUniverse) -> None:
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
            self._connection.run_coroutine(self._subscribe_one(contract, instrument_id))

    async def _subscribe_one(self, contract: Contract, instrument_id: str) -> None:
        ib = self._connection.ib
        try:
            qualified = await ib.qualifyContractsAsync(contract)
        except Exception as exc:  # noqa: BLE001 -- log and skip, don't crash the whole universe
            logger.warning("Could not qualify contract for %s: %s", instrument_id, exc)
            return
        if not qualified:
            logger.warning(
                "No qualified contract found for %s (symbol/exchange may need adjustment in "
                "config/instruments)",
                instrument_id,
            )
            return
        resolved = qualified[0]
        self._contract_to_instrument_id[resolved.conId] = instrument_id
        ib.reqMktData(resolved, "", False, False)
        logger.info("Subscribed market data for %s (conId=%s)", instrument_id, resolved.conId)

    def _on_pending_tickers(self, tickers: set[Ticker]) -> None:
        now = datetime.now(timezone.utc)
        all_ticks: list[Tick] = []
        for ticker in tickers:
            instrument_id = self._contract_to_instrument_id.get(ticker.contract.conId)
            if instrument_id is None:
                continue
            for field_name, value in (("bid", ticker.bid), ("ask", ticker.ask), ("last", ticker.last)):
                if value is None or value != value:  # filters NaN, which IBKR sends for "no value"
                    continue
                key = (instrument_id, field_name)
                last_t = self._last_publish.get(key, 0.0)
                if time.monotonic() - last_t < self._throttle_seconds:
                    continue
                self._last_publish[key] = time.monotonic()
                tick = Tick(instrument_id=instrument_id, field=field_name, value=float(value), ts=now)
                all_ticks.append(tick)
                self._broker.publish(f"tick.{instrument_id}", tick)
        if all_ticks:
            self._storage.insert_ticks(all_ticks)
