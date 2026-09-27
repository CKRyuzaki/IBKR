# IBKR Desk — Architecture

One package, `ibkr_desk`, serving three products that all talk to Interactive Brokers (paper by
default): a read-only **dashboard**, a **market-data archive** (Postgres), and a **rates RV
strategy** (backtest + paper trader). Everything that touches the IBKR API lives once, in
`ibkr_desk/core/ib/`, so the three products share the same connection, contract, history and
execution code.

```
ibkr_desk/
  core/            depends on nothing else in the package
    config.py        IBKRConfig, PostgresConfig, FutureSpec, ClientRole
    ib/connection.py connect_async / connect_sync / IBConnectionManager
    ib/contracts.py  stock / index / future factories, qualify
    ib/history.py    HistoryClient (paced reqHistoricalData), bars_to_frame
    ib/execution.py  positions, daily_pnl, marketable_limit
    providers.py     ProviderStatus + registry (connection status, provider-agnostic)
    pubsub.py        Broker: topic pub/sub + synchronous taps
    models.py, time_utils.py
  storage/         sqlite.py | postgres.py | csv_archive.py
  marketdata/      futures.py | equities.py | public_rates.py | backfill.py | jobs.py
  live/            market_data.py | portfolio_feed.py | quote_book.py
  strategies/rates_rv/   config | signals | data | backtest | risk | trader
  dashboard/       app | server | ws_server | theme | data_access | pages/ | callbacks/ | components/
  universe.py, swaps/, settings.py (composition root)
```
Dependency direction: `core` <- `storage`, `marketdata`, `live`, `strategies` <- `dashboard`.
`settings.py` assembles every sub-config (each lives next to the code that uses it).

## One place to connect

`core/ib/connection.py` is the only code that opens an IBKR socket. Every client goes through
`connect_async(ib, cfg, role)`, which guarantees:

- **Paper guard**: after connecting, if any managed account is not `DU…` and `ibkr.allow_live` is
  false, it disconnects and raises `LiveAccountRefused` (not retried: it is a config problem).
- **Distinct client id per role**: `ClientRole` (DASHBOARD 0, TRADER 1, ARCHIVE 2, RESEARCH 3, ADHOC 4)
  is added to `ibkr.client_id`, so simultaneous clients on one Gateway can never collide.
- **Least privilege**: every role connects read-only except `TRADER`.
- The configured market-data type.

Two entry points share that code path: `connect_sync()` for short-lived scripts and jobs (archive,
trader), and `IBConnectionManager` for long-running apps (dashboard).

### IBConnectionManager (long-running apps)
Owns the single `ib_async.IB()` on its own asyncio loop in a dedicated thread (an IBKR connection is
not safe to share across threads/loops). Everything else schedules coroutines onto that loop via
`run_coroutine()`. It:
- retries forever and reconnects after a drop;
- runs **on-connect hooks** after every successful (re)connect. Subscriptions and account streams
  die with the socket, so `MarketDataService`, `PortfolioFeed` and the backfill register hooks
  rather than firing once at startup;
- reports its state through `status()` (see Providers below);
- `start(required=False)` lets the dashboard come up even when Gateway is down.

## Providers and connection status

`core/providers.py` defines `ProviderStatus` (state, endpoint, time in state, last-data age, extras,
`kind`) and a `ProviderRegistry`. A provider is any object with a `name` and `status()`. Registered
today: `IBConnectionManager` (IBKR) and `PostgresProbe`. The header chips and the STATUS tab render
whatever is registered, so wiring in another market-data source is one `registry.register(...)`.
`registry.touch(name)` records that data arrived, which lets the UI distinguish "connected" from
"connected but silent".

## Historical data

All `reqHistoricalData` calls go through `HistoryClient`, which spaces requests (default 1.5 s;
`ibkr.historical_request_interval_s`) with a lock, so concurrent callers queue instead of tripping
IBKR's pacing limits. The dashboard backfill, the futures archive and the equities archive all use it.

## Storage

- **SQLite** (`data/market_data.db`): the dashboard's tick/bar cache. Frequent small writes + range reads.
- **Postgres** (`marketdata`): long-term archive, one schema per asset class.

| Schema | Tables |
|---|---|
| `futures` | `contract`, `daily_bar` (OHLCV per contract per day) |
| `equities` | `daily_bar` (OHLCV + adjusted close) |
| `rates` | `treasury_par_yield`, `overnight_rate` (SOFR, EFFR), `fred_series` (breakevens, TIPS real yields, credit OAS, VIX) |
| `ops` | `snapshot_run` (one row per snapshot step: ok/fail + detail) |

