from datetime import datetime, timedelta, timezone

from ibkr_dashboard.data.models import AssetClass, Bar, Instrument, Tick
from ibkr_dashboard.data.storage import Storage


def test_insert_and_query_ticks(tmp_path):
    storage = Storage(tmp_path / "test.db")
    now = datetime.now(timezone.utc)
    storage.insert_ticks(
        [
            Tick(instrument_id="USD.EQ.AAPL", field="last", value=190.0, ts=now - timedelta(minutes=1)),
            Tick(instrument_id="USD.EQ.AAPL", field="last", value=191.5, ts=now),
            Tick(instrument_id="USD.EQ.MSFT", field="last", value=420.0, ts=now),
        ]
    )

    rows = storage.query_ticks(
        "USD.EQ.AAPL", "last", now - timedelta(minutes=5), now + timedelta(minutes=5)
    )
    assert [value for _, value in rows] == [190.0, 191.5]


def test_insert_and_query_bars_upserts_on_conflict(tmp_path):
    storage = Storage(tmp_path / "test.db")
    ts = datetime(2026, 1, 2, tzinfo=timezone.utc)
    storage.insert_bars(
        [Bar(instrument_id="USD.IDX.SPX", bar_size="1 day", ts=ts, open=1, high=2, low=0.5, close=1.5)]
    )
    # Re-insert the same (instrument_id, bar_size, ts) with different values -> should update, not duplicate.
    storage.insert_bars(
        [Bar(instrument_id="USD.IDX.SPX", bar_size="1 day", ts=ts, open=1, high=3, low=0.5, close=2.5)]
    )

    bars = storage.query_bars(
        "USD.IDX.SPX", "1 day", ts - timedelta(days=1), ts + timedelta(days=1)
    )
    assert len(bars) == 1
    assert bars[0].close == 2.5


def test_upsert_instrument(tmp_path):
    storage = Storage(tmp_path / "test.db")
    storage.upsert_instrument(
        Instrument(instrument_id="USD.IDX.SPX", currency="USD", asset_class=AssetClass.INDEX, display_name="S&P 500")
    )
    # Should not raise on conflict.
    storage.upsert_instrument(
        Instrument(instrument_id="USD.IDX.SPX", currency="USD", asset_class=AssetClass.INDEX, display_name="SPX")
    )
