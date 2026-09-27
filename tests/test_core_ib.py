import pytest

from ibkr_desk.core.config import ClientRole, IBKRConfig
from ibkr_desk.core.ib import contracts as ibc
from ibkr_desk.core.ib.connection import LiveAccountRefused, assert_account_allowed


def test_client_ids_are_unique_per_role():
    cfg = IBKRConfig(client_id=11)
    ids = [cfg.client_id_for(r) for r in ClientRole]
    assert len(ids) == len(set(ids))
    assert cfg.client_id_for(ClientRole.DASHBOARD) == 11  # dashboard keeps its historical id


def test_only_trader_role_is_not_readonly():
    cfg = IBKRConfig()
    assert cfg.readonly_for(ClientRole.DASHBOARD)
    assert cfg.readonly_for(ClientRole.ARCHIVE)
    assert not cfg.readonly_for(ClientRole.TRADER)


def test_paper_accounts_allowed():
    assert_account_allowed(["DU1234567"], IBKRConfig())


@pytest.mark.parametrize("accounts", [["U1234567"], ["DU1234567", "U7654321"], []])
def test_live_or_unknown_accounts_refused_by_default(accounts):
    with pytest.raises(LiveAccountRefused):
        assert_account_allowed(accounts, IBKRConfig())


def test_live_account_allowed_only_when_explicit():
    assert_account_allowed(["U1234567"], IBKRConfig(allow_live=True))


def test_port_follows_mode():
    assert IBKRConfig(mode="paper").port == 4002
    assert IBKRConfig(mode="live").port == 4001


def test_contract_factories():
    f = ibc.future("ZN", "CBOT", month="202612", include_expired=True)
    assert (f.symbol, f.exchange, f.lastTradeDateOrContractMonth, f.includeExpired) == ("ZN", "CBOT", "202612", True)
    assert ibc.future("ZN", "CBOT").lastTradeDateOrContractMonth == ""  # front month resolved by IBKR
    assert ibc.stock("TLT").exchange == "SMART"
    assert ibc.month_code(2026, 3) == "202603"


def test_stock_primary_exchange_is_empty_string_not_none():
    # None gets serialised as the literal "None" and IBKR rejects the exchange ("No security definition")
    assert ibc.stock("SPY").primaryExchange == ""
    assert ibc.stock("ATCO-A", primary_exchange="SFB").primaryExchange == "SFB"
