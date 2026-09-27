"""Thread-safe in-memory pub/sub bridging the IBKR I/O thread and the Dash/websocket thread.

Deliberately not a message broker (Redis/Kafka/etc): this is a single-process, single-user
tool, so a plain topic -> subscriber-queue registry with a lock is sufficient and has zero
extra operational surface.
"""

from __future__ import annotations

import asyncio
import queue
import threading
from collections import defaultdict
from typing import Any


class Broker:
    """Supports two kinds of subscribers:

    - plain thread-safe `queue.Queue` (subscribe/unsubscribe) for consumers that block-poll
      from a regular thread.
    - asyncio-native (subscribe_async/unsubscribe_async) for consumers living on an event loop
      (the websocket bridge), fed via `loop.call_soon_threadsafe` since publish() is called
      from the IBKR I/O thread, not the subscriber's own loop.
    """

    def __init__(self, max_queue_size: int = 1000) -> None:
        self._max_queue_size = max_queue_size
        self._lock = threading.Lock()
        self._subscribers: dict[str, list[queue.Queue]] = defaultdict(list)
        self._async_subscribers: dict[str, list[tuple[asyncio.AbstractEventLoop, asyncio.Queue]]] = defaultdict(list)
        self._taps: list[tuple[str, Any]] = []

    def tap(self, prefix: str, fn) -> None:
        """Call fn(topic, payload) for every publish whose topic starts with `prefix`.

        Runs synchronously on the publisher's thread (the IBKR I/O thread), so `fn` must be fast and
        must not block -- e.g. update an in-memory dict. Exceptions in fn are swallowed so a buggy
        tap can never break market data ingestion.
        """
        with self._lock:
            self._taps.append((prefix, fn))

    def subscribe(self, topic: str) -> queue.Queue:
        q: queue.Queue = queue.Queue(maxsize=self._max_queue_size)
        with self._lock:
            self._subscribers[topic].append(q)
        return q

    def unsubscribe(self, topic: str, q: queue.Queue) -> None:
        with self._lock:
            subs = self._subscribers.get(topic)
            if subs and q in subs:
                subs.remove(q)

    def subscribe_async(self, topic: str, loop: asyncio.AbstractEventLoop) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=self._max_queue_size)
        with self._lock:
            self._async_subscribers[topic].append((loop, q))
        return q

    def unsubscribe_async(self, topic: str, loop: asyncio.AbstractEventLoop, q: asyncio.Queue) -> None:
        with self._lock:
            subs = self._async_subscribers.get(topic)
            if subs:
                self._async_subscribers[topic] = [(lp, qq) for (lp, qq) in subs if qq is not q]

    def publish(self, topic: str, payload: Any) -> None:
        with self._lock:
            subs = list(self._subscribers.get(topic, ()))
            async_subs = list(self._async_subscribers.get(topic, ()))
            taps = [fn for prefix, fn in self._taps if topic.startswith(prefix)]
        for fn in taps:
            try:
                fn(topic, payload)
            except Exception:  # noqa: BLE001 -- never let a tap break the publisher
                pass
        for q in subs:
            try:
                q.put_nowait(payload)
            except queue.Full:
                # Drop the oldest message rather than block the publisher (the IBKR I/O thread) --
                # a slow/stalled UI subscriber must never back-pressure market data ingestion.
                try:
                    q.get_nowait()
                    q.put_nowait(payload)
                except queue.Empty:
                    pass
        for loop, aq in async_subs:
            loop.call_soon_threadsafe(_put_nowait_drop_oldest, aq, payload)


def _put_nowait_drop_oldest(q: asyncio.Queue, payload: Any) -> None:
    try:
        q.put_nowait(payload)
    except asyncio.QueueFull:
        try:
            q.get_nowait()
        except asyncio.QueueEmpty:
            pass
        q.put_nowait(payload)


# Module-level singleton: one process, one broker.
broker = Broker()
