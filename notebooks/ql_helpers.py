"""Shared QuantLib helpers for the curve / swap / bond-future notebooks.

All market data here is synthetic (an illustrative USD market as of EVAL_DATE) so the
notebooks run offline. Swap the quote dicts for live IBKR / LSEG data when needed.
"""
from __future__ import annotations

import QuantLib as ql

EVAL_DATE = ql.Date(25, 9, 2026)

# Synthetic SOFR OIS par rates (decimal). Tenor -> rate.
SOFR_OIS_QUOTES: dict[str, float] = {
    "1W": 0.0405, "1M": 0.0403, "3M": 0.0398, "6M": 0.0388, "1Y": 0.0372,
    "2Y": 0.0361, "3Y": 0.0362, "4Y": 0.0367, "5Y": 0.0373, "7Y": 0.0385,
    "10Y": 0.0399, "15Y": 0.0412, "20Y": 0.0416, "30Y": 0.0410,
}

INTERPOLATORS = {
    "LogLinearDiscount": ql.PiecewiseLogLinearDiscount,
    "LinearZero": ql.PiecewiseLinearZero,
    "LogCubicDiscount": ql.PiecewiseLogCubicDiscount,
    "FlatForward": ql.PiecewiseFlatForward,
}


def set_eval_date(date: ql.Date = EVAL_DATE) -> ql.Date:
    ql.Settings.instance().evaluationDate = date
    return date


class SofrCurve:
    """Bootstrapped SOFR OIS curve whose input quotes are live `SimpleQuote`s.

    Bumping a quote (`bump`) automatically re-bootstraps the curve, so any instrument
    priced off `handle` re-prices -> bump-and-reprice risk without rebuilding anything.
    """

    def __init__(self, quotes: dict[str, float] | None = None, interpolator: str = "LogLinearDiscount"):
        set_eval_date()
        self.quote_levels = dict(quotes or SOFR_OIS_QUOTES)
        self.quotes = {t: ql.SimpleQuote(r) for t, r in self.quote_levels.items()}
        self._handle = ql.RelinkableYieldTermStructureHandle()
        self.index = ql.Sofr(self._handle)
        self.helpers = []
        for tenor, q in self.quotes.items():
            period = ql.Period(tenor)
            self.helpers.append(
                ql.OISRateHelper(2, period, ql.QuoteHandle(q), self.index, ql.YieldTermStructureHandle(), False, 2)
            )
        self.curve = INTERPOLATORS[interpolator](0, ql.UnitedStates(ql.UnitedStates.SOFR),
                                                 self.helpers, ql.Actual365Fixed())
        self.curve.enableExtrapolation()
        self._handle.linkTo(self.curve)
        self.curve.discount(1.0)   # force the lazy bootstrap so helpers are attached to the curve

    @property
    def handle(self) -> ql.YieldTermStructureHandle:
        return self._handle

    def bump(self, tenor: str | None, bp: float = 1.0) -> None:
        """Bump one quote (or all if tenor is None) by `bp` basis points."""
        for t, q in self.quotes.items():
            if tenor is None or t == tenor:
                q.setValue(q.value() + bp * 1e-4)

    def reset(self) -> None:
        for t, q in self.quotes.items():
            q.setValue(self.quote_levels[t])


# Synthetic Treasury zero-rate pillars (continuous, decimal) used to discount deliverable bonds.
UST_ZERO_RATES: dict[str, float] = {
    "3M": 0.0395, "6M": 0.0385, "1Y": 0.0370, "2Y": 0.0372, "3Y": 0.0376, "5Y": 0.0387,
    "7Y": 0.0401, "10Y": 0.0420, "20Y": 0.0460, "30Y": 0.0450,
}


def ust_curve(bumps_bp: dict[str, float] | None = None, parallel_bp: float = 0.0) -> ql.YieldTermStructure:
    """Treasury zero curve from pillar zero rates, with optional key-rate / parallel bumps (bp).

    Rebuilt on every call (cheap), which keeps bump-and-reprice risk explicit and stateless.
    """
    set_eval_date()
    bumps_bp = bumps_bp or {}
    dates, rates = [], []
    for tenor, r in UST_ZERO_RATES.items():
        dates.append(EVAL_DATE + ql.Period(tenor))
        rates.append(r + (bumps_bp.get(tenor, 0.0) + parallel_bp) * 1e-4)
    dates.insert(0, EVAL_DATE)
    rates.insert(0, rates[0])
    curve = ql.ZeroCurve(dates, rates, ql.Actual365Fixed(), ql.UnitedStates(ql.UnitedStates.GovernmentBond))
    curve.enableExtrapolation()
    return curve
