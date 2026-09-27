"""Free public rates data into Postgres schema `rates`: US Treasury par yield curve (1990+) from
home.treasury.gov and SOFR / EFFR from the NY Fed reference-rate API. No IBKR involved."""

from __future__ import annotations

import io
import json
import logging
import urllib.request
from datetime import date, timedelta

import pandas as pd
import psycopg

logger = logging.getLogger(__name__)

TSY = ("https://home.treasury.gov/resource-center/data-chart-center/interest-rates/daily-treasury-rates.csv/"
       "{y}/all?type=daily_treasury_yield_curve&field_tdr_date_value={y}&page&_format=csv")
NYF = "https://markets.newyorkfed.org/api/rates/{kind}/{name}/search.json?startDate={a}&endDate={b}"
UA = {"User-Agent": "Mozilla/5.0 (ibkr_desk research)"}


def _get(url: str, timeout: int = 90) -> bytes:
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
        return r.read()


def _num(v) -> float | None:
    """NY Fed returns 'NA' / '' / None for missing values."""
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _since(conn: psycopg.Connection, table: str, col: str, default: date) -> date:
    d = conn.execute(f"select max({col}) from {table}").fetchone()[0]
    return d - timedelta(days=15) if d else default


def load_treasury(conn: psycopg.Connection, since: date) -> int:
    n = 0
    for y in range(since.year, date.today().year + 1):
        df = pd.read_csv(io.BytesIO(_get(TSY.format(y=y))))
        df["Date"] = pd.to_datetime(df["Date"], format="%m/%d/%Y").dt.date
        long = df.melt(id_vars="Date", var_name="tenor", value_name="y").dropna()
        rows = [(d, t, float(v)) for d, t, v in long.itertuples(index=False) if d >= since]
        with conn.cursor() as cur:
            cur.executemany("""insert into rates.treasury_par_yield values (%s,%s,%s)
                               on conflict (curve_date, tenor) do update set yield_pct = excluded.yield_pct""", rows)
        n += len(rows)
    return n


def load_overnight(conn: psycopg.Connection, rate_type: str, kind: str, name: str, first: date, since: date) -> int:
    n, start = 0, max(since, first)
    while start <= date.today():
        end = min(start + timedelta(days=364), date.today())
        data = json.loads(_get(NYF.format(kind=kind, name=name, a=start, b=end)))["refRates"]
        rows = [(date.fromisoformat(r["effectiveDate"]), rate_type, _num(r.get("percentRate")),
                 _num(r.get("percentPercentile1")), _num(r.get("percentPercentile25")),
                 _num(r.get("percentPercentile75")), _num(r.get("percentPercentile99")),
                 _num(r.get("volumeInBillions"))) for r in data]
        with conn.cursor() as cur:
            cur.executemany("""insert into rates.overnight_rate values (%s,%s,%s,%s,%s,%s,%s,%s)
                               on conflict (rate_date, rate_type) do update set rate_pct = excluded.rate_pct,
                               p1 = excluded.p1, p25 = excluded.p25, p75 = excluded.p75, p99 = excluded.p99,
                               volume_bn = excluded.volume_bn""", rows)
        n += len(rows)
        start = end + timedelta(days=1)
    return n


def refresh(conn: psycopg.Connection) -> dict[str, int]:
    """Full history on first run, then incremental (last ~15 days re-fetched)."""
    out = {"treasury": load_treasury(conn, _since(conn, "rates.treasury_par_yield", "curve_date", date(1990, 1, 1)))}
    conn.commit()
    s = _since(conn, "rates.overnight_rate", "rate_date", date(2000, 1, 1))
    out["sofr"] = load_overnight(conn, "SOFR", "secured", "sofr", date(2018, 4, 2), s)
    out["effr"] = load_overnight(conn, "EFFR", "unsecured", "effr", date(2000, 7, 3), s)
    conn.commit()
    return out
