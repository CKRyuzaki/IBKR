from datetime import date

import pandas as pd

from ibkr_desk.marketdata import futures
from ibkr_desk.storage import csv_archive


def _bars(dates, close, **extra):
    idx = pd.to_datetime(dates)
    df = pd.DataFrame({"open": close, "high": close, "low": close, "close": close, "volume": 1.0, **extra}, index=idx)
    df.index.name = "date"
    return df


def test_merge_save_appends_and_never_deletes(tmp_path):
    f = tmp_path / "ZN_202612.csv"
    assert csv_archive.merge_save(f, _bars(["2026-01-02", "2026-01-05"], [100.0, 101.0])) == 2
    # newer fetch: overlaps one old date (revised) and adds one new; the 2026-01-02 row is absent from it
    added = csv_archive.merge_save(f, _bars(["2026-01-05", "2026-01-06"], [101.5, 102.0]))
    out = csv_archive.read(f)
    assert added == 1
    assert list(out["close"]) == [100.0, 101.5, 102.0]  # old row kept, overlap refreshed


def test_merge_save_is_idempotent(tmp_path):
    f = tmp_path / "x.csv"
    df = _bars(["2026-01-02", "2026-01-05"], [1.0, 2.0])
    csv_archive.merge_save(f, df)
    assert csv_archive.merge_save(f, df) == 0


def test_contract_months_are_quarterly():
    months = futures.contract_months(date(2026, 9, 27), back=1, fwd=2)
    assert months == [(2026, 6), (2026, 9), (2026, 12), (2027, 3)]


def test_roll_schedule_is_contiguous_and_rolls_before_month_start():
    sched = futures.contract_schedule(date(2025, 1, 1), date(2026, 9, 27), 10)
    for (_, _, _, prev_to), (_, _, nxt_from, _) in zip(sched, sched[1:]):
        assert prev_to == nxt_from  # exactly one contract held on every day
    assert futures.held_contract(sched, date(2026, 9, 27)) == (2026, 12)  # Sept contract rolled ~Aug 22
    assert futures.held_contract(sched, date(2026, 8, 21)) == (2026, 9)


def test_product_changes_never_span_a_roll():
    sched = [(2026, 9, date(2026, 6, 20), date(2026, 8, 22)), (2026, 12, date(2026, 8, 22), date(2026, 11, 20))]
    old = pd.Series([100.0, 101.0, 102.0], index=pd.to_datetime(["2026-08-20", "2026-08-21", "2026-08-24"]))
    new = pd.Series([90.0, 91.0, 93.0], index=pd.to_datetime(["2026-08-20", "2026-08-21", "2026-08-24"]))
    ch = futures.product_changes({(2026, 9): old, (2026, 12): new}, sched)
    # 08-21 change comes from the old contract (+1), 08-24 from the NEW one (+2): the 100->93 jump never appears
    assert ch.loc["2026-08-21"] == 1.0
    assert ch.loc["2026-08-24"] == 2.0
