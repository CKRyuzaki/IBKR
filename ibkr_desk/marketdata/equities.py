"""Daily stock/ETF bars from IBKR into the CSV archive (unadjusted TRADES + adjusted close)."""

from __future__ import annotations

import logging
from datetime import date
from pathlib import Path

import pandas as pd
from ib_async import IB

from ibkr_desk.core.config import EquityArchiveConfig
from ibkr_desk.core.ib import contracts as ibc
from ibkr_desk.core.ib.history import HistoryClient, bars_to_frame
from ibkr_desk.storage import csv_archive

logger = logging.getLogger(__name__)


def refresh_archive(ib: IB, cfg: EquityArchiveConfig, archive: Path, hist_interval_s: float) -> dict[str, int]:
    """Returns {symbol: rows_added}. Today's incomplete bar is skipped."""
    hist = HistoryClient(ib, hist_interval_s)
    cutoff = pd.Timestamp(date.today())
    added: dict[str, int] = {}
    for sym in cfg.symbols:
        c = ibc.qualify(ib, ibc.stock(sym, cfg.exchange))
        if c is None:
            logger.warning("%s: unknown to IBKR, skipped", sym)
            continue
        df = bars_to_frame(ib.run(hist.bars(c, cfg.duration, "1 day", "TRADES", use_rth=True)))
        if df.empty:
            logger.warning("%s: no data", sym)
            continue
        adj = bars_to_frame(ib.run(hist.bars(c, cfg.duration, "1 day", "ADJUSTED_LAST", use_rth=True)))
        if not adj.empty:
            df["adj_close"] = adj["close"]
        df = df[df.index < cutoff]
        added[sym] = csv_archive.merge_save(csv_archive.equity_path(archive, sym), df)
        logger.info("%s: %d bars, +%d new", sym, len(df), added[sym])
    return added
