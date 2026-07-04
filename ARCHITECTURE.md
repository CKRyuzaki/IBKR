# IBKR G10 RV Desk Dashboard — Architecture

## What this is

A live-ticking market data and portfolio dashboard for a G10 rates/equity relative-value desk,
built on Interactive Brokers. It connects to IB Gateway/TWS (**paper trading by default**),
streams live quotes for the most liquid equity index + single names per G10 currency (USD, EUR,
GBP, JPY, CHF, CAD, AUD, NZD, SEK, NOK), shows Bloomberg-GP-style price charts (pan/zoom/
crosshair, adjustable lookback), and monitors the account's live positions/P&L. Swap/IRS curves
(e.g. EURIBOR, ESTR, basis swaps) are scaffolded as a clearly-labeled **placeholder** — see
[Known limitation](#known-limitation-swapirs-data) below.

It deliberately runs as **one Python process** (no microservices, no message broker, no
Docker/k8s) — this is a single-user local tool, so that complexity would add operational weight
without benefit.

## Process layout: three pieces of concurrency, one process

```
                         ┌─────────────────────────────────────────┐
                         │              Python process              │
                         │                                           │
  IB Gateway/TWS  <────► │  IBKR I/O thread                          │
  (paper, port 4002)     │  - owns the single ib_async.IB() conn.    │
                         │  - own asyncio event loop                 │
                         │  - reqMktData / reqHistoricalData /       │
                         │    reqAccountUpdates                      │
                         │        │                                  │
                         │        │ publish()                        │
                         │        ▼                                  │
                         │  Broker (in-memory pub/sub)                │
                         │  topic -> subscriber queues                │
                         │        │              │                   │
                         │        │              ▼                   │
                         │        │      SQLite (data/market_data.db)│
                         │        │      (ticks + backfilled bars)   │
                         │        ▼                                  │
                         │  WebSocket bridge thread                  │
                         │  (its own asyncio loop, port 8501)        │
                         │        │                                  │
                         │        ▼ ws frames                        │
                         │  Dash/Flask server thread (main thread)   │
                         │  - serves the dashboard, port 8500        │
                         │  - dash-extensions WebSocket component     │
                         │    receives frames -> Dash callback fires  │
                         │  - callback returns dash.Patch() -> only   │
                         │    the changed trace/value updates,        │
                         │    zoom/pan/crosshair state is preserved   │
                         └─────────────────────────────────────────┘
                                        ▲
                                        │ HTTP/WS
                                  Your browser
                          http://127.0.0.1:8500
```

Why three threads and not more/fewer:
- **Exactly one IBKR connection** — the API isn't safe to share across threads/loops, so all
  IBKR I/O (market data, historical backfill, account/portfolio updates) happens on one
  dedicated thread/event loop (`ibkr_dashboard/connection/ib_client.py`).
- **A separate websocket bridge thread** (`ibkr_dashboard/dash_app/ws_server.py`) — decouples
  "how a tick reaches the browser" from "how a tick reaches IBKR," so the Dash server and the
  IBKR connection never block on each other.
- **The Dash/Flask server on the main thread** — this is what you interact with in the browser.

## Why not Streamlit / why Dash + Patch() + WebSocket

Streamlit reruns the entire script top-to-bottom on every update, which doesn't scale to
sub-second ticking data. Instead:
- `dash-extensions`' `WebSocket` component pushes each new tick from the server the moment it
  arrives (event-driven), instead of the browser polling on an interval.
- The Dash callback that receives a tick returns a `dash.Patch()` object, which patches only the
  one changed trace/value in the existing figure — never rebuilds the whole chart — which is
  what keeps your zoom/pan/crosshair state intact while data streams in.
- `dcc.Interval` is not used for ticks at all; it's reserved for low-frequency housekeeping
  (not currently wired to anything, but the pattern is there if needed later, e.g. a
  "connection alive" heartbeat).
- Switching the **instrument** or the chart's lookback range is a deliberate full redraw
  (queries SQLite directly) — that's correct there because *you* changed the view, so a fresh
  figure with `uirevision` reset is appropriate, unlike a background tick arriving passively.

## Component map

| File | Responsibility |
|---|---|
| `ibkr_dashboard/settings.py` | Loads `config/config.yaml` (or falls back to `config.example.yaml`) + `.env`, typed via pydantic. Single `mode: paper\|live` toggle picks the connection port. |
| `ibkr_dashboard/connection/ib_client.py` | `IBConnectionManager` — the one asyncio loop/thread owning `ib_async.IB()`, with connect-retry and auto-reconnect on disconnect. |
| `ibkr_dashboard/connection/contracts.py` | Loads a currency's `config/instruments/<ccy>.yaml`, builds real `ib_async` `Contract` objects (`Stock`, `Index`, `Future`) for equities/indices/futures. Swaps never become a `Contract` here. |
| `ibkr_dashboard/connection/market_data.py` | `MarketDataService` — qualifies contracts, calls `reqMktData`, listens to `ib.pendingTickersEvent`, throttles + normalizes ticks, publishes to the `Broker` and writes to SQLite. |
| `ibkr_dashboard/connection/portfolio_feed.py` | `PortfolioFeed` — wraps `reqAccountUpdates`, republishes `Position`/`AccountValue` snapshots to the `Broker` for the Portfolio tab. |
| `ibkr_dashboard/swaps/models.py` + `adapter.py` | `RatesSwapInstrument` data shape + `SwapMarketDataAdapter` protocol. Only implementation today is `StubSwapAdapter`, which always returns no data. This is the single slot-in point for real swap data later. |
| `ibkr_dashboard/data/models.py` | Shared dataclasses: `Tick`, `Bar`, `Position`, `AccountValue`, `Instrument`. |
| `ibkr_dashboard/data/pubsub.py` | `Broker` — thread-safe in-memory pub/sub. Supports both plain thread `queue.Queue` subscribers and asyncio-native subscribers (used by the websocket bridge). Drops the oldest message on a full queue rather than ever blocking the IBKR I/O thread. |
| `ibkr_dashboard/data/storage.py` | SQLite schema (`ticks`, `bars`, `instruments`) + read/write API. Chosen over DuckDB because this workload is frequent small writes + simple range-scan reads, which is SQLite's strength. |
| `ibkr_dashboard/data/backfill.py` | At startup, calls `reqHistoricalData` per instrument to pre-populate `bars` so GP-style longer lookbacks have data immediately. |
| `ibkr_dashboard/dash_app/ws_server.py` | `WebSocketServer` — its own thread/loop, bridges `Broker` topics to browser websocket connections (one topic set per currency tab, one for the portfolio tab). |
| `ibkr_dashboard/dash_app/server.py` | `build_app()` — Dash app factory: tab layout (10 currencies + Portfolio) + registers callbacks. |
| `ibkr_dashboard/dash_app/pages/currency_page.py` | Builds one GP-style currency page: quote header, instrument dropdown, price chart, swap panel. Reused for all 10 currencies via pattern-matching (`MATCH`) component ids. |
| `ibkr_dashboard/dash_app/pages/portfolio_page.py` | Positions table + account summary cards. |
| `ibkr_dashboard/dash_app/components/*.py` | Pure render functions for the price chart, quote ticker, swap panel, positions table — reused by both the initial page layout and the live-update callbacks. |
| `ibkr_dashboard/dash_app/callbacks/chart_callbacks.py` | Websocket message → `Patch()` chart/quote update; dropdown change → full SQLite requery + fresh figure. |
| `ibkr_dashboard/dash_app/callbacks/portfolio_callbacks.py` | Websocket message → positions table rows + account summary cards. |
| `ibkr_dashboard/app.py` | Entrypoint (`uv run dashboard` / `python -m ibkr_dashboard.app`) — wires all of the above together and starts everything. |

## End-to-end data flow (one tick)

1. IB Gateway sends a bid/ask/last update over the socket → `ib_async` fires
   `ib.pendingTickersEvent` on the IBKR I/O thread.
2. `MarketDataService._on_pending_tickers` (`connection/market_data.py`) normalizes it into a
   `Tick`, throttles per-instrument-per-field (`dashboard.update_throttle_ms`, default 250ms),
   writes it to SQLite, and calls `Broker.publish("tick.<instrument_id>", tick)`.
3. `Broker.publish` (`data/pubsub.py`) hands the tick to any subscriber of that topic — both
   plain-thread subscribers and, via `loop.call_soon_threadsafe`, any asyncio subscribers.
4. The `WebSocketServer` (`dash_app/ws_server.py`) holds one asyncio subscription per open
   browser connection for the topics relevant to that currency tab, and forwards the tick as a
   JSON websocket frame.
5. The browser's `dash-extensions` `WebSocket` component receives the frame, which fires the
   Dash callback in `chart_callbacks.py`.
6. That callback updates the quote-cache `dcc.Store`, rebuilds the small quote-ticker header,
   and — only if the tick's instrument is the one currently selected in the dropdown — returns
   a `Patch()` that appends one point to the chart trace.

## Config & credentials

- `config/config.example.yaml` is committed; `config/config.yaml` is your real local copy
  (gitignored). Single `ibkr.mode: paper|live` toggle picks `paper_port` (4002) vs `live_port`
  (4001).
- IBKR's TWS API has **no API key/secret** — you authenticate by logging into TWS/IB Gateway
  itself. `.env` is only for optional cosmetic overrides (e.g. an account label).
- `config/instruments/<ccy>.yaml` — one file per G10 currency, editable without touching code.
  Marks each row as real (equities/index/futures, subscribed live) or a swap stub.

## Known limitation: swap/IRS data

IBKR's public TWS API docs don't describe a contract spec for OTC interest-rate-swap quotes via
`reqMktData` — likely an institutional-only entitlement, possibly requiring FIX CTCI rather than
the standard socket API this project uses. `ibkr_dashboard/swaps/adapter.py` documents this and
provides `StubSwapAdapter` as the only implementation. Once the real IBKR contract spec is
confirmed, only that one adapter needs to be replaced (single line in `app.py`) — nothing else
in the pipeline changes.

## Build phases (for reference)

The project was built in this order, each independently verifiable:

1. **Connection** — `settings.py`, `ib_client.py`, `scripts/smoke_test_connection.py`.
2. **Storage** — `data/models.py`, `storage.py`, `backfill.py`.
3. **Dash skeleton** — one currency (USD) wired end-to-end: tick subscription → pubsub →
   websocket → chart/quote update.
4. **Portfolio tab** — `portfolio_feed.py`, positions table, account summary.
5. **Remaining 9 G10 currencies** — instrument YAMLs populated, same page code reused.
6. **Swap stub wiring** — placeholder panel added to all 10 currency pages.
