# IBKR G10 RV Desk Dashboard

Live-ticking market data, portfolio monitoring, and Bloomberg-GP-style price charts for a G10
rates/equity relative-value desk, built on top of Interactive Brokers. **Paper trading account
by default.**

See [ARCHITECTURE.md](ARCHITECTURE.md) for the full component-by-component writeup and data
flow diagram. In short:

- **UI**: Dash (Plotly), pushed via a background WebSocket bridge + `dash.Patch()` partial
  updates -- not full-page reruns like Streamlit, not raw polling.
- **IBKR access**: [`ib_async`](https://github.com/ib-api-reloaded/ib_async), the maintained
  fork of `ib_insync`.
- **Storage**: local SQLite for tick/bar history (survives restarts, powers longer lookback
  charts).
- **Swaps/IRS**: currently a **stub only** -- see "Known limitation" below.

## 1. Install Python deps

Requires Python 3.12 and [uv](https://docs.astral.sh/uv/).

```powershell
uv sync
```

## 2. Install & configure IB Gateway (paper account)

We recommend **IB Gateway** over full TWS Desktop for this use case -- it's lighter weight and
better suited to a long-running background data connection.

1. Download and install IB Gateway from IBKR's website.
2. Log in with your **paper trading** credentials.
3. In IB Gateway: **Configure -> Settings -> API -> Settings**:
   - Confirm the socket port matches `config.yaml` (`4002` for paper by default)
   - "Read-Only API" can stay **checked** -- this dashboard only reads market data,
     positions, and account values; it never submits/modifies/cancels orders. Read-Only
     only blocks order entry, not data reads, so leaving it on is actually the safer default.
   - Add `127.0.0.1` to "Trusted IP Addresses" if that field is present and empty (some
     Gateway versions auto-trust localhost connections and won't show this requirement)
   - Note: IB Gateway (unlike full TWS Desktop) doesn't show an "Enable ActiveX and Socket
     Clients" checkbox -- the API is always on since that's Gateway's whole purpose.
4. Keep IB Gateway running while the dashboard is running.

## 3. Configure the app

```powershell
copy config\config.example.yaml config\config.yaml
```

Edit `config/config.yaml` for your setup (host/port/clientId/account id). `config.yaml` is
gitignored -- never commit real account details.

IBKR's TWS API has **no API key/secret** -- authentication happens when you log into TWS/IB
Gateway itself. `.env.example` (copy to `.env`) is only for optional cosmetic overrides.

## 4. Run

```powershell
uv run dashboard
```

Then open `http://127.0.0.1:8500`.

## Verifying each build phase

- **Connection**: `uv run python scripts/smoke_test_connection.py` -- connects to your
  paper Gateway and prints account summary.
- **Historical backfill**: `uv run python scripts/backfill_once.py USD` -- backfills bars
  for one currency's instrument universe.
- **Tests**: `uv run pytest`

## Known limitation: swap/IRS data is a stub

IBKR's public TWS API documentation does not describe a contract spec (secType/fields) for OTC
interest-rate-swap quotes via `reqMktData`. This is very likely an institutional-only
entitlement and may require FIX CTCI rather than the standard TWS/IB Gateway socket API this
project uses. The swap curve panel on every currency tab is a clearly-labeled placeholder
(`ibkr_dashboard/swaps/adapter.py`) until the real IBKR contract spec is confirmed and wired in.
Equities, indices, and futures (used as short-rate proxies) are real, live data via `ib_async`.

## Instrument universe

Per-currency instrument lists live in `config/instruments/<ccy>.yaml` (G10: USD, EUR, GBP, JPY,
CHF, CAD, AUD, NZD, SEK, NOK). Symbols/exchanges are best-effort defaults -- some (especially
JPY/NZD/SEK/NOK names) may need correcting once you can run `ib.qualifyContractsAsync()`
against a live connection. Edit these files freely; no code changes needed to adjust the
universe.
