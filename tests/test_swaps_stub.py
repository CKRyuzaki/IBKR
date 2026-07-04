from ibkr_dashboard.swaps.adapter import StubSwapAdapter
from ibkr_dashboard.swaps.models import RatesSwapInstrument


def test_stub_adapter_always_returns_no_data():
    adapter = StubSwapAdapter()
    instrument = RatesSwapInstrument(
        currency="EUR", index_basis="ESTR", tenor="5Y", leg_description="Fixed vs ESTR (OIS)"
    )

    adapter.subscribe(instrument)  # should not raise
    result = adapter.get_quote(instrument)

    assert result.bid is None
    assert result.ask is None
    assert result.mid is None
    assert result.is_stub is True


def test_instrument_id_format():
    instrument = RatesSwapInstrument(
        currency="EUR", index_basis="ESTR", tenor="5Y", leg_description="Fixed vs ESTR (OIS)"
    )
    assert instrument.instrument_id == "EUR.SWAP.ESTR.5Y"
