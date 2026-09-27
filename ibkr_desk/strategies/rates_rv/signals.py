"""Butterfly construction, z-score signal, position state machine, vol-targeted sizing.

Unit fly: belly DV01 = -1, wings +0.5 each (DV01-neutral). Its daily change in bp-equivalent is
    u_t = sum_i w_i * m_i * dP_i / dv01_i
and the cumulative sum L_t is the (back-adjusted) fly level. Mean reversion is traded on
z(L). pos=+1 (long wings / short belly) profits when L rises, so we go long when z < -entry.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ibkr_desk.core.config import FutureSpec
from ibkr_desk.strategies.rates_rv.config import FlyConfig, StrategyParams


def fly_weights(fly: FlyConfig) -> dict[str, float]:
    return {fly.short_wing: 0.5, fly.belly: -1.0, fly.long_wing: 0.5}


def unit_change(changes: pd.DataFrame, w: dict[str, float], products: dict[str, FutureSpec]) -> pd.Series:
    return sum(w[p] * changes[p] * products[p].multiplier / products[p].dv01 for p in w)


def zscore(level: pd.Series, window: int) -> pd.Series:
    return (level - level.rolling(window).mean()) / level.rolling(window).std()


def positions(z: pd.Series, entry: float, exit_: float, stop: float, max_hold: int) -> pd.Series:
    """+1/-1/0 state machine. After a stop or time-out, wait for |z| < entry before re-entering."""
    pos = np.zeros(len(z))
    cur, held, wait_reset = 0, 0, False
    for i, zi in enumerate(z.to_numpy()):
        if np.isnan(zi):
            pos[i] = 0
            continue
        if wait_reset and abs(zi) < entry:
            wait_reset = False
        if cur != 0:
            held += 1
            if abs(zi) < exit_:
                cur = 0
            elif abs(zi) > stop or held > max_hold:
                cur, wait_reset = 0, True
        if cur == 0 and not wait_reset:
            if zi > entry:
                cur, held = -1, 0
            elif zi < -entry:
                cur, held = 1, 0
        pos[i] = cur
    return pd.Series(pos, index=z.index)


def dv01_budget(u: pd.Series, vol_window: int, target_vol: float, max_dv01: float) -> pd.Series:
    """Belly DV01 (USD/bp) such that the fly's expected daily vol equals target_vol."""
    sd = u.rolling(vol_window).std()
    return (target_vol / sd).clip(upper=max_dv01)


def fly_targets(changes: pd.DataFrame, fly: FlyConfig, products: dict[str, FutureSpec],
                params: StrategyParams) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Returns (sig, target): sig has u/level/z/pos/budget; target is signed integer contracts
    per product held after each close."""
    w = fly_weights(fly)
    u = unit_change(changes, w, products)
    level = u.cumsum()
    z = zscore(level, params.z_window)
    pos = positions(z, params.entry_z, params.exit_z, params.stop_z, params.max_hold_days)
    budget = dv01_budget(u, params.vol_window, params.target_daily_vol, params.max_belly_dv01)
    unit = pd.DataFrame({q: (budget * w[q] / products[q].dv01).round() for q in w})
    target = unit.mul(pos, axis=0).fillna(0.0)
    sig = pd.DataFrame({"u": u, "level": level, "z": z, "pos": pos, "budget": budget})
    return sig, target
