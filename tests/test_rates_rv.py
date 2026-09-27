"""Strategy tests. The synthetic-data numbers are a regression lock taken from the original standalone
rv_bot implementation: the port into this package must reproduce them exactly."""

import numpy as np
import pandas as pd
import pytest

from ibkr_desk.core.config import DEFAULT_TREASURY_FUTURES as PRODUCTS
from ibkr_desk.strategies.rates_rv.backtest import metrics, run_fly
from ibkr_desk.strategies.rates_rv.config import FlyConfig, RatesRVConfig, RiskConfig
from ibkr_desk.strategies.rates_rv.data import synthetic_changes
from ibkr_desk.strategies.rates_rv.risk import RiskManager
from ibkr_desk.strategies.rates_rv.signals import fly_targets, fly_weights, positions

RV = RatesRVConfig()
FLY = RV.flies[0]  # 2s5s10s


def test_fly_is_dv01_neutral():
    w = fly_weights(FLY)
    dv01 = sum(w[p] * PRODUCTS[p].dv01 / PRODUCTS[p].dv01 for p in w)  # per-unit-DV01 weights
    assert dv01 == pytest.approx(0.0)


def test_positions_enter_exit_stop_and_wait_for_reset():
    z = pd.Series([0, 0, -2.5, -1.0, -0.2, 0.0, 2.5, 4.5, 3.0, 1.0, 2.5])
    pos = positions(z, entry=2.0, exit_=0.5, stop=4.0, max_hold=30)
    assert list(pos) == [0, 0, 1, 1, 0, 0, -1, 0, 0, 0, -1]  # stop at 4.5, no re-entry at 3.0 until |z|<entry


def test_targets_have_no_lookahead_on_last_row():
    changes = synthetic_changes(PRODUCTS, n_days=400)
    sig_a, tgt_a = fly_targets(changes, FLY, PRODUCTS, RV.strategy)
    sig_b, tgt_b = fly_targets(changes.iloc[:-1], FLY, PRODUCTS, RV.strategy)
    pd.testing.assert_frame_equal(tgt_a.iloc[:-1], tgt_b)  # appending a day never changes earlier targets


def test_regression_lock_against_original_rv_bot():
    changes = synthetic_changes(PRODUCTS)
    r = run_fly(changes, FLY, PRODUCTS, RV.strategy, RV.costs)
    assert r["cost"].sum() == pytest.approx(37585, abs=1)
    assert r["gross"].sum() == pytest.approx(183255, abs=1)
    m = metrics(r["pnl"], r["pos"])
    assert m["sharpe"] == pytest.approx(1.39, abs=0.005)
    assert m["ann_pnl_usd"] == pytest.approx(18363.56, abs=0.5)
    assert m["entries"] == 49


def test_execution_lag_delays_pnl():
    changes = synthetic_changes(PRODUCTS, n_days=600)
    a = run_fly(changes, FLY, PRODUCTS, RV.strategy, RV.costs, lag=0)
    b = run_fly(changes, FLY, PRODUCTS, RV.strategy, RV.costs, lag=1)
    assert not np.allclose(a["pnl"].fillna(0), b["pnl"].fillna(0))


def test_risk_clips_legs_then_scales_dv01(tmp_path):
    rm = RiskManager(RiskConfig(max_contracts_per_leg=50, max_total_abs_dv01=5000), PRODUCTS, tmp_path)
    assert rm.clip_targets({"ZN": 500})["ZN"] <= 50
    out = rm.clip_targets({"ZT": 50, "ZF": -50, "ZN": 50})
    assert sum(abs(q) * PRODUCTS[p].dv01 for p, q in out.items()) <= 5000


def test_risk_kill_file_and_daily_loss(tmp_path):
    rm = RiskManager(RiskConfig(max_daily_loss=1000, kill_file="KILL"), PRODUCTS, tmp_path)
    assert not rm.killed()
    (tmp_path / "KILL").write_text("")
    assert rm.killed()
    assert rm.daily_loss_breached(-1000) and not rm.daily_loss_breached(-999)
    assert not rm.daily_loss_breached(None)  # unknown P&L is not treated as a breach (trader warns loudly)


def test_fly_config_legs_order():
    assert FlyConfig(name="x", short_wing="ZT", belly="ZF", long_wing="ZN").legs == ("ZT", "ZF", "ZN")
