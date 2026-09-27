"""Vectorised backtest of the curve-fly strategy.

No lookahead: a signal from close t is traded at close t+1+... per exec_lag (default 1, i.e. one
extra day of delay). Costs = commission + slippage per contract per side.

    python -m ibkr_desk.strategies.rates_rv.backtest --synthetic     # smoke test, no data needed
    rv-backtest --years 8 --walkforward --plot                       # real data from data/archive
"""

from __future__ import annotations

import argparse
import itertools
from pathlib import Path

import numpy as np
import pandas as pd

from ibkr_desk.core.config import FutureSpec
from ibkr_desk.settings import Settings, load_settings
from ibkr_desk.strategies.rates_rv.config import CostsConfig, FlyConfig, StrategyParams
from ibkr_desk.strategies.rates_rv.data import load_changes, synthetic_changes
from ibkr_desk.strategies.rates_rv.signals import fly_targets


def run_fly(changes: pd.DataFrame, fly: FlyConfig, products: dict[str, FutureSpec], params: StrategyParams,
            costs: CostsConfig, lag: int | None = None) -> pd.DataFrame:
    lag = params.exec_lag if lag is None else lag
    sig, target = fly_targets(changes, fly, products, params)
    held = target.shift(1 + lag).fillna(0.0)  # position earning day t's change
    gross = sum(held[p] * products[p].multiplier * changes[p] for p in held.columns)
    trades = held.diff().abs().fillna(held.abs())
    cost = sum(trades[p] * (costs.commission_per_contract + costs.slippage_ticks * products[p].tick_value)
               for p in held.columns)
    return pd.DataFrame({"gross": gross, "cost": cost, "pnl": gross - cost,
                         "turnover": trades.sum(axis=1), "z": sig["z"], "pos": sig["pos"]})


def metrics(pnl: pd.Series, pos: pd.Series | None = None) -> dict:
    pnl = pnl.dropna()
    if pnl.std() == 0 or len(pnl) < 30:
        return {"days": len(pnl)}
    eq = pnl.cumsum()
    m = {
        "days": len(pnl),
        "ann_pnl_usd": pnl.mean() * 252,
        "ann_vol_usd": pnl.std() * np.sqrt(252),
        "sharpe": pnl.mean() / pnl.std() * np.sqrt(252),
        "max_dd_usd": (eq - eq.cummax()).min(),
        "hit_rate": (pnl[pnl != 0] > 0).mean() if (pnl != 0).any() else np.nan,
    }
    if pos is not None:
        m["entries"] = int(((pos != 0) & (pos.shift(1).fillna(0) != pos)).sum())
    return m


def walk_forward(changes, fly, products, params, costs, train_years=3, step_months=6):
    """Every step_months, pick (z_window, entry_z) by trailing-train Sharpe, apply out-of-sample."""
    grid = list(itertools.product([40, 60, 90], [1.5, 2.0, 2.5]))
    runs = {g: run_fly(changes, fly, products, params.model_copy(update={"z_window": g[0], "entry_z": g[1]}),
                       costs)["pnl"] for g in grid}
    idx = changes.index
    out = pd.Series(0.0, index=idx)
    starts = pd.date_range(idx[0] + pd.DateOffset(years=train_years), idx[-1], freq=f"{step_months}MS")
    chosen = []
    for s in starts:
        e = s + pd.DateOffset(months=step_months)
        tr = slice(s - pd.DateOffset(years=train_years), s - pd.Timedelta(days=1))
        best = max(grid, key=lambda g: metrics(runs[g].loc[tr]).get("sharpe", -9))
        seg = runs[best].loc[s:e - pd.Timedelta(days=1)]
        out.loc[seg.index] = seg
        chosen.append((s.date(), best))
    out = out[out.index >= starts[0]] if len(starts) else out
    return out, chosen


def _fmt(m: dict) -> str:
    return "  ".join(f"{k}={v:,.2f}" for k, v in m.items())


def run_all(st: Settings, changes: pd.DataFrame, walkforward: bool = False, out=print) -> pd.Series:
    rv = st.rates_rv
    total = pd.Series(0.0, index=changes.index)
    for fly in rv.flies:
        if walkforward:
            pnl, chosen = walk_forward(changes, fly, st.futures, rv.strategy, rv.costs)
            out(f"\n[{fly.name}] walk-forward params: {chosen[-4:]}")
            m = metrics(pnl)
        else:
            r = run_fly(changes, fly, st.futures, rv.strategy, rv.costs)
            pnl = r["pnl"]
            m = metrics(pnl, r["pos"])
            out(f"\n[{fly.name}] cost drag: ${r['cost'].sum():,.0f}  gross: ${r['gross'].sum():,.0f}")
        out(f"[{fly.name}] " + _fmt(m))
        total = total.add(pnl, fill_value=0.0)
    if walkforward:  # drop the initial training period, where the walk-forward has no P&L
        nz = total[total != 0]
        if nz.empty:
            raise SystemExit("Walk-forward produced no P&L: need more history than the 3-year train window. "
                             "Run without --walkforward, or add older data to data/archive.")
        total = total[total.index >= nz.index[0]]
    out("\n[PORTFOLIO] " + _fmt(metrics(total)))
    return total


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--years", type=int, default=8)
    ap.add_argument("--synthetic", action="store_true")
    ap.add_argument("--walkforward", action="store_true")
    ap.add_argument("--plot", action="store_true")
    a = ap.parse_args()
    st = load_settings()

    if a.synthetic:
        print("*** SYNTHETIC DATA: smoke test only, results are meaningless for real markets ***")
        changes = synthetic_changes(st.futures)
    else:
        changes = load_changes(st.archive_path, st.futures, st.rates_rv.flies,
                               st.rates_rv.roll.days_before_month_start, a.years)
    print(f"Data: {len(changes)} days, {changes.index[0].date()} -> {changes.index[-1].date()}")
    total = run_all(st, changes, a.walkforward)
    if a.plot:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        total.cumsum().plot(title="Cumulative P&L (USD)")
        plt.tight_layout()
        out = Path("equity.png")
        plt.savefig(out, dpi=120)
        print(f"saved {out.resolve()}")


if __name__ == "__main__":
    main()
