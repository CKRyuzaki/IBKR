"""Paper-trading loop: archive refresh -> signals -> target contracts -> diff vs positions -> orders.

    rv-trade                  # compute + log targets and the orders it WOULD send (no orders)
    rv-trade --send           # actually send orders (to the paper account)
    rv-trade --send --loop    # repeat every rates_rv.live.interval_min minutes
    rv-trade --flatten --send

Run after the CME settlement (~16:15 ET): the last daily bar is used as the signal close.
Create a file named KILL in the repo root to flatten everything and halt.
"""

from __future__ import annotations

import argparse
import csv
import logging
import time
from datetime import date, datetime
from pathlib import Path

import pandas as pd

from ibkr_desk.core.config import ClientRole
from ibkr_desk.core.ib import contracts as ibc
from ibkr_desk.core.ib import execution
from ibkr_desk.core.ib.connection import connect_sync
from ibkr_desk.marketdata import futures
from ibkr_desk.settings import REPO_ROOT, Settings, load_settings
from ibkr_desk.strategies.rates_rv.data import load_changes
from ibkr_desk.strategies.rates_rv.risk import RiskManager
from ibkr_desk.strategies.rates_rv.signals import fly_targets

logger = logging.getLogger(__name__)


def _log_rows(path: Path, header: list, rows: list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    new = not path.exists()
    with open(path, "a", newline="") as f:
        w = csv.writer(f)
        if new:
            w.writerow(header)
        w.writerows(rows)


def compute_targets(st: Settings, changes: pd.DataFrame) -> tuple[dict[str, int], date]:
    """Sum the latest target contracts across flies -> {product: qty}."""
    rv = st.rates_rv
    totals: dict[str, float] = {}
    rows = []
    for fly in rv.flies:
        sig, target = fly_targets(changes, fly, st.futures, rv.strategy)
        last = sig.iloc[-1]
        for p, q in target.iloc[-1].items():
            totals[p] = totals.get(p, 0) + q
        rows.append([datetime.now().isoformat(timespec="seconds"), fly.name, sig.index[-1].date(),
                     round(last["z"], 3), int(last["pos"]), round(last["budget"], 1)])
        print(f"[{fly.name}] asof {sig.index[-1].date()} z={last['z']:.2f} pos={int(last['pos'])} "
              f"belly_dv01={last['budget']:.0f}")
    _log_rows(st.log_path / "signals.csv", ["ts", "fly", "asof", "z", "pos", "belly_dv01"], rows)
    return {p: int(round(q)) for p, q in totals.items()}, changes.index[-1].date()


def run_once(st: Settings, send: bool, flatten: bool) -> bool:
    rv = st.rates_rv
    risk = RiskManager(rv.risk, st.futures, REPO_ROOT)
    ib = connect_sync(st.ibkr, ClientRole.TRADER)
    try:
        today = date.today()
        sched = futures.contract_schedule(today, today, rv.roll.days_before_month_start)
        universe = {p for fly in rv.flies for p in fly.legs}
        current = execution.positions(ib, universe)

        pnl = execution.daily_pnl(ib, ib.managedAccounts()[0])
        if pnl is None:
            print("WARNING: daily P&L unavailable from IBKR; the daily-loss limit is NOT being enforced")
        halt = flatten or risk.killed() or risk.daily_loss_breached(pnl)
        if halt:
            print("HALT: flattening all positions (flatten flag / KILL file / daily loss limit)")
            desired: dict[int, tuple] = {}
        else:
            # Refresh the archive from IBKR on this connection, then compute from the archive.
            futures.refresh_archive(ib, {p: st.futures[p] for p in universe}, st.archive_path,
                                    st.ibkr.historical_request_interval_s)
            changes = load_changes(st.archive_path, st.futures, rv.flies, rv.roll.days_before_month_start,
                                   rv.live.lookback_years)
            targets, asof = compute_targets(st, changes)
            if (today - asof).days > 4:
                print(f"WARNING: latest bar {asof} is stale, skipping trading")
                return False
            targets = risk.clip_targets(targets)
            print("Targets (front contract):", targets)
            y, m = futures.held_contract(sched, today)
            desired = {}
            for p in universe:
                c = ibc.qualify(ib, ibc.future(p, st.futures[p].exchange, month=ibc.month_code(y, m)))
                if c is None:
                    raise RuntimeError(f"could not qualify {p} {y}{m:02d}")
                desired[c.conId] = (c, targets.get(p, 0))

        # stale-month / unwanted positions -> target 0 (this also handles rolls)
        book = {cid: (c, 0) for cid, (c, _) in current.items()}
        book.update(desired)
        rows = []
        for cid, (c, tgt) in book.items():
            have = current.get(cid, (None, 0))[1]
            delta = tgt - have
            if delta == 0:
                continue
            side = "BUY" if delta > 0 else "SELL"
            print(f"  {side} {abs(delta)} {c.localSymbol or c.symbol}  (pos {have} -> {tgt})")
            if not send:
                continue
            res = execution.marketable_limit(ib, c, delta, st.futures[c.symbol].tick, rv.live.order_timeout_s)
            print(f"    -> {res.status} limit={res.limit} filled={res.filled} @ {res.avg_fill}")
            rows.append([datetime.now().isoformat(timespec="seconds"), c.localSymbol, side, abs(delta),
                         res.limit, res.status, res.filled, res.avg_fill])
        if rows:
            _log_rows(st.log_path / "trades.csv",
                      ["ts", "contract", "side", "qty", "limit", "status", "filled", "avg_fill"], rows)
        if not send:
            print("(dry run: no orders sent; use --send)")
        return not halt
    finally:
        ib.disconnect()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("--send", action="store_true", help="actually send orders")
    ap.add_argument("--loop", action="store_true")
    ap.add_argument("--flatten", action="store_true")
    a = ap.parse_args()
    st = load_settings()
    while True:
        keep_going = run_once(st, a.send, a.flatten)
        if not a.loop or not keep_going:
            break
        time.sleep(st.rates_rv.live.interval_min * 60)


if __name__ == "__main__":
    main()
