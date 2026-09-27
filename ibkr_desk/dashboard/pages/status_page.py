"""STATUS tab + header chips: connection state of every registered provider.

Provider-agnostic: anything registered in `core.providers.registry` (IBKR, Postgres, a future
Bloomberg/Refinitiv/websocket feed, ...) is rendered with no changes here.
"""

from __future__ import annotations

import time
from datetime import datetime

from dash import dcc, html

from ibkr_desk.core.providers import ConnState, ProviderStatus

NO_DATA_WARN_S = 120  # connected, but no tick for this long => flag (markets may simply be closed)


def _dur(seconds: float | None) -> str:
    if seconds is None:
        return "--"
    s = int(seconds)
    if s < 60:
        return f"{s}s"
    if s < 3600:
        return f"{s // 60}m {s % 60:02d}s"
    return f"{s // 3600}h {(s % 3600) // 60:02d}m"


def _is_bad(s: ProviderStatus) -> bool:
    return s.state in (ConnState.DISCONNECTED, ConnState.ERROR)


def chips(statuses: list[ProviderStatus]) -> list:
    out = []
    for s in statuses:
        label = s.state.value
        if s.state is ConnState.CONNECTED and s.data_age_s is not None and s.data_age_s > NO_DATA_WARN_S:
            label = f"connected · no data {_dur(s.data_age_s)}"
        out.append(
            html.Div(
                [html.Span(className=f"dot {s.state.value}"), html.Span(s.name), html.Span(label, className="chip-state")],
                className="chip bad" if _is_bad(s) else "chip",
                title=s.detail,
            )
        )
    return out


def cards(statuses: list[ProviderStatus]) -> list:
    out = []
    now = time.time()
    for s in statuses:
        rows = [
            ("State", s.state.value.upper()),
            ("Endpoint", s.detail or "--"),
            ("In this state for", _dur(now - s.since) if s.since else "--"),
            ("Last data", f"{_dur(s.data_age_s)} ago" if s.data_age_s is not None else "n/a"),
            *[(k, v) for k, v in s.extra.items()],
        ]
        out.append(
            html.Div(
                [
                    html.Div([html.Span(className=f"dot {s.state.value}"), html.Span(s.name)], className="card-head"),
                    *[html.Div([html.Span(k), html.Span(v)], className="card-row") for k, v in rows],
                ],
                className="card bad" if _is_bad(s) else "card",
            )
        )
    return out


def build_status_layout() -> html.Div:
    return html.Div(
        [
            dcc.Interval(id="status-page-interval", interval=2000),
            html.H2("Connections"),
            html.Div(id="status-cards", className="cards"),
            html.Div(
                "Providers are read from ibkr_desk.core.providers.registry. To monitor another market-data "
                "source, register any object with a `name` and a `status()` method -- it appears here and in "
                "the header automatically.",
                className="muted", style={"marginTop": "14px"},
            ),
        ],
        className="page",
    )


def clock() -> str:
    return datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")
