"""Live bid/ask/last header strip. Rendered from a plain cache dict (instrument_id -> {label,
bid, ask, last}) so the same render function drives both the initial page layout and the
websocket-driven callback updates.
"""

from __future__ import annotations

from dash import html


def _fmt(value) -> str:
    return f"{value:.4f}" if isinstance(value, (int, float)) else "--"


def build_quote_ticker_children(cache: dict) -> list:
    cards = []
    for instrument_id, info in cache.items():
        cards.append(
            html.Div(
                [
                    html.Div(info.get("label", instrument_id), className="quote-label"),
                    html.Div(
                        [
                            html.Span(_fmt(info.get("bid")), className="quote-bid"),
                            html.Span(" / ", className="quote-sep"),
                            html.Span(_fmt(info.get("ask")), className="quote-ask"),
                            html.Span("  last ", className="quote-sep"),
                            html.Span(_fmt(info.get("last")), className="quote-last"),
                        ],
                        className="quote-values",
                    ),
                ],
                className="quote-card",
            )
        )
    return cards


def build_quote_ticker(cache: dict) -> html.Div:
    return html.Div(build_quote_ticker_children(cache), className="quote-ticker")
