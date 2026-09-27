from datetime import date
from unittest.mock import patch

from ibkr_desk.marketdata import fred


def _csv(rows: list[tuple[str, str]]) -> bytes:
    body = "DATE,VALUE\n" + "\n".join(f"{d},{v}" for d, v in rows)
    return body.encode()


class _FakeCursor:
    def __init__(self, sink):
        self._sink = sink

    def executemany(self, _sql, rows):
        self._sink.extend(rows)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class _FakeConn:
    """Records executemany() rows; execute() answers a configurable max(obs_date)."""

    def __init__(self, last_obs=None):
        self.written: list[tuple] = []
        self._last_obs = last_obs

    def cursor(self):
        return _FakeCursor(self.written)

    def execute(self, _sql, _params=None):
        class _Result:
            def __init__(self_, v):
                self_._v = v

            def fetchone(self_):
                return [self_._v]

        return _Result(self._last_obs)

    def commit(self):
        pass


def test_fetch_drops_missing_observations():
    raw = _csv([("2026-09-01", "1.23"), ("2026-09-02", "."), ("2026-09-03", "1.30")])
    with patch("ibkr_desk.marketdata.fred._get", return_value=raw):
        df = fred.fetch("T10YIE", date(2026, 9, 1))
    assert list(df["value"]) == [1.23, 1.30]
    assert list(df["date"]) == [date(2026, 9, 1), date(2026, 9, 3)]


def test_load_series_upserts_and_carries_label():
    conn = _FakeConn()
    raw = _csv([("2026-09-01", "1.0"), ("2026-09-02", "2.0")])
    with patch("ibkr_desk.marketdata.fred._get", return_value=raw):
        n = fred.load_series(conn, "T10YIE", "10Y Breakeven Inflation", "inflation", date(2026, 9, 1))
    assert n == 2
    assert {(sid, label, value) for sid, label, _cat, _d, value in conn.written} == {
        ("T10YIE", "10Y Breakeven Inflation", 1.0), ("T10YIE", "10Y Breakeven Inflation", 2.0)
    }


def test_load_series_drops_rows_older_than_since():
    conn = _FakeConn()
    raw = _csv([("2026-08-30", "9.9"), ("2026-09-01", "1.0")])  # fetch() may return a bit before `since`
    with patch("ibkr_desk.marketdata.fred._get", return_value=raw):
        n = fred.load_series(conn, "T10YIE", "L", "c", date(2026, 9, 1))
    assert n == 1
    assert [row[3] for row in conn.written] == [date(2026, 9, 1)]


def test_since_falls_back_to_default_when_no_rows():
    conn = _FakeConn(last_obs=None)
    assert fred._since(conn, "T10YIE", date(2003, 1, 2)) == date(2003, 1, 2)


def test_since_re_fetches_a_trailing_window_when_data_exists():
    conn = _FakeConn(last_obs=date(2026, 9, 20))
    assert fred._since(conn, "T10YIE", date(2003, 1, 2)) == date(2026, 9, 5)  # 15 days back


def test_refresh_loads_every_declared_series_once():
    calls = []

    def fake_load(_conn, series_id, _label, _category, _since):
        calls.append(series_id)
        return 1

    with patch("ibkr_desk.marketdata.fred.load_series", side_effect=fake_load):
        out = fred.refresh(_FakeConn())
    assert set(calls) == set(fred.SERIES)
    assert out == {k: 1 for k in fred.SERIES}
