"""Provider-agnostic connection status, so the dashboard can monitor IBKR today and any other
market-data provider (Bloomberg, Refinitiv, a websocket feed, ...) later without changes.

A provider is anything with a `name` and a `status()` method. Register it in a `ProviderRegistry`;
the status panel just renders whatever is registered.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Protocol, runtime_checkable


class ConnState(str, Enum):
    CONNECTED = "connected"
    CONNECTING = "connecting"
    DISCONNECTED = "disconnected"
    ERROR = "error"


@dataclass(frozen=True)
class ProviderStatus:
    name: str
    state: ConnState
    detail: str = ""  # human-readable: endpoint, account, last error
    since: float | None = None  # unix ts of the last state change
    last_data_ts: float | None = None  # unix ts of the last tick/message received, if tracked
    extra: dict[str, str] = field(default_factory=dict)  # provider-specific facts (account, clientId, ...)
    kind: str = "market_data"  # "market_data" (feeds ticks) or "storage" (a service we depend on)

    @property
    def data_age_s(self) -> float | None:
        return None if self.last_data_ts is None else max(0.0, time.time() - self.last_data_ts)


@runtime_checkable
class MarketDataProvider(Protocol):
    name: str

    def status(self) -> ProviderStatus: ...


class ProviderRegistry:
    """Thread-safe list of providers; also records the last time data arrived from each."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._providers: dict[str, MarketDataProvider] = {}
        self._last_data: dict[str, float] = {}

    def register(self, provider: MarketDataProvider) -> None:
        with self._lock:
            self._providers[provider.name] = provider

    def touch(self, name: str) -> None:
        """Call whenever a provider delivers data (tick, bar, message)."""
        self._last_data[name] = time.time()

    def statuses(self) -> list[ProviderStatus]:
        with self._lock:
            providers = list(self._providers.values())
        out = []
        for p in providers:
            try:
                s = p.status()
            except Exception as exc:  # noqa: BLE001 -- a broken provider must not break the panel
                s = ProviderStatus(p.name, ConnState.ERROR, f"status() failed: {exc}")
            last = self._last_data.get(p.name)
            if last is not None and s.last_data_ts is None:
                s = replace(s, last_data_ts=last)
            out.append(s)
        return out


registry = ProviderRegistry()
