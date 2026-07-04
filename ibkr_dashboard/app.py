"""Entrypoint: wires the IBKR connection, storage, pub/sub, websocket bridge and Dash app
together and runs the process.

Run with: `poetry run dashboard` (see pyproject.toml [project.scripts]) or
`python -m ibkr_dashboard.app`.
"""

from __future__ import annotations

import logging

from ibkr_dashboard.connection.contracts import (
    CurrencyUniverse,
    instruments_for_universe,
    load_currency_universe,
)
from ibkr_dashboard.connection.ib_client import IBConnectionManager
from ibkr_dashboard.connection.market_data import MarketDataService
from ibkr_dashboard.connection.portfolio_feed import ACCOUNT_TOPIC, POSITIONS_TOPIC, PortfolioFeed
from ibkr_dashboard.dash_app.server import build_app
from ibkr_dashboard.dash_app.ws_server import WebSocketServer
from ibkr_dashboard.data.backfill import backfill_universe
from ibkr_dashboard.data.pubsub import broker
from ibkr_dashboard.data.storage import Storage
from ibkr_dashboard.settings import load_settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

WS_PORT = 8051


def _make_topics_for_path(topics_by_ccy: dict[str, list[str]]):
    def _topics_for_path(path: str) -> list[str]:
        parts = [p for p in path.split("/") if p]
        if len(parts) >= 3 and parts[0] == "ws" and parts[1] == "currency":
            return topics_by_ccy.get(parts[2], [])
        if len(parts) >= 2 and parts[0] == "ws" and parts[1] == "portfolio":
            return [POSITIONS_TOPIC, ACCOUNT_TOPIC]
        return []

    return _topics_for_path


def _load_universes(settings) -> dict[str, CurrencyUniverse]:
    universes: dict[str, CurrencyUniverse] = {}
    for ccy in settings.currencies:
        try:
            universes[ccy] = load_currency_universe(ccy, settings.instruments_path)
        except FileNotFoundError:
            logger.warning(
                "No instrument config found for %s at %s -- skipping this currency's tab",
                ccy,
                settings.instruments_path,
            )
    return universes


def main() -> None:
    settings = load_settings()
    universes = _load_universes(settings)

    storage = Storage(settings.sqlite_path)

    connection = IBConnectionManager(settings.ibkr)
    connection.start()

    market_data = MarketDataService(
        connection, broker, storage, throttle_ms=settings.dashboard.update_throttle_ms
    )
    portfolio_feed = PortfolioFeed(connection, broker)

    for instrument_universe in universes.values():
        for instrument in instruments_for_universe(instrument_universe):
            storage.upsert_instrument(instrument)
        market_data.subscribe_universe(instrument_universe)
        connection.run_coroutine(
            backfill_universe(connection, storage, instrument_universe, settings.storage.bar_backfill_days)
        )
    portfolio_feed.start(settings.ibkr.account_id)

    topics_by_ccy = {
        ccy: [f"tick.{inst.instrument_id}" for inst in instruments_for_universe(u)]
        for ccy, u in universes.items()
    }
    ws_server = WebSocketServer(broker, settings.dashboard.host, WS_PORT, _make_topics_for_path(topics_by_ccy))
    ws_server.start()

    app = build_app(universes, storage, settings.dashboard.host, WS_PORT)
    app.run(host=settings.dashboard.host, port=settings.dashboard.port, debug=False)


if __name__ == "__main__":
    main()
