"""Price-change inputs for the rates RV strategy: from the futures CSV archive, or synthetic."""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from ibkr_desk.core.config import FutureSpec
from ibkr_desk.marketdata import futures
from ibkr_desk.strategies.rates_rv.config import FlyConfig


def load_changes(archive: Path, products: dict[str, FutureSpec], flies: list[FlyConfig],
                 roll_days_before: int, years: int = 8) -> pd.DataFrame:
    """[date x product] roll-consistent daily price changes (points) from the archive.
    Raises if the archive holds nothing usable (run `archive-daily` first)."""
    today = date.today()
    start = today - timedelta(days=int(365.25 * years))
    sched = futures.contract_schedule(start, today, roll_days_before)
    needed = sorted({p for fly in flies for p in fly.legs})
    out = {}
    for prod in needed:
        closes = {}
        for y, m, _frm, _to in sched:
            s = futures.read_closes(archive, prod, y, m)
            if s is not None:
                closes[(y, m)] = s
        out[prod] = futures.product_changes(closes, sched)
    df = pd.DataFrame(out).dropna()
    if df.empty:
        raise RuntimeError(f"No futures history in {archive}. Run `archive-daily` (needs IB Gateway) first.")
    return df[df.index >= pd.Timestamp(start)]


def synthetic_changes(products: dict[str, FutureSpec], n_days: int = 2000, seed: int = 7) -> pd.DataFrame:
    """Smoke-test data ONLY: 4 tenors = common level/slope shocks + mean-reverting idiosyncratic
    noise. Results on this data say nothing about real-market profitability."""
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=n_days)
    level = np.cumsum(rng.normal(0, 5, n_days))
    slope = np.cumsum(rng.normal(0, 1.5, n_days))
    loadings = np.array([-1.0, -0.4, 0.4, 1.0])
    tenor = {"ZT": 0, "ZF": 1, "ZN": 2, "TN": 2, "ZB": 3}

    def ou(theta=0.08, sig=0.8):
        x = np.zeros(n_days)
        for i in range(1, n_days):
            x[i] = x[i - 1] * (1 - theta) + rng.normal(0, sig)
        return x

    yields = [level + loadings[k] * slope + ou() for k in range(4)]
    out = {}
    for prod, k in tenor.items():
        spec = products[prod]
        dy = np.diff(yields[k], prepend=yields[k][0])  # bp
        out[prod] = pd.Series(-dy * spec.dv01 / spec.multiplier, index=idx)
    return pd.DataFrame(out).iloc[1:]
