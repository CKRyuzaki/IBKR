"""Background websocket server bridging the in-process pub/sub Broker to the browser.

Runs on its own asyncio loop/thread, separate from both the Dash server thread and the IBKR I/O
thread, listening on a different port. Each browser tab opens one websocket connection (via the
dash-extensions `WebSocket` component) whose URL path determines which Broker topics it
subscribes to; the server fans those topic messages out as JSON frames. This is the mechanism
that lets Dash callbacks push `dash.Patch()` updates driven by real IBKR ticks instead of
polling/rerunning the whole page like Streamlit does.
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
from collections.abc import Callable
from dataclasses import asdict, is_dataclass
from datetime import datetime

import websockets
from websockets.exceptions import ConnectionClosed

from ibkr_desk.core.pubsub import Broker

logger = logging.getLogger(__name__)

TopicsForPath = Callable[[str], list[str]]


def _json_default(obj):
    if isinstance(obj, datetime):
        return obj.isoformat()
    if is_dataclass(obj):
        return asdict(obj)
    return str(obj)


class WebSocketServer:
    def __init__(self, broker: Broker, host: str, port: int, topics_for_path: TopicsForPath) -> None:
        self._broker = broker
        self._host = host
        self._port = port
        self._topics_for_path = topics_for_path
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="ws-server", daemon=True)
        self._thread.start()

    def _run(self) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._loop.run_until_complete(self._serve())
        self._loop.run_forever()

    async def _serve(self) -> None:
        await websockets.serve(self._handle_connection, self._host, self._port)
        logger.info("WebSocket bridge listening on ws://%s:%s", self._host, self._port)

    async def _handle_connection(self, websocket) -> None:
        path = getattr(websocket, "path", None) or websocket.request.path
        topics = self._topics_for_path(path)
        loop = asyncio.get_event_loop()
        queues = [self._broker.subscribe_async(topic, loop) for topic in topics]
        pending = {asyncio.ensure_future(q.get()): q for q in queues}
        try:
            while True:
                done, _ = await asyncio.wait(pending.keys(), return_when=asyncio.FIRST_COMPLETED)
                for task in done:
                    q = pending.pop(task)
                    message = task.result()
                    await websocket.send(json.dumps(message, default=_json_default))
                    pending[asyncio.ensure_future(q.get())] = q
        except ConnectionClosed:
            pass
        finally:
            for task in pending:
                task.cancel()
            for topic, q in zip(topics, queues):
                self._broker.unsubscribe_async(topic, loop, q)
