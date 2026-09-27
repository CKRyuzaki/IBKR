"""Subscribes to live IBKR market data for real (non-stub) instruments and republishes
normalized ticks onto the pub/sub broker + SQLite storage.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone

from ib_async import Contract, Ticker

from ibkr_desk.core.ib.connection import IBConnectionManager
from ibkr_desk.core.ib.contracts import qualify_async
from ibkr_desk.core.models import Tick
from ibkr_desk.core.providers import registry
from ibkr_desk.core.pubsub import Broker
from ibkr_desk.storage.sqlite import Storage
from ibkr_desk.universe import CurrencyUniverse, contracts_for_universe

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
        self._wanted: list[tuple[Contract, str]] = []
        connection.add_on_connected(self._subscribe_all)  # re-subscribe after every reconnect

        # ib.pendingTickersEvent fires once per socket read with the set of Tickers that
        # changed -- more broadly documented/stable across ib_insync/ib_async than relying
        # on a per-Ticker update event.
        connection.ib.pendingTickersEvent += self._on_pending_tickers

    def subscribe_universe(self, universe: CurrencyUniverse) -> None:
        """Declare interest; subscriptions are (re)established on every successful IBKR connect."""
        self._wanted.extend(contracts_for_universe(universe))

    async def _subscribe_all(self) -> None:
        self._contract_to_instrument_id.clear()
        for contract, instrument_id in self._wanted:
            await self._subscribe_one(contract, instrument_id)

    async def _subscribe_one(self, contract: Contract, instrument_id: str) -> None:
        resolved = await qualify_async(self._connection.ib, contract)
        if resolved is None:
            logger.warning(
                "No qualified contract found for %s (symbol/exchange may need adjustment in "
                "config/instruments)",
                instrument_id,
            )
            return
        self._contract_to_instrument_id[resolved.conId] = instrument_id
        self._connection.ib.reqMktData(resolved, "", False, False)
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
                registry.touch(self._connection.name)
        if all_ticks:
            self._storage.insert_ticks(all_ticks)
