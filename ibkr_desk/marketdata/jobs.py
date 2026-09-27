"""Daily snapshot job: IBKR futures + equities -> CSV archive -> Postgres, plus public rates.

    python -m ibkr_desk.marketdata.jobs          # or the `archive-daily` script

Each step is isolated: one failing step (e.g. Gateway not logged in) is logged and does not stop
the others. The exit code is non-zero if any step failed, so a scheduler can flag it. Every run is
recorded in the Postgres table `ops.snapshot_run` for the dashboard's data-health panel.
"""

from __future__ import annotations

import logging
import sys
import traceback

from ibkr_desk.core.config import ClientRole
from ibkr_desk.core.ib.connection import connect_sync
from ibkr_desk.marketdata import equities, fred, futures, public_rates
from ibkr_desk.settings import Settings, load_settings
from ibkr_desk.storage import postgres

logger = logging.getLogger("ibkr_desk.jobs")

def _record(conn, step: str, ok: bool, detail: str) -> None:
    conn.execute("insert into ops.snapshot_run (step, ok, detail) values (%s,%s,%s)", (step, ok, detail[:2000]))
    conn.commit()


def _step(conn, step: str, ok: bool, detail: str) -> bool:
    """Record a step; a step that returned less than asked for is a failure, not a silent success."""
    if not ok:
        logger.error("%s FAILED: %s", step, detail)
    _record(conn, step, ok, detail)
    return ok


def run_daily(st: Settings) -> bool:
    ok_all = True
    with postgres.connect(st.postgres) as conn:
        postgres.init_schema(conn)

        # 1) IBKR: refresh the CSV archive (futures + equities) on one connection
        try:
            ib = connect_sync(st.ibkr, ClientRole.ARCHIVE)
            try:
                gap = st.ibkr.historical_request_interval_s
                f = futures.refresh_archive(ib, st.futures, st.archive_path, gap)
                # expired contracts legitimately return nothing; but every product must yield *some* contract
                no_data = [p for p in st.futures if not any(k.startswith(p + "_") for k in f)]
                ok_all &= _step(conn, "ibkr_futures", not no_data,
                                f"+{sum(f.values())} rows / {len(f)} contracts" + (f"; NO DATA: {no_data}" if no_data else ""))
                e = equities.refresh_archive(ib, st.equities, st.archive_path, gap)
                missing = [s_ for s_ in st.equities.symbols if s_ not in e]
                ok_all &= _step(conn, "ibkr_equities", not missing,
                                f"+{sum(e.values())} rows / {len(e)} symbols" + (f"; NO DATA: {missing}" if missing else ""))
            finally:
                ib.disconnect()
        except Exception as exc:  # noqa: BLE001 -- isolate: the other steps still run
            ok_all = False
            logger.error("IBKR step failed: %s", exc)
            _record(conn, "ibkr", False, "".join(traceback.format_exception_only(type(exc), exc)))

        # 2) CSV archive -> Postgres
        try:
            n = postgres.load_archive(conn, st.archive_path, st.futures)
            _record(conn, "archive_to_postgres", True, str(n))
        except Exception as exc:  # noqa: BLE001
            ok_all = False
            conn.rollback()
            _record(conn, "archive_to_postgres", False, repr(exc))

        # 3) Free public rates
        try:
            _record(conn, "public_rates", True, str(public_rates.refresh(conn)))
        except Exception as exc:  # noqa: BLE001
            ok_all = False
            conn.rollback()
            _record(conn, "public_rates", False, repr(exc))

        # 4) Free FRED series (breakevens, TIPS real yields, credit spreads, VIX)
        try:
            _record(conn, "fred", True, str(fred.refresh(conn)))
        except Exception as exc:  # noqa: BLE001
            ok_all = False
            conn.rollback()
            _record(conn, "fred", False, repr(exc))
    return ok_all


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    sys.exit(0 if run_daily(load_settings()) else 1)


if __name__ == "__main__":
    main()
