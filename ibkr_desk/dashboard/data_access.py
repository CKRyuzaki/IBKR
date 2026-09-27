"""Read-only Postgres queries behind the Data panel: dataset freshness, snapshot-job history, and
time-series retrieval for the explorer.

Datasets are declared in `DATASETS`; adding a new table to the panel is one entry. SQL identifiers
only ever come from this registry (never from user input); user-chosen values are bound parameters.
The dashboard only reads: this module never writes.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

import numpy as np
import pandas as pd
import psycopg

from ibkr_desk.core.config import PostgresConfig
from ibkr_desk.storage.postgres import connect


@dataclass(frozen=True)
class Dataset:
    key: str
    label: str
    table: str
    date_col: str
    keys: tuple[tuple[str, str], ...]  # (column, label), in selection order (max 2 in the UI)
    value_cols: tuple[str, ...]
    ohlc: bool = False  # has open/high/low/close -> candlestick available
    freshness_by: tuple[str, ...] = ()  # columns to break freshness down by (default: whole table)
    max_lag_bd: int = 2  # business days behind "today" still considered healthy


DATASETS: dict[str, Dataset] = {
    d.key: d
    for d in (
        Dataset("futures", "Futures daily bars", "futures.daily_bar", "bar_date",
                (("product", "Product"), ("contract_month", "Contract")),
                ("open", "high", "low", "close", "volume"), ohlc=True, freshness_by=("product",)),
        Dataset("equities", "Equities / ETF daily bars", "equities.daily_bar", "bar_date",
                (("symbol", "Symbol"),),
                ("open", "high", "low", "close", "volume", "adj_close"), ohlc=True, freshness_by=("symbol",)),
        Dataset("treasury", "US Treasury par yield curve", "rates.treasury_par_yield", "curve_date",
                (("tenor", "Tenor"),), ("yield_pct",), freshness_by=()),
        Dataset("overnight", "Overnight rates (SOFR / EFFR)", "rates.overnight_rate", "rate_date",
                (("rate_type", "Rate"),),
                ("rate_pct", "p1", "p25", "p75", "p99", "volume_bn"), freshness_by=("rate_type",), max_lag_bd=3),
        Dataset("fred", "FRED (breakevens, TIPS, credit, VIX)", "rates.fred_series", "obs_date",
                (("label", "Series"),), ("value",), freshness_by=("label",), max_lag_bd=3),
    )
}

RANGES = {"1M": 31, "3M": 92, "6M": 183, "1Y": 366, "3Y": 1096, "5Y": 1827, "Max": None}


def _rows(cur) -> pd.DataFrame:
    cols = [d.name for d in cur.description]
    return pd.DataFrame(cur.fetchall(), columns=cols)


def lag_business_days(last: date, today: date | None = None) -> int:
    return int(np.busday_count(last, today or date.today()))


def _status(lag: int, max_lag: int) -> str:
    return "OK" if lag <= max_lag else "WARN" if lag <= max_lag + 2 else "STALE"


def freshness(cfg: PostgresConfig) -> list[dict]:
    """One row per dataset (and per freshness_by key): rows, first/last date, business-day lag, status."""
    out: list[dict] = []
    with connect(cfg) as conn:
        for ds in DATASETS.values():
            by = ", ".join(ds.freshness_by)
            sel = f"{by}, " if by else ""
            grp = f"group by {by}" if by else ""
            cur = conn.execute(
                f"select {sel}count(*) n, min({ds.date_col}) first, max({ds.date_col}) last from {ds.table} {grp} order by 1"
            )
            df = _rows(cur)
            if df.empty:
                out.append({"dataset": ds.label, "key": "", "rows": 0, "first": "", "last": "", "lag_bd": None, "status": "EMPTY"})
                continue
            for r in df.itertuples(index=False):
                d = r._asdict()
                lag = lag_business_days(d["last"])
                out.append({
                    "dataset": ds.label, "key": " / ".join(str(d[c]) for c in ds.freshness_by),
                    "rows": int(d["n"]), "first": str(d["first"]), "last": str(d["last"]),
                    "lag_bd": lag, "status": _status(lag, ds.max_lag_bd),
                })
    return out


def snapshot_runs(cfg: PostgresConfig, limit: int = 40) -> list[dict]:
    """Most recent daily-snapshot steps (from ops.snapshot_run), newest first."""
    with connect(cfg) as conn:
        cur = conn.execute("select run_at, step, ok, detail from ops.snapshot_run order by run_at desc limit %s", (limit,))
        df = _rows(cur)
    return [
        {"run_at": pd.Timestamp(r.run_at).to_pydatetime().astimezone().strftime("%Y-%m-%d %H:%M:%S"), "step": r.step,
         "status": "OK" if r.ok else "FAIL", "detail": (r.detail or "")[:200]}
        for r in df.itertuples(index=False)
    ]


def hours_since_last_run(cfg: PostgresConfig) -> float | None:
    with connect(cfg) as conn:
        row = conn.execute("select extract(epoch from now() - max(run_at)) / 3600 from ops.snapshot_run").fetchone()
    return None if row is None or row[0] is None else float(row[0])


def distinct_values(cfg: PostgresConfig, ds: Dataset, col: str, where: dict[str, str] | None = None) -> list[str]:
    where = {k: v for k, v in (where or {}).items() if v}
    clause = " and ".join(f"{k} = %s" for k in where) or "true"
    desc = "desc" if col == "contract_month" else ""
    with connect(cfg) as conn:
        cur = conn.execute(f"select distinct {col} from {ds.table} where {clause} order by 1 {desc}", tuple(where.values()))
        return [str(r[0]).strip() for r in cur.fetchall()]


def default_key(cfg: PostgresConfig, ds: Dataset, level: int, options: list[str], parent: str | None = None) -> str | None:
    """Sensible initial selection: ZN if present, and for contracts the one with the most history
    i.e. the front contract: still trading (latest bar), then most history -- not an expired one."""
    if not options:
        return None
    if level == 0:
        return "ZN" if "ZN" in options else options[0]
    if ds.key == "futures" and parent:
        with connect(cfg) as conn:
            row = conn.execute(
                f"select contract_month from {ds.table} where {ds.keys[0][0]} = %s "
                f"group by contract_month order by max({ds.date_col}) desc, count(*) desc, contract_month limit 1", (parent,)).fetchone()
        if row:
            return str(row[0]).strip()
    return options[0]


def fetch_series(cfg: PostgresConfig, ds: Dataset, key_vals: dict[str, str], range_key: str = "1Y",
                 limit: int = 20000) -> pd.DataFrame:
    """Time series for the selected keys, oldest first, indexed by `date`."""
    where = {k: v for k, v in key_vals.items() if v}
    clauses = [f"{k} = %s" for k in where]
    params: list = list(where.values())
    days = RANGES.get(range_key)
    if days:
        clauses.append(f"{ds.date_col} >= %s")
        params.append(date.today() - timedelta(days=days))
    sql = (f"select {ds.date_col} as date, {', '.join(ds.value_cols)} from {ds.table} "
           f"where {' and '.join(clauses) or 'true'} order by {ds.date_col} desc limit %s")
    with connect(cfg) as conn:
        df = _rows(conn.execute(sql, (*params, limit)))
    return df.sort_values("date").reset_index(drop=True)


def postgres_error(exc: Exception) -> str:
    return f"Postgres unavailable: {str(exc).splitlines()[0] if str(exc) else type(exc).__name__}"


PostgresError = psycopg.Error
