"""Append-only CSV archive of daily bars: the plain-file backup that survives IBKR's ~1y
expired-futures limit, and the source Postgres is loaded from.

Rows are never deleted. On overlapping dates the newer fetch wins (settlement revisions).
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

BAR_COLS = ["open", "high", "low", "close", "volume"]


def read(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame(columns=BAR_COLS)
    return pd.read_csv(path, index_col=0, parse_dates=True)


def merge_save(path: Path, new: pd.DataFrame) -> int:
    """Union `new` into the file at `path`. Returns the number of rows added."""
    old = read(path)
    merged = pd.concat([old, new[~new.index.isin(old.index)]]) if len(old) else new.copy()
    overlap = new.index.intersection(old.index)
    if len(overlap):
        merged.loc[overlap, new.columns] = new.loc[overlap]
    merged = merged.sort_index()
    merged.index.name = "date"
    path.parent.mkdir(parents=True, exist_ok=True)
    merged.to_csv(path)
    return len(merged) - len(old)


def futures_path(archive: Path, product: str, year: int, month: int) -> Path:
    return archive / "futures" / f"{product}_{year}{month:02d}.csv"


def equity_path(archive: Path, symbol: str) -> Path:
    return archive / "equities" / f"{symbol}.csv"
