"""Postgres storage for archived market data: one schema per asset class.

    python -m ibkr_desk.storage.postgres init      # create schemas/tables (idempotent)
    python -m ibkr_desk.storage.postgres load      # upsert data/archive/** CSVs
    python -m ibkr_desk.storage.postgres summary   # row counts and date ranges

Schemas: futures (contract, daily_bar) | equities (daily_bar) | rates (treasury_par_yield, overnight_rate).
The CSV archive stays as the plain-file backup; loading is an idempotent upsert.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import psycopg

from ibkr_desk.core.config import FutureSpec, PostgresConfig
from ibkr_desk.storage import csv_archive

DDL = """
create schema if not exists futures;
create table if not exists futures.contract (
    product         text    not null,
    contract_month  char(6) not null,           -- YYYYMM
    exchange        text    not null,
    multiplier      numeric not null,
    tick_size       numeric not null,
    primary key (product, contract_month)
);
create table if not exists futures.daily_bar (
    product         text    not null,
    contract_month  char(6) not null,
    bar_date        date    not null,
    open double precision, high double precision, low double precision, close double precision,
    volume          double precision,
    loaded_at       timestamptz not null default now(),
    primary key (product, contract_month, bar_date),
    foreign key (product, contract_month) references futures.contract
);
create index if not exists daily_bar_date_idx on futures.daily_bar (bar_date);

create schema if not exists equities;
create table if not exists equities.daily_bar (
    symbol    text not null,
    bar_date  date not null,
    open double precision, high double precision, low double precision, close double precision,
    volume    double precision,
    adj_close double precision,
    loaded_at timestamptz not null default now(),
    primary key (symbol, bar_date)
);

create schema if not exists rates;
create table if not exists rates.treasury_par_yield (
    curve_date date not null,
    tenor      text not null,          -- '1 Mo','2 Yr','10 Yr', ...
    yield_pct  double precision not null,
    primary key (curve_date, tenor)
);
create table if not exists rates.overnight_rate (
    rate_date   date not null,
    rate_type   text not null,         -- SOFR, EFFR
    rate_pct    double precision, p1 double precision, p25 double precision,
    p75 double precision, p99 double precision, volume_bn double precision,
    primary key (rate_date, rate_type)
);

create table if not exists rates.fred_series (
    series_id text not null,
    label     text not null,
    category  text not null,
    obs_date  date not null,
    value     double precision not null,
    primary key (series_id, obs_date)
);
create index if not exists fred_series_label_idx on rates.fred_series (label);

