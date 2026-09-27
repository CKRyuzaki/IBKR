"""Phase A verification: connect to IB Gateway/TWS (paper by default) and print account summary.

Usage: uv run python scripts/smoke_test_connection.py
"""

from __future__ import annotations

import logging
import sys

from ibkr_desk.core.ib.connection import IBConnectionManager
from ibkr_desk.settings import load_settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def main() -> None:
    settings = load_settings()
    print(f"Connecting to IBKR at {settings.ibkr.host}:{settings.ibkr.port} (mode={settings.ibkr.mode})...")

    connection = IBConnectionManager(settings.ibkr)
    connection.start()

    async def _fetch_summary():
        accounts = connection.ib.managedAccounts()
        summary = await connection.ib.accountSummaryAsync()
        return accounts, summary

    try:
        accounts, summary = connection.run_coroutine(_fetch_summary()).result(timeout=settings.ibkr.timeout_seconds + 5)
    except Exception as exc:  # noqa: BLE001
        print(f"FAILED: {exc}", file=sys.stderr)
        connection.stop()
        sys.exit(1)

    print(f"Managed accounts: {accounts}")
    print("Account summary:")
    for item in summary:
        print(f"  {item.tag:>20}: {item.value} {item.currency}")

    connection.stop()
    print("Smoke test OK.")


if __name__ == "__main__":
    main()
