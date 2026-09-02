"""Per-minute bid/ask history — the record that settles "the price was wrong".

Until this existed there was no way to answer that question: bid/ask are not
in any candle feed (Kite historical is LTP only), so once a minute passed it
was gone. Neither the operator nor the admin could prove anything.

Forward-only by nature. What it must get right is the aggregation itself — a
wrong high/low here is worse than no history, because it would be BELIEVED.
"""

from __future__ import annotations

import pytest

from app.services import tick_aggregator as agg

MIN_MS = 60_000


@pytest.fixture(autouse=True)
def _clean():
    agg._buckets.clear()
    yield
    agg._buckets.clear()


def rec(ltp, bid=0.0, ask=0.0, vol=0.0, ms=MIN_MS * 100):
    agg.record([("T1", {"ltp": ltp, "bid": bid, "ask": ask, "volume": vol})], ms)


def bucket(minute_ms=MIN_MS * 100):
    return agg._buckets["T1"][(minute_ms // MIN_MS) * 60]


def _stub_snapshot(monkeypatch) -> list:
    """Stand in for the Beanie Document — constructing a real one needs an
    initialised collection, and what is under test is the aggregation, not the
    ODM."""
    written: list = []

    class _Stub:
        def __init__(self, **kw):
            self.__dict__.update(kw)

        @staticmethod
        async def insert_many(docs):
            written.extend(docs)

    monkeypatch.setattr(agg, "TickSnapshot", _Stub)
    return written


def test_the_first_tick_seeds_both_extremes():
    """`low` starting at 0 would pin every low to zero forever — the bug the
    None sentinel exists to prevent."""
    rec(100.0, bid=99.5, ask=100.5)
    b = bucket()
    assert (b["open"], b["high"], b["low"], b["close"]) == (100.0, 100.0, 100.0, 100.0)
    assert (b["bid_low"], b["ask_low"]) == (99.5, 100.5)


def test_it_tracks_the_range_across_ticks():
    rec(100.0, bid=99.5, ask=100.5)
    rec(105.0, bid=104.5, ask=105.5)
    rec(98.0, bid=97.5, ask=98.5)
    b = bucket()
    assert (b["open"], b["high"], b["low"], b["close"]) == (100.0, 105.0, 98.0, 98.0)
    assert (b["bid_high"], b["bid_low"]) == (104.5, 97.5)
    assert (b["ask_high"], b["ask_low"]) == (105.5, 98.5)


def test_a_zero_priced_tick_is_not_recorded():
    """Mirrors the tick loop's own skip. A 0 in the history would read as a
    real print and would be believed."""
    rec(0.0, bid=99.5, ask=100.5)
    assert "T1" not in agg._buckets


def test_a_tick_with_no_book_still_records_its_price():
    """Illiquid contracts push no depth. Losing the LTP row too would leave a
    gap exactly where the argument usually is."""
    rec(100.0)
    b = bucket()
    assert b["high"] == 100.0
    assert b["bid_high"] == 0.0 and b["bid_low"] is None


def test_volume_only_ever_climbs():
    """Exchange volume is cumulative; a lower value is a thinner packet, not a
    reversal."""
    rec(100.0, vol=5000)
    rec(101.0, vol=3000)
    assert bucket()["volume"] == 5000


def test_minutes_are_kept_apart():
    rec(100.0, ms=MIN_MS * 100)
    rec(200.0, ms=MIN_MS * 101)
    assert bucket(MIN_MS * 100)["close"] == 100.0
    assert bucket(MIN_MS * 101)["close"] == 200.0


def test_a_bad_tick_does_not_take_the_batch_down():
    agg.record([("T1", {"ltp": "junk"}), ("T2", {"ltp": 50.0})], MIN_MS * 100)
    assert "T1" not in agg._buckets
    assert agg._buckets["T2"][MIN_MS * 100 // MIN_MS * 60]["close"] == 50.0


def test_an_empty_batch_is_a_no_op():
    agg.record([], MIN_MS * 100)
    assert agg._buckets == {}


@pytest.mark.asyncio
async def test_only_completed_minutes_flush(monkeypatch):
    """The current minute is still filling — writing it would store a partial
    range as if it were the whole minute."""
    written = _stub_snapshot(monkeypatch)

    rec(100.0, ms=MIN_MS * 100)
    assert await agg.flush_completed(now_ms=MIN_MS * 100 + 5_000) == 0
    assert not written
    assert agg._buckets["T1"], "the in-progress minute must be kept, not dropped"


@pytest.mark.asyncio
async def test_a_finished_minute_is_written_once_then_dropped(monkeypatch):
    """Written twice would double the history; kept forever would grow without
    bound in the leader's memory."""
    written = _stub_snapshot(monkeypatch)

    rec(100.0, bid=99.5, ask=100.5, ms=MIN_MS * 100)
    assert await agg.flush_completed(now_ms=MIN_MS * 101 + 1_000) == 1
    assert (written[0].bid_high, written[0].ask_low) == (99.5, 100.5)
    assert await agg.flush_completed(now_ms=MIN_MS * 101 + 2_000) == 0
    assert agg._buckets == {}


def test_the_loop_is_leader_gated_and_stoppable():
    import inspect

    from app import main

    src = inspect.getsource(main)
    assert "tick_aggregator_flush" in src
    assert '("app.services.tick_aggregator", "stop_tick_aggregator")' in src
    assert "tick_aggregator.record(mdlive_items, now_ms)" in inspect.getsource(
        __import__("app.services.market_data_service", fromlist=["x"]).tick_loop
    )


def test_stopping_drops_the_unflushed_minute():
    rec(100.0)
    agg.stop_tick_aggregator()
    assert agg._buckets == {}


def test_the_admin_can_read_it_back():
    from app.api.v1.admin.trading import router

    assert any("rate-history" in r.path for r in router.routes)
