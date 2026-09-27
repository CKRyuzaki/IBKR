"""The one place an IBKR connection is made.

Two ways in, one code path (`connect_async`), so every client gets the same guarantees:
  - the paper-account guard (refuse a live account unless `ibkr.allow_live`),
  - a distinct clientId per `ClientRole`, and read-only unless the role is TRADER,
  - the configured market-data type.

`connect_sync`           short-lived scripts / jobs (archive, backtest refresh, trader).
`IBConnectionManager`    long-running apps (dashboard): owns the single ib_async.IB() on its own
                         asyncio loop in a dedicated thread, auto-reconnects, and reports status.

IBKR API connections are not safe to share across threads/loops. Everything else in a long-running
app (market data subscriptions, portfolio feed, historical backfill) schedules coroutines onto the
manager's loop via run_coroutine(); event callbacks registered on `ib` fire on that same thread.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from concurrent.futures import Future
from typing import Callable, Coroutine

from ib_async import IB

from ibkr_desk.core.config import PAPER_ACCOUNT_PREFIX, ClientRole, IBKRConfig
from ibkr_desk.core.providers import ConnState, ProviderStatus

logger = logging.getLogger(__name__)


class LiveAccountRefused(RuntimeError):
    """Raised when the Gateway is logged into a non-paper account and ibkr.allow_live is false."""


def assert_account_allowed(accounts: list[str], cfg: IBKRConfig) -> None:
    if cfg.allow_live:
        return
    live = [a for a in accounts if not a.startswith(PAPER_ACCOUNT_PREFIX)]
    if live or not accounts:
        raise LiveAccountRefused(
            f"Refusing to run: accounts {accounts or '[none]'} are not paper "
            f"('{PAPER_ACCOUNT_PREFIX}...') and ibkr.allow_live is false. "
            "Log Gateway into your paper account, or set ibkr.allow_live: true deliberately."
        )


async def connect_async(ib: IB, cfg: IBKRConfig, role: ClientRole) -> None:
    if cfg.mode == "live" and not cfg.allow_live:
        raise LiveAccountRefused("ibkr.mode is 'live' but ibkr.allow_live is false")
    await ib.connectAsync(
        cfg.host,
        cfg.port,
        clientId=cfg.client_id_for(role),
        timeout=cfg.timeout_seconds,
        readonly=cfg.readonly_for(role),
    )
    try:
        assert_account_allowed(ib.managedAccounts(), cfg)
    except LiveAccountRefused:
        ib.disconnect()
        raise
    ib.reqMarketDataType(cfg.market_data_type)


def connect_sync(cfg: IBKRConfig, role: ClientRole) -> IB:
    """Blocking connect for scripts. Caller owns the returned IB and must call .disconnect()."""
    ib = IB()
    ib.run(connect_async(ib, cfg, role))
    logger.info("Connected to IBKR %s:%s as %s (clientId=%s)", cfg.host, cfg.port, role.name,
                cfg.client_id_for(role))
    return ib


class IBConnectionManager:
    name = "IBKR"

    def __init__(self, config: IBKRConfig, role: ClientRole = ClientRole.DASHBOARD) -> None:
        self._config = config
        self._role = role
        self.ib = IB()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()
        self._stopping = False
        self._fatal: Exception | None = None
        self._state = ConnState.CONNECTING
        self._detail = ""
        self._since = time.time()
        self._history = None  # lazily created HistoryClient, shared so pacing is global
        self._hooks: list[tuple[Callable[[], Coroutine], bool]] = []
        self._ran_once: set[int] = set()

        self.ib.disconnectedEvent += self._on_disconnected

    # --- provider status (see core/providers.py) -------------------------------------------
    def _set_state(self, state: ConnState, detail: str = "") -> None:
        if state != self._state:
            self._since = time.time()
        self._state, self._detail = state, detail

    def status(self) -> ProviderStatus:
        connected = self.ib.isConnected()
        state = self._state
        if state is ConnState.CONNECTED and not connected:
            state = ConnState.DISCONNECTED
        extra: dict[str, str] = {"clientId": str(self._config.client_id_for(self._role)), "role": self._role.name}
        if connected:
            extra["accounts"] = ",".join(self.ib.managedAccounts())
        return ProviderStatus(
            name=self.name,
            state=state,
            detail=self._detail or f"{self._config.host}:{self._config.port} ({self._config.mode})",
            since=self._since,
            extra=extra,
        )

    @property
    def history(self):
        """Shared paced historical-data client (one pacer for every backfill on this connection)."""
        if self._history is None:
            from ibkr_desk.core.ib.history import HistoryClient

            self._history = HistoryClient(self.ib, self._config.historical_request_interval_s)
        return self._history

    def add_on_connected(self, hook: Callable[[], Coroutine], once: bool = False) -> None:
        """Run `hook()` (a coroutine function) on the IBKR loop after every successful (re)connect.

        Subscriptions and account streams die with the socket, so anything that must be live has
        to be re-established here rather than fired once at startup. `once=True` runs it on the
        first connect only (e.g. a historical backfill). Register before `start()`."""
        self._hooks.append((hook, once))

    def _run_hooks(self) -> None:
        for i, (hook, once) in enumerate(self._hooks):
            if once and i in self._ran_once:
                continue
            self._ran_once.add(i)
            task = asyncio.ensure_future(hook())
            task.add_done_callback(self._log_hook_error)

    @staticmethod
    def _log_hook_error(task: "asyncio.Future") -> None:
        if not task.cancelled() and task.exception() is not None:
            logger.error("on-connected hook failed: %r", task.exception())

    # --- lifecycle -------------------------------------------------------------------------
    def start(self, required: bool = True) -> None:
        """Start the IBKR thread. With required=True (scripts) block until connected and raise on
        failure. With required=False (dashboard) return after the first attempt even if the Gateway
        is down: the thread keeps retrying and status() reports the state, so the UI can show it."""
        self._thread = threading.Thread(target=self._run, name="ib-io", daemon=True)
        self._thread.start()
        if not self._ready.wait(timeout=self._config.timeout_seconds + 10 if required else 3):
            if required:
                raise TimeoutError("Timed out waiting for IBKR connection thread to become ready")
            logger.warning("IBKR not connected yet; still retrying in the background")
        if self._fatal is not None:
            raise self._fatal

    def _run(self) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._loop.run_until_complete(self._connect_with_retry())
        self._ready.set()
        if self._fatal is None:
            self._loop.run_forever()

    async def _connect_with_retry(self) -> None:
        cfg = self._config
        while not self._stopping:
            self._set_state(ConnState.CONNECTING, f"connecting to {cfg.host}:{cfg.port}")
            try:
                await connect_async(self.ib, cfg, self._role)
                self._set_state(ConnState.CONNECTED, f"{cfg.host}:{cfg.port} ({cfg.mode})")
                logger.info(
                    "Connected to IBKR at %s:%s (clientId=%s, role=%s, mode=%s)",
                    cfg.host, cfg.port, cfg.client_id_for(self._role), self._role.name, cfg.mode,
                )
                self._run_hooks()
                return
            except LiveAccountRefused as exc:  # config problem, not transient: don't retry
                self._fatal = exc
                self._set_state(ConnState.ERROR, str(exc))
                return
            except Exception as exc:  # noqa: BLE001 -- any connection failure should retry, not crash
                self._set_state(ConnState.DISCONNECTED, f"{exc!r}; retrying in {cfg.reconnect_delay_seconds}s")
                logger.warning(
                    "IBKR connection failed (%s); retrying in %ss. Is IB Gateway/TWS running "
                    "with API access enabled on port %s?",
                    exc, cfg.reconnect_delay_seconds, cfg.port,
                )
                await asyncio.sleep(cfg.reconnect_delay_seconds)

    def _on_disconnected(self) -> None:
        if self._stopping or self._loop is None or self._fatal is not None:
            return
        logger.warning("Lost connection to IBKR; scheduling reconnect")
        self._set_state(ConnState.DISCONNECTED, "connection lost; reconnecting")
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
        self._set_state(ConnState.DISCONNECTED, "stopped")
