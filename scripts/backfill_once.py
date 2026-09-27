"""Phase B verification: run a one-off historical backfill for a single currency's universe
and print how many bars landed in SQLite.

Usage: uv run python scripts/backfill_once.py USD
"""

from __future__ import annotations

import logging
import sys

from ibkr_desk.universe import load_currency_universe
from ibkr_desk.core.ib.connection import IBConnectionManager
from ibkr_desk.marketdata.backfill import backfill_universe
from ibkr_desk.storage.sqlite import Storage
from ibkr_desk.settings import load_settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def main() -> None:
    if len(sys.argv) != 2:
        print("Usage: uv run python scripts/backfill_once.py <CURRENCY>", file=sys.stderr)
        sys.exit(1)
    currency = sys.argv[1].upper()

    settings = load_settings()
    universe = load_currency_universe(currency, settings.instruments_path)

    storage = Storage(settings.sqlite_path)
    connection = IBConnectionManager(settings.ibkr)
    connection.start()

    connection.run_coroutine(
        backfill_universe(connection, storage, universe, settings.storage.bar_backfill_days)
    ).result(timeout=120)

    connection.stop()
    print(f"Backfill complete for {currency}. Check {settings.sqlite_path} `bars` table row counts.")


if __name__ == "__main__":
    main()
