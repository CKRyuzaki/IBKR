"""Order/position helpers for strategies. Only a client connected with ClientRole.TRADER (not
read-only) can actually place orders; every other role is rejected by IBKR itself."""

from __future__ import annotations

import math
from dataclasses import dataclass

from ib_async import IB, Contract, LimitOrder


@dataclass(frozen=True)
class OrderResult:
    limit: float | None
    status: str
    filled: float = 0.0
    avg_fill: float = 0.0


def positions(ib: IB, symbols: set[str]) -> dict[int, tuple[Contract, int]]:
    """{conId: (contract, qty)} for non-zero futures positions in `symbols`."""
    out = {}
    for p in ib.positions():
        if p.contract.secType == "FUT" and p.contract.symbol in symbols and p.position:
            out[p.contract.conId] = (p.contract, int(p.position))
    return out


def daily_pnl(ib: IB, account: str) -> float | None:
    """Account daily P&L in base currency, or None if IBKR did not return it (caller must treat
    None as *unknown*, not as zero)."""
    try:
        ib.reqPnL(account)
        ib.sleep(2)
        v = ib.pnl()[0].dailyPnL
        return None if v is None or (isinstance(v, float) and math.isnan(v)) else float(v)
    except Exception:  # noqa: BLE001
        return None


def top_of_book(ib: IB, contract: Contract, wait_s: float = 8.0) -> tuple[float, float] | None:
    t = ib.reqMktData(contract, "", False, False)
    waited = 0.0
    while waited < wait_s and not (t.bid and t.ask and t.bid > 0 and t.ask > 0):
        ib.sleep(0.5)
        waited += 0.5
    bid, ask = t.bid, t.ask
    ib.cancelMktData(contract)
    if not (bid and ask and bid > 0 and ask > 0):
        return None
    return bid, ask


def marketable_limit(ib: IB, contract: Contract, delta: int, tick: float, timeout_s: int) -> OrderResult:
    """Buy at the ask / sell at the bid as a DAY limit order; cancel if not done after timeout_s."""
    q = top_of_book(ib, contract)
    if q is None:
        return OrderResult(None, "no_quote")
    bid, ask = q
    px = round(round((ask if delta > 0 else bid) / tick) * tick, 6)
    order = LimitOrder("BUY" if delta > 0 else "SELL", abs(delta), px, tif="DAY")
    trade = ib.placeOrder(contract, order)
    waited = 0
    while not trade.isDone() and waited < timeout_s:
        ib.sleep(1)
        waited += 1
    if not trade.isDone():
        ib.cancelOrder(order)
        ib.sleep(1)
    st = trade.orderStatus
    return OrderResult(px, st.status, st.filled, st.avgFillPrice)
