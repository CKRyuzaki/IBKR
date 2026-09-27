"""SQLite-backed tick/bar/instrument store.

SQLite (not DuckDB) because the workload is frequent small writes (live ticks) plus simple
range-scan reads (chart windows) -- SQLite's sweet spot. DuckDB's columnar/analytical strengths
aren't needed since there's no cross-instrument aggregation here.
"""

from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from ibkr_desk.core.models import Bar, Instrument, Tick

_SCHEMA = """
CREATE TABLE IF NOT EXISTS instruments (
    instrument_id TEXT PRIMARY KEY,
    currency TEXT NOT NULL,
    asset_class TEXT NOT NULL,
    display_name TEXT,
    is_real INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS ticks (
    id INTEGER PRIMARY KEY,
    instrument_id TEXT NOT NULL,
    ts INTEGER NOT NULL,
    field TEXT NOT NULL,
    value REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ticks_instr_ts ON ticks(instrument_id, ts);

CREATE TABLE IF NOT EXISTS bars (
    id INTEGER PRIMARY KEY,
    instrument_id TEXT NOT NULL,
    bar_size TEXT NOT NULL,
    ts INTEGER NOT NULL,
    open REAL,
    high REAL,
    low REAL,
    close REAL,
    volume REAL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_bars_instr_size_ts ON bars(instrument_id, bar_size, ts);
"""


def _to_epoch_ms(ts: datetime) -> int:
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return int(ts.timestamp() * 1000)


def _from_epoch_ms(ms: int) -> datetime:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc)


class Storage:
    """One instance per process. SQLite has a single writer anyway, so all writes are
    expected to come from the IBKR I/O thread; a lock guards the shared connection since
    sqlite3 connections aren't safe to use concurrently from multiple threads by default."""

    def __init__(self, db_path: Path) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL;")
        with self._conn:
            self._conn.executescript(_SCHEMA)

    @contextmanager
    def _cursor(self):
        with self._lock:
            cur = self._conn.cursor()
            try:
                yield cur
                self._conn.commit()
            finally:
                cur.close()

    def upsert_instrument(self, instrument: Instrument) -> None:
        with self._cursor() as cur:
            cur.execute(
                """INSERT INTO instruments (instrument_id, currency, asset_class, display_name, is_real)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(instrument_id) DO UPDATE SET
                     currency=excluded.currency, asset_class=excluded.asset_class,
                     display_name=excluded.display_name, is_real=excluded.is_real""",
                (
                    instrument.instrument_id,
                    instrument.currency,
                    instrument.asset_class.value,
                    instrument.display_name,
                    int(instrument.is_real),
                ),
            )

    def insert_tick(self, tick: Tick) -> None:
        self.insert_ticks([tick])

    def insert_ticks(self, ticks: list[Tick]) -> None:
        if not ticks:
            return
        with self._cursor() as cur:
            cur.executemany(
                "INSERT INTO ticks (instrument_id, ts, field, value) VALUES (?, ?, ?, ?)",
                [(t.instrument_id, _to_epoch_ms(t.ts), t.field, t.value) for t in ticks],
            )

    def insert_bars(self, bars: list[Bar]) -> None:
        if not bars:
            return
        with self._cursor() as cur:
            cur.executemany(
                """INSERT INTO bars (instrument_id, bar_size, ts, open, high, low, close, volume)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(instrument_id, bar_size, ts) DO UPDATE SET
                     open=excluded.open, high=excluded.high, low=excluded.low,
                     close=excluded.close, volume=excluded.volume""",
                [
                    (b.instrument_id, b.bar_size, _to_epoch_ms(b.ts), b.open, b.high, b.low, b.close, b.volume)
                    for b in bars
                ],
            )

    def query_ticks(
        self, instrument_id: str, field: str, start: datetime, end: datetime
    ) -> list[tuple[datetime, float]]:
        with self._cursor() as cur:
            cur.execute(
                """SELECT ts, value FROM ticks
                   WHERE instrument_id = ? AND field = ? AND ts BETWEEN ? AND ?
                   ORDER BY ts ASC""",
                (instrument_id, field, _to_epoch_ms(start), _to_epoch_ms(end)),
            )
            rows = cur.fetchall()
        return [(_from_epoch_ms(ts), value) for ts, value in rows]

    def query_bars(
        self, instrument_id: str, bar_size: str, start: datetime, end: datetime
    ) -> list[Bar]:
        with self._cursor() as cur:
            cur.execute(
                """SELECT ts, open, high, low, close, volume FROM bars
                   WHERE instrument_id = ? AND bar_size = ? AND ts BETWEEN ? AND ?
                   ORDER BY ts ASC""",
                (instrument_id, bar_size, _to_epoch_ms(start), _to_epoch_ms(end)),
            )
            rows = cur.fetchall()
        return [
            Bar(
                instrument_id=instrument_id,
                bar_size=bar_size,
                ts=_from_epoch_ms(ts),
                open=o,
                high=h,
                low=lo,
                close=c,
                volume=v,
            )
            for ts, o, h, lo, c, v in rows
        ]

    def latest_bar(self, instrument_id: str, bar_size: str) -> Bar | None:
        with self._cursor() as cur:
            cur.execute(
                """SELECT ts, open, high, low, close, volume FROM bars
                   WHERE instrument_id = ? AND bar_size = ?
                   ORDER BY ts DESC LIMIT 1""",
                (instrument_id, bar_size),
            )
            row = cur.fetchone()
        if row is None:
            return None
        ts, o, h, lo, c, v = row
        return Bar(
            instrument_id=instrument_id, bar_size=bar_size, ts=_from_epoch_ms(ts),
            open=o, high=h, low=lo, close=c, volume=v,
        )

    def close(self) -> None:
        with self._lock:
            self._conn.close()