- **CSV archive** (`data/archive/`): append-only local backup. Rows are never deleted; on overlapping
  dates the newer fetch wins. Postgres is loaded from it by idempotent upsert.

## Daily snapshot (`marketdata/jobs.py`)

1. IBKR: refresh futures and equities CSVs (one connection, `ClientRole.ARCHIVE`).
2. CSVs -> Postgres.
3. Public rates (US Treasury par curve, NY Fed SOFR/EFFR) -> Postgres.
4. FRED series (`marketdata/fred.py`: breakevens, TIPS real yields, IG/HY credit OAS, VIX) -> Postgres.
   Uses FRED's anonymous CSV download, no API key; add a row to `fred.SERIES` to archive another
   series. Two of the credit-OAS series only return their trailing ~3 years via this endpoint
   (a FRED licensing restriction on ICE-sourced data, not a bug) -- see the comment in that file.

Each step is isolated and recorded in `ops.snapshot_run`. A step that returns less than requested
(a product with no contracts, a symbol IBKR rejects) is recorded as a **failure**, not a silent
success. The process exits non-zero if anything failed. Scheduled by Windows Task Scheduler.

## Rates RV strategy (`strategies/rates_rv/`)

DV01-neutral butterflies on Treasury futures (2s5s10s, 5s10s30s). `signals.py` builds the fly
level, z-score, position state machine and vol-targeted sizing; `backtest.py` adds an execution lag,
commission + slippage, and a walk-forward parameter search; `risk.py` enforces per-leg/DV01 caps, a
daily-loss flatten and a `KILL` file; `trader.py` refreshes the archive, computes targets, diffs
against positions and sends marketable-limit orders (only with `--send`, as `ClientRole.TRADER`).
Price changes are always taken within the contract held the previous day, so roll gaps never enter P&L.
The port from the original standalone bot is locked by a regression test on the synthetic backtest.

## Dashboard

One process, three pieces of concurrency: the IBKR I/O thread, a websocket bridge thread
(`ws_server.py`, port 8051) and the Dash/Flask server on the main thread (port 8500).

```
IB Gateway <--> IBKR I/O thread --publish--> Broker --+--> SQLite (ticks, bars)
                                                       +--> QuoteBook (tap)      --> LIVE tab (500 ms refresh)
                                                       +--> WebSocket bridge     --> CHARTS / PORTFOLIO tabs (Patch())
Postgres <-- data_access.py (read-only) ------------------------------------------> DATA tab
provider registry ----------------------------------------------------------------> header chips + STATUS tab
```

| Tab | Source | Mechanism |
|---|---|---|
| LIVE | `QuoteBook` (fed by a broker tap) | 500 ms interval; the blotter reads server-side state instead of pushing every tick through the browser, which stays responsive with dozens of instruments and cannot back-pressure ingestion |
| CHARTS | SQLite bars + websocket ticks | `dash.Patch()` appends a point so zoom/pan/crosshair survive live updates; switching instrument is a deliberate full redraw |
| PORTFOLIO | `PortfolioFeed` via websocket | positions + account cards |
| DATA | Postgres | freshness per dataset (business-day lag -> OK/WARN/STALE), `ops.snapshot_run` log, explorer (plot **and** table) driven by a dataset registry in `data_access.py` |
| STATUS | provider registry | one card per provider; same data as the header chips |

The dashboard is **read-only**: it never places orders. The look (black, amber labels, green/red,
monospace) is defined once in `dashboard/theme.py` (plotly template + DataTable styles) and
`assets/style.css`.

## Config & credentials

`config/config.yaml` (gitignored, copy of `config.example.yaml`) — typed by pydantic in `settings.py`.
Secrets (Postgres password) live in `.env`. IBKR has no API key: you authenticate by logging into
Gateway. `ibkr.mode` picks paper/live port; `ibkr.allow_live` must be set deliberately to talk to a
non-paper account.

## Known limitations

- **Swap/IRS data**: IBKR's public TWS API has no documented contract spec for OTC swap quotes.
  `swaps/adapter.py` provides `StubSwapAdapter` as the only implementation and is the single slot-in
  point for a real feed.
- **Expired futures**: IBKR serves roughly one year of expired contracts, so deep futures history
  must come from elsewhere; the archive accumulates from now on.
- **DV01s** in `config` are approximations.
- Some instruments in `config/instruments/*.yaml` do not resolve on IBKR (check logs for
  "No security definition"); they show as empty rows on the LIVE tab.