create schema if not exists ops;
create table if not exists ops.snapshot_run (
    run_at  timestamptz not null default now(),
    step    text not null,
    ok      boolean not null,
    detail  text
);
"""


def connect(cfg: PostgresConfig) -> psycopg.Connection:
    return psycopg.connect(
        host=cfg.host, port=cfg.port, user=cfg.user,
        password=cfg.password.get_secret_value(), dbname=cfg.database,
    )


def init_schema(conn: psycopg.Connection) -> None:
    conn.execute(DDL)
    conn.commit()


def _num(v) -> float | None:
    return None if v is None or pd.isna(v) else float(v)


def upsert_futures_bars(conn: psycopg.Connection, product: str, month: str, spec: FutureSpec,
                        df: pd.DataFrame) -> int:
    if df.empty:
        return 0
    conn.execute("insert into futures.contract values (%s,%s,%s,%s,%s) on conflict do nothing",
                 (product, month, spec.exchange, spec.multiplier, spec.tick))
    rows = [(product, month, d.date(), *[_num(r.get(c)) for c in csv_archive.BAR_COLS]) for d, r in df.iterrows()]
    with conn.cursor() as cur:
        cur.executemany(
            """insert into futures.daily_bar (product, contract_month, bar_date, open, high, low, close, volume)
               values (%s,%s,%s,%s,%s,%s,%s,%s)
               on conflict (product, contract_month, bar_date) do update set
                 open = coalesce(excluded.open, futures.daily_bar.open),
                 high = coalesce(excluded.high, futures.daily_bar.high),
                 low = coalesce(excluded.low, futures.daily_bar.low),
                 close = coalesce(excluded.close, futures.daily_bar.close),
                 volume = coalesce(excluded.volume, futures.daily_bar.volume),
                 loaded_at = now()""", rows)
    return len(rows)


def upsert_equity_bars(conn: psycopg.Connection, symbol: str, df: pd.DataFrame) -> int:
    if df.empty:
        return 0
    cols = csv_archive.BAR_COLS + ["adj_close"]
    rows = [(symbol, d.date(), *[_num(r.get(c)) for c in cols]) for d, r in df.iterrows()]
    with conn.cursor() as cur:
        cur.executemany(
            """insert into equities.daily_bar (symbol, bar_date, open, high, low, close, volume, adj_close)
               values (%s,%s,%s,%s,%s,%s,%s,%s)
               on conflict (symbol, bar_date) do update set
                 open = coalesce(excluded.open, equities.daily_bar.open),
                 high = coalesce(excluded.high, equities.daily_bar.high),
                 low = coalesce(excluded.low, equities.daily_bar.low),
                 close = coalesce(excluded.close, equities.daily_bar.close),
                 volume = coalesce(excluded.volume, equities.daily_bar.volume),
                 adj_close = coalesce(excluded.adj_close, equities.daily_bar.adj_close),
                 loaded_at = now()""", rows)
    return len(rows)


def load_archive(conn: psycopg.Connection, archive: Path, futures: dict[str, FutureSpec]) -> dict[str, int]:
    """Upsert every CSV under `archive` into Postgres. Returns rows upserted per asset class."""
    n = {"futures": 0, "equities": 0}
    for f in sorted((archive / "futures").glob("*_*.csv")):
        product, month = f.stem.split("_")
        if product in futures:
            n["futures"] += upsert_futures_bars(conn, product, month, futures[product], csv_archive.read(f))
    for f in sorted((archive / "equities").glob("*.csv")):
        n["equities"] += upsert_equity_bars(conn, f.stem, csv_archive.read(f))
    conn.commit()
    return n


def summary(conn: psycopg.Connection) -> list[tuple]:
    return conn.execute(
        """select 'futures.daily_bar', count(*), min(bar_date), max(bar_date) from futures.daily_bar
           union all select 'equities.daily_bar', count(*), min(bar_date), max(bar_date) from equities.daily_bar
           union all select 'rates.treasury_par_yield', count(*), min(curve_date), max(curve_date) from rates.treasury_par_yield
           union all select 'rates.overnight_rate', count(*), min(rate_date), max(rate_date) from rates.overnight_rate"""
    ).fetchall()


def main() -> None:
    from ibkr_desk.settings import load_settings

    st = load_settings()
    cmd = sys.argv[1] if len(sys.argv) > 1 else "summary"
    with connect(st.postgres) as conn:
        if cmd == "init":
            init_schema(conn)
            print("schema ready")
        elif cmd == "load":
            init_schema(conn)
            print("upserted", load_archive(conn, st.archive_path, st.futures))
        else:
            for r in summary(conn):
                print(r)


if __name__ == "__main__":
    main()


class PostgresProbe:
    """Provider-registry probe (core/providers.py): can we log in to Postgres right now?
    Result cached for `ttl_s` so a fast-refreshing status panel does not open a connection per tick."""

    name = "Postgres"

    def __init__(self, cfg: PostgresConfig, ttl_s: float = 5.0) -> None:
        self._cfg, self._ttl = cfg, ttl_s
        self._cached = None
        self._at = 0.0

    def status(self):
        import time

        from ibkr_desk.core.providers import ConnState, ProviderStatus

        if self._cached is not None and time.monotonic() - self._at < self._ttl:
            return self._cached
        endpoint = f"{self._cfg.host}:{self._cfg.port}/{self._cfg.database}"
        t0 = time.monotonic()
        try:
            with psycopg.connect(
                host=self._cfg.host, port=self._cfg.port, user=self._cfg.user, dbname=self._cfg.database,
                password=self._cfg.password.get_secret_value(), connect_timeout=2,
            ) as c:
                c.execute("select 1")
            ms = (time.monotonic() - t0) * 1000
            st = ProviderStatus(self.name, ConnState.CONNECTED, endpoint, extra={"latency": f"{ms:.0f} ms"}, kind="storage")
        except Exception as exc:  # noqa: BLE001
            st = ProviderStatus(self.name, ConnState.ERROR, f"{endpoint}: {str(exc).splitlines()[0]}", kind="storage")
        self._cached, self._at = st, time.monotonic()
        return st
