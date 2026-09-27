"""Server-side book of the latest quote per instrument, fed straight from the tick pub/sub.

The Live blotter reads this on a short timer instead of pushing every tick through the browser:
that stays responsive with dozens of instruments ticking, and a stalled browser can never
back-pressure ingestion. Provider-agnostic: any provider that publishes `tick.<instrument_id>`
messages (see core/pubsub.py) shows up here.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime

from ibkr_desk.core.models import Tick
from ibkr_desk.core.pubsub import Broker


@dataclass
class Quote:
    instrument_id: str
    label: str = ""
    ccy: str = ""
    bid: float | None = None
    ask: float | None = None
    last: float | None = None
    direction: int = 0  # +1 / -1: sign of the last change in `last` (or mid if no trades)
    updated: float = 0.0  # unix ts of the most recent tick of any field
    history: deque = field(default_factory=lambda: deque(maxlen=600))  # (epoch, price)


class QuoteBook:
    def __init__(self, labels: dict[str, tuple[str, str]] | None = None) -> None:
        """`labels`: {instrument_id: (display_name, currency)} -- lets the blotter list every
        subscribed instrument immediately, even before its first tick."""
        self._lock = threading.Lock()
        self._quotes: dict[str, Quote] = {}
        for iid, (label, ccy) in (labels or {}).items():
            self._quotes[iid] = Quote(iid, label, ccy)

    def attach(self, broker: Broker) -> None:
        broker.tap("tick.", self._on_message)

    def _on_message(self, _topic: str, tick: Tick) -> None:
        with self._lock:
            q = self._quotes.get(tick.instrument_id)
            if q is None:
                q = self._quotes[tick.instrument_id] = Quote(tick.instrument_id, tick.instrument_id)
            prev = q.last
            setattr(q, tick.field, tick.value)
            if tick.field == "last" and prev is not None and tick.value != prev:
                q.direction = 1 if tick.value > prev else -1
            q.updated = time.time()
            px = q.last if q.last is not None else (
                (q.bid + q.ask) / 2 if q.bid is not None and q.ask is not None else None
            )
            if px is not None:
                q.history.append((q.updated, px))

    def seed(self, instrument_id: str, price: float, ts: datetime) -> None:
        """Prime `last` from the most recent backfilled bar close, so a closed market shows
        its latest known price instead of a blank row. A real tick always wins: this is a
        no-op once `last` is set, so it only fills the gap before the first live tick."""
        with self._lock:
            q = self._quotes.get(instrument_id)
            if q is None:
                q = self._quotes[instrument_id] = Quote(instrument_id, instrument_id)
            if q.last is not None:
                return
            q.last = price
            q.updated = ts.timestamp()
            q.history.append((q.updated, price))

    def snapshot(self) -> list[dict]:
        now = time.time()
        with self._lock:
            return [
                {
                    "id": q.instrument_id, "ccy": q.ccy, "name": q.label,
                    "bid": q.bid, "ask": q.ask, "last": q.last,
                    "spread": (q.ask - q.bid) if q.bid is not None and q.ask is not None else None,
                    "dir": "▲" if q.direction > 0 else "▼" if q.direction < 0 else "",
                    "age_s": round(now - q.updated, 1) if q.updated else None,
                }
                for q in self._quotes.values()
            ]

    def history(self, instrument_id: str) -> list[tuple[float, float]]:
        with self._lock:
            q = self._quotes.get(instrument_id)
            return list(q.history) if q else []
