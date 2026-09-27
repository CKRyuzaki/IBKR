"""Contract factories and qualification, shared by the dashboard universe, archive jobs and strategies."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from ib_async import IB, Contract, Future, Index, Stock

logger = logging.getLogger(__name__)


def stock(symbol: str, exchange: str = "SMART", currency: str = "USD",
          primary_exchange: str | None = None) -> Stock:
    # ib_async wants '' (not None) for 'no primary exchange'; None is sent as the string "None" and rejected
    return Stock(symbol, exchange, currency, primaryExchange=primary_exchange or "")


def index(symbol: str, exchange: str, currency: str = "USD") -> Index:
    return Index(symbol, exchange, currency)


def future(symbol: str, exchange: str, currency: str = "USD", month: str | None = None,
           include_expired: bool = False) -> Future:
    """`month` is YYYYMM. With no month, qualification resolves the nearest expiry (front month).
    `include_expired` is needed to qualify contracts past their last trade date (history)."""
    kwargs = {"lastTradeDateOrContractMonth": month} if month else {}
    return Future(symbol, exchange=exchange, currency=currency, includeExpired=include_expired, **kwargs)


def month_code(year: int, month: int) -> str:
    return f"{year}{month:02d}"


async def _qualify_front_month(ib: IB, contract: Future) -> Contract | None:
    """A bare Future symbol (no explicit month) matches every listed expiry, and
    `qualifyContractsAsync` refuses to pick one when several match -- it just logs "Ambiguous
    contract" and returns nothing. Ask for the full expiry list instead and take the nearest
    one that hasn't already expired."""
    try:
        details = await ib.reqContractDetailsAsync(contract)
    except Exception as exc:  # noqa: BLE001 -- callers skip unknown contracts rather than crash
        logger.warning("Could not fetch contract details for %s: %s", contract, exc)
        return None
    if not details:
        logger.warning("No contract details found for %s", contract)
        return None
    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    candidates = sorted(details, key=lambda d: d.contract.lastTradeDateOrContractMonth)
    for d in candidates:
        if d.contract.lastTradeDateOrContractMonth[:8] >= today:
            return d.contract
    return candidates[-1].contract  # every expiry is in the past -- take the latest anyway


async def qualify_async(ib: IB, contract: Contract) -> Contract | None:
    """First qualified contract, or None (logged) if IBKR does not know it."""
    if isinstance(contract, Future) and not contract.lastTradeDateOrContractMonth:
        return await _qualify_front_month(ib, contract)
    try:
        qualified = await ib.qualifyContractsAsync(contract)
    except Exception as exc:  # noqa: BLE001 -- callers skip unknown contracts rather than crash
        logger.warning("Could not qualify %s: %s", contract, exc)
        return None
    return qualified[0] if qualified else None


def qualify(ib: IB, contract: Contract) -> Contract | None:
    return ib.run(qualify_async(ib, contract))
