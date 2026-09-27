# IBKR Desk

One repo for everything that talks to Interactive Brokers and the data around it:

| Piece | What it does | Run |
|---|---|---|
| **Dashboard** | Dark Bloomberg-style Dash app: live quotes, charts, portfolio, Postgres data health, connection status. **Read-only.** | `uv run dashboard` |
| **Market-data archive** | Daily snapshot of IBKR futures + equities and free public rates (Treasury curve, SOFR, EFFR, FRED breakevens/TIPS/credit/VIX) into Postgres, with an append-only CSV backup. | `uv run archive-daily` |
| **Rates RV strategy** | DV01-neutral Treasury-futures butterflies: backtest and paper trader. | `uv run rv-backtest`, `uv run rv-trade` |

Paper account by default; every client refuses a live account unless `ibkr.allow_live: true`.
See [ARCHITECTURE.md](ARCHITECTURE.md) for the design.

## Layout

```
ibkr_desk/
  core/            shared by everything
    config.py        IBKR / Postgres / futures-spec config models, ClientRole
    providers.py     provider-agnostic connection status registry
    pubsub.py        in-process topic broker (with taps)
    models.py, time_utils.py
    ib/
      connection.py  THE place an IBKR connection is made: paper guard, client ids, reconnect + hooks
      contracts.py   stock/index/future factories + qualify
      history.py     paced historical-bar client (one pacer for every caller)
      execution.py   positions, P&L, marketable-limit orders
  storage/         sqlite.py (dashboard cache) | postgres.py (schemas, upserts) | csv_archive.py
  marketdata/      futures.py, equities.py, public_rates.py, backfill.py, jobs.py (daily snapshot)
  live/            market_data.py, portfolio_feed.py, quote_book.py  (streaming services)
  strategies/rates_rv/   config, signals, data, backtest, risk, trader
  dashboard/       app.py, server.py, ws_server.py, pages/, callbacks/, components/, theme.py
  universe.py, swaps/    G10 instrument universe and the swap-data stub
config/            config.example.yaml, instruments/*.yaml
scripts/           run_daily.bat, smoke_test_connection.py, backfill_once.py
tests/
data/              market_data.db (dashboard), archive/ (CSV backup)  -- gitignored
```

## Setup

Requires Python 3.12, [uv](https://docs.astral.sh/uv/), IB Gateway, and (for the archive/DATA tab) PostgreSQL.

```powershell
uv sync
copy config\config.example.yaml config\config.yaml     # edit ports / account if needed
copy .env.example .env                                  # then add the Postgres settings below
```

`.env` (gitignored) holds secrets. IBKR has no API key: you authenticate by logging into Gateway.
```
PGHOST=127.0.0.1
PGPORT=5432
PGUSER=postgres
PGPASSWORD=...
PGDATABASE=marketdata
```

### IB Gateway
1. Log in with your **paper** credentials. Gateway's top bar should show an account starting `DU`.
2. *Configure -> Settings -> API*: port 4002 (paper). Leave **Read-Only API unchecked** only if you will run `rv-trade --send`; the dashboard and archive work with it checked.
3. Keep Gateway running. Each client uses its own client id (base `ibkr.client_id` + role offset: dashboard 11, trader 12, archive 13, research 14, adhoc 15) so they can all connect at once.

## Dashboard

```powershell
uv run dashboard          # http://127.0.0.1:8500
```

| Tab | What you see |
|---|---|
| LIVE | Blotter of every subscribed instrument: bid / ask / last / spread / direction / age of last tick, plus a tick chart of the selected row. Banner says if the feed is down or silent. |
| CHARTS | GP-style price chart per G10 currency. |
| PORTFOLIO | Positions and account summary. |
| DATA | Snapshot health: per-dataset freshness (OK / WARN / STALE), the daily-job log (failures in red), and an explorer showing any Postgres dataset as **plot and table**. |
| STATUS | One card per provider (IBKR, Postgres, ...): state, endpoint, time in state, last data. The header always shows the same chips. |

The dashboard starts even when Gateway is down; subscriptions re-establish automatically after every reconnect.
To monitor another data source, register any object with a `name` and `status()` in `ibkr_desk.core.providers.registry`.

## Daily snapshot

```powershell
uv run archive-daily      # IBKR futures + equities -> data/archive/*.csv -> Postgres, plus rates
```
A step that returns less than requested (e.g. a symbol IBKR rejects) is recorded as a **failure** in `ops.snapshot_run`, shown on the DATA tab, and gives a non-zero exit code.

Scheduled on Windows as `ibkr_desk_daily_archive` (weekdays 23:30 local, after CME settlement) via `scripts\run_daily.bat`; output in `logs\daily.log`. Requires Gateway logged in on the paper account at that time.

Recreate the task with:
```powershell
schtasks /Create /TN ibkr_desk_daily_archive /TR "<repo>\scripts\run_daily.bat" /SC WEEKLY /D MON,TUE,WED,THU,FRI /ST 23:30
```

## Rates RV strategy

```powershell
uv run rv-backtest --synthetic                 # smoke test, no data needed (results meaningless)
uv run rv-backtest --years 8 --walkforward     # real data from data/archive (needs history)
uv run rv-trade                                # dry run: prints targets and the orders it WOULD send
uv run rv-trade --send                         # sends orders to the PAPER account
```
Safety: paper guard on connect; orders only with `--send`; per-leg and DV01 caps; daily-loss flatten; create a file named `KILL` in the repo root to flatten and halt. `futures.*.dv01` in config are approximations -- refresh them before trusting sizing.
IBKR serves only ~1 year of expired futures, so a multi-year walk-forward needs older data added to `data/archive/futures/`.

## Development

```powershell
uv run pytest
uv run ruff check .
```
