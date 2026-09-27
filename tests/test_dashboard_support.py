import datetime as dt

from ibkr_desk.core.models import Tick
from ibkr_desk.core.providers import ConnState, ProviderRegistry, ProviderStatus
from ibkr_desk.core.pubsub import Broker
from ibkr_desk.dashboard import data_access as da
from ibkr_desk.live.quote_book import QuoteBook


def _tick(iid, field, value):
    return Tick(instrument_id=iid, field=field, value=value, ts=dt.datetime.now(dt.timezone.utc))


def test_tap_sees_publishes_and_cannot_break_publisher():
    b = Broker()
    seen = []
    b.tap("tick.", lambda topic, p: seen.append(topic))
    b.tap("tick.", lambda topic, p: 1 / 0)  # a buggy tap must never affect ingestion
    b.publish("tick.X", {"v": 1})
    b.publish("other.X", {"v": 1})
    assert seen == ["tick.X"]


def test_quote_book_lists_instruments_before_first_tick_and_tracks_direction():
    b = Broker()
    book = QuoteBook({"USD.EQ.A": ("A Corp", "USD")})
    book.attach(b)
    row = book.snapshot()[0]
    assert (row["name"], row["last"], row["age_s"]) == ("A Corp", None, None)
    for f, v in (("bid", 9.9), ("ask", 10.1), ("last", 10.0), ("last", 10.5), ("last", 10.2)):
        b.publish("tick.USD.EQ.A", _tick("USD.EQ.A", f, v))
    row = book.snapshot()[0]
    assert (row["bid"], row["ask"], row["last"], row["dir"]) == (9.9, 10.1, 10.2, "▼")
    assert row["spread"] == 10.1 - 9.9 and row["age_s"] < 5
    # history holds a price point per tick once a price exists: the lone bid has none, ask gives a mid, then 3 lasts
    assert len(book.history("USD.EQ.A")) == 4


def test_registry_reports_any_provider_and_survives_a_broken_one():
    class Good:
        name = "Feed1"

        def status(self):
            return ProviderStatus("Feed1", ConnState.CONNECTED, "ok")

    class Broken:
        name = "Feed2"

        def status(self):
            raise RuntimeError("boom")

    reg = ProviderRegistry()
    reg.register(Good())
    reg.register(Broken())
    reg.touch("Feed1")
    good, broken = reg.statuses()
    assert good.state is ConnState.CONNECTED and good.data_age_s is not None and good.data_age_s < 5
    assert broken.state is ConnState.ERROR and "boom" in broken.detail


def test_freshness_status_thresholds():
    assert da._status(1, 2) == "OK"
    assert da._status(3, 2) == "WARN"
    assert da._status(5, 2) == "STALE"


def test_lag_counts_business_days_only():
    fri, mon = dt.date(2026, 9, 25), dt.date(2026, 9, 28)
    assert da.lag_business_days(fri, mon) == 1  # the weekend does not count as staleness
    assert da.lag_business_days(dt.date(2026, 9, 22), mon) == 4
