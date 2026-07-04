"""Owns the single ib_async.IB() connection on its own asyncio event loop, in a dedicated thread.

IBKR API connections are not safe to share across threads/loops -- there is exactly one
connection, one event loop, one thread for it, for the lifetime of the process. Everything else
(market data subscriptions, portfolio feed, historical backfill) schedules coroutines onto this
loop via run_coroutine(); event callbacks registered on `ib` (ticks, positions, disconnects) fire
on this same loop/thread.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from concurrent.futures import Future
from typing import Coroutine

from ib_async import IB

from ibkr_dashboard.settings import IBKRConfig

logger = logging.getLogger(__name__)


class IBConnectionManager:
    def __init__(self, config: IBKRConfig) -> None:
        self._config = config
        self.ib = IB()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()
        self._stopping = False

        self.ib.disconnectedEvent += self._on_disconnected

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="ib-io", daemon=True)
        self._thread.start()
        if not self._ready.wait(timeout=self._config.timeout_seconds + 10):
            raise TimeoutError("Timed out waiting for IBKR connection thread to become ready")

    def _run(self) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._loop.run_until_complete(self._connect_with_retry())
        self._ready.set()
        self._loop.run_forever()

    async def _connect_with_retry(self) -> None:
        while not self._stopping:
            try:
                await self.ib.connectAsync(
                    self._config.host,
                    self._config.port,
                    clientId=self._config.client_id,
                    timeout=self._config.timeout_seconds,
                    readonly=self._config.readonly_api,
                )
                logger.info(
                    "Connected to IBKR at %s:%s (clientId=%s, mode=%s)",
                    self._config.host,
                    self._config.port,
                    self._config.client_id,
                    self._config.mode,
                )
                return
            except Exception as exc:  # noqa: BLE001 -- any connection failure should retry, not crash
                logger.warning(
                    "IBKR connection failed (%s); retrying in %ss. Is IB Gateway/TWS running "
                    "with API access enabled on port %s?",
                    exc,
                    self._config.reconnect_delay_seconds,
                    self._config.port,
                )
                await asyncio.sleep(self._config.reconnect_delay_seconds)

    def _on_disconnected(self) -> None:
        if self._stopping or self._loop is None:
            return
        logger.warning("Lost connection to IBKR; scheduling reconnect")
        asyncio.run_coroutine_threadsafe(self._connect_with_retry(), self._loop)

    def run_coroutine(self, coro: Coroutine) -> Future:
        """Schedule a coroutine on the IBKR thread's loop from any other thread."""
        if self._loop is None:
            raise RuntimeError("IBConnectionManager not started")
        return asyncio.run_coroutine_threadsafe(coro, self._loop)

    def stop(self) -> None:
        self._stopping = True
        if self._loop is None:
            return

        async def _disconnect() -> None:
            self.ib.disconnect()

        try:
            asyncio.run_coroutine_threadsafe(_disconnect(), self._loop).result(timeout=5)
        except Exception:  # noqa: BLE001 -- best-effort shutdown
            pass
        self._loop.call_soon_threadsafe(self._loop.stop)
        if self._thread:
            self._thread.join(timeout=5)
