"""Free FRED (St. Louis Fed) series into Postgres schema `rates`, table `fred_series`.

Uses the public fredgraph.csv download (no API key needed), the same mechanism FRED's own site
charts use. For a more robust/documented integration (rate limits, richer metadata), switch to
the official api.stlouisfed.org endpoint with a free API key -- this module deliberately avoids
that dependency so `archive-daily` needs no credentials beyond Postgres.

Series are declared once in `SERIES`; add a row there to archive another one. Chosen to complement
what's already free elsewhere (Treasury par curve, NY Fed SOFR/EFFR): breakevens, TIPS real
yields, credit spreads and equity vol -- none of which those sources cover.
"""

from __future__ import annotations

import io
import logging
import urllib.request
from datetime import date, timedelta

import pandas as pd
import psycopg

logger = logging.getLogger(__name__)

BASE = "https://fred.stlouisfed.org/graph/fredgraph.csv"
UA = {"User-Agent": "Mozilla/5.0 (ibkr_desk research)"}

# series_id -> (label, category, approximate series start)
SERIES: dict[str, tuple[str, str, date]] = {
    "T10YIE": ("10Y Breakeven Inflation", "inflation", date(2003, 1, 2)),
    "T5YIE": ("5Y Breakeven Inflation", "inflation", date(2003, 1, 2)),
    "DFII10": ("10Y TIPS Real Yield", "rates", date(2003, 1, 2)),
    "DFII5": ("5Y TIPS Real Yield", "rates", date(2003, 1, 2)),
    # BAML/ICE series: the anonymous fredgraph.csv download ignores `cosd` for these and always
    # returns only the trailing ~3 years, regardless of the requested start -- a FRED licensing
    # restriction on ICE-sourced data (full history since 1996-12-31 needs the keyed API instead).
    "BAMLC0A0CM": ("US IG Corporate OAS", "credit", date(1996, 12, 31)),
    "BAMLH0A0HYM2": ("US HY Corporate OAS", "credit", date(1996, 12, 31)),
    "VIXCLS": ("CBOE VIX", "equity_vol", date(1990, 1, 2)),
}


def _get(url: str, timeout: int = 60) -> bytes:
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
        return r.read()


def fetch(series_id: str, since: date) -> pd.DataFrame:
    """[date, value], missing observations (FRED uses ".") dropped."""
    url = f"{BASE}?id={series_id}&cosd={since.isoformat()}"
    df = pd.read_csv(io.BytesIO(_get(url)))
    df.columns = ["date", "value"]
    df["date"] = pd.to_datetime(df["date"]).dt.date
    df["value"] = pd.to_numeric(df["value"], errors="coerce")  # "." (no observation) -> NaN
    return df.dropna(subset=["value"])


def _since(conn: psycopg.Connection, series_id: str, default: date) -> date:
    d = conn.execute("select max(obs_date) from rates.fred_series where series_id = %s", (series_id,)).fetchone()[0]
    return max(default, d - timedelta(days=15)) if d else default


def load_series(conn: psycopg.Connection, series_id: str, label: str, category: str, since: date) -> int:
    df = fetch(series_id, since)
    rows = [(series_id, label, category, d, float(v)) for d, v in df.itertuples(index=False) if d >= since]
    with conn.cursor() as cur:
        cur.executemany(
            """insert into rates.fred_series (series_id, label, category, obs_date, value)
               values (%s,%s,%s,%s,%s)
               on conflict (series_id, obs_date) do update set value = excluded.value,
                 label = excluded.label, category = excluded.category""", rows)
    return len(rows)


def refresh(conn: psycopg.Connection) -> dict[str, int]:
    """Full history on first run per series, then incremental (last ~15 days re-fetched)."""
    out: dict[str, int] = {}
    for series_id, (label, category, first) in SERIES.items():
        out[series_id] = load_series(conn, series_id, label, category, _since(conn, series_id, first))
    conn.commit()
    return out
