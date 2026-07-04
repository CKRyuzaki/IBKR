"""Wraps ib_async's live account/portfolio update stream and republishes normalized
Position / AccountValue snapshots onto the pub/sub broker, for the Portfolio dashboard tab.
"""

from __future__ import annotations

import logging

from ib_async import AccountValue as IBAccountValue
from ib_async import PortfolioItem

from ibkr_dashboard.connection.ib_client import IBConnectionManager
from ibkr_dashboard.data.models import AccountValue, Position
from ibkr_dashboard.data.pubsub import Broker

logger = logging.getLogger(__name__)

POSITIONS_TOPIC = "portfolio.positions"
ACCOUNT_TOPIC = "portfolio.account"


class PortfolioFeed:
    def __init__(self, connection: IBConnectionManager, broker: Broker) -> None:
        self._connection = connection
        self._broker = broker
        connection.ib.updatePortfolioEvent += self._on_portfolio_update
        connection.ib.accountValueEvent += self._on_account_value

    def start(self, account_id: str = "") -> None:
        self._connection.run_coroutine(self._request_account_updates(account_id))

    async def _request_account_updates(self, account_id: str) -> None:
        ib = self._connection.ib
        if not account_id:
            accounts = ib.managedAccounts()
            account_id = accounts[0] if accounts else ""
        if not account_id:
            logger.warning("No IBKR account id available yet; portfolio feed not started")
            return
        ib.reqAccountUpdates(True, account_id)
        logger.info("Requested live account/portfolio updates for %s", account_id)

    def _on_portfolio_update(self, item: PortfolioItem) -> None:
        position = Position(
            account=item.account,
            instrument_id=f"{item.contract.currency}.EQ.{item.contract.symbol}",
            symbol=item.contract.symbol,
            position=item.position,
            avg_cost=item.averageCost,
            market_price=item.marketPrice,
            market_value=item.marketValue,
            unrealized_pnl=item.unrealizedPNL,
            realized_pnl=item.realizedPNL,
        )
        self._broker.publish(POSITIONS_TOPIC, position)

    def _on_account_value(self, value: IBAccountValue) -> None:
        account_value = AccountValue(
            account=value.account, tag=value.tag, value=value.value, currency=value.currency
        )
        self._broker.publish(ACCOUNT_TOPIC, account_value)
