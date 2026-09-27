"""Quarterly futures: the contract calendar, the archive refresh from IBKR, and roll-consistent
daily price changes.

There is exactly one fetch path (`refresh_archive`) that writes to the CSV archive; backtests and
the live trader read from the archive rather than each keeping their own IBKR fetch + cache.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
from ib_async import IB

from ibkr_desk.core.config import FutureSpec
from ibkr_desk.core.ib import contracts as ibc
from ibkr_desk.core.ib.history import HistoryClient, bars_to_frame
from ibkr_desk.storage import csv_archive

logger = logging.getLogger(__name__)

QUARTER_MONTHS = (3, 6, 9, 12)


# --- calendar -------------------------------------------------------------------------------
def contract_months(today: date, back: int = 6, fwd: int = 4) -> list[tuple[int, int]]:
    """Quarterly (H/M/U/Z) contract (year, month)s from `back` quarters ago to `fwd` ahead."""
    q = today.year * 4 + (today.month - 1) // 3
    return [(n // 4, (n % 4 + 1) * 3) for n in range(q - back, q + fwd + 1)]


def roll_date(year: int, month: int, days_before: int) -> date:
    return date(year, month, 1) - timedelta(days=days_before)


def contract_schedule(start: date, end: date, days_before: int) -> list[tuple[int, int, date, date]]:
    """[(year, month, hold_from, hold_to)]: the contract is the held one on hold_from <= d < hold_to."""
    rolls = sorted(
        (y, m, roll_date(y, m, days_before))
        for y in range(start.year - 1, end.year + 2)
        for m in QUARTER_MONTHS
    )
    sched = []
    for prev, cur in zip(rolls, rolls[1:]):
        frm, to = prev[2], cur[2]
        if to > start and frm <= end:
            sched.append((cur[0], cur[1], frm, to))
    return sched


def held_contract(sched, day: date) -> tuple[int, int]:
    for y, m, frm, to in sched:
        if frm <= day < to:
            return y, m
    raise ValueError(f"no contract scheduled for {day}")


# --- archive refresh (the only IBKR fetch path for futures bars) -----------------------------
def refresh_archive(ib: IB, products: dict[str, FutureSpec], archive: Path, hist_interval_s: float,
                    today: date | None = None) -> dict[str, int]:
    """Fetch every contract IBKR still serves and merge into the CSV archive.
    Returns {"{PRODUCT}_{YYYYMM}": rows_added}. Today's incomplete bar is skipped."""
    today = today or date.today()
    hist = HistoryClient(ib, hist_interval_s)
    cutoff = pd.Timestamp(today)
    added: dict[str, int] = {}
    for product, spec in products.items():
        for y, m in contract_months(today):
            c = ibc.qualify(ib, ibc.future(product, spec.exchange, month=ibc.month_code(y, m), include_expired=True))
            if c is None:
                continue
            df = bars_to_frame(ib.run(hist.bars(c, "2 Y", "1 day", use_rth=False)))
            df = df[df.index < cutoff]
            if df.empty:
                continue
            added[f"{product}_{y}{m:02d}"] = csv_archive.merge_save(csv_archive.futures_path(archive, product, y, m), df)
            logger.info("%s_%s%02d: %d bars, +%d new", product, y, m, len(df), added[f"{product}_{y}{m:02d}"])
    return added


# --- reading the archive ---------------------------------------------------------------------
def read_closes(archive: Path, product: str, year: int, month: int) -> pd.Series | None:
    path = csv_archive.futures_path(archive, product, year, month)
    if not path.exists():
        return None
    df = csv_archive.read(path)
    return df["close"].dropna() if "close" in df else None


def product_changes(closes: dict[tuple[int, int], pd.Series], sched) -> pd.Series:
    """Daily price changes (points), each taken within the contract held the prior day so roll
    gaps never enter P&L."""
    parts = []
    for y, m, frm, to in sched:
        s = closes.get((y, m))
        if s is None:
            continue
        d = s.diff()
        parts.append(d[(d.index > pd.Timestamp(frm)) & (d.index <= pd.Timestamp(to))].dropna())
    if not parts:
        return pd.Series(dtype=float)
    out = pd.concat(parts)
    return out[~out.index.duplicated()].sort_index()
