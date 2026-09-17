"""Every tick, stored, for two days — and nothing older.

The value of this store is that it can be trusted when someone disputes a
fill. So the things worth pinning are the ones that would make it lie or make
it dangerous: a zero written as if it were a print, retention that quietly
grows, a delete that runs long enough to hurt the feed, and a buffer that eats
the leader's memory when the writer stalls.
"""

from __future__ import annotations

import inspect
from datetime import datetime, timedelta, timezone

import pytest

from app.services import tick_store as ts

MS = 1_788_000_000_000


@pytest.fixture(autouse=True)
def _clean():
    # `_last_second` too: the store keeps one row per token per second, so a
    # test reusing the same token at the same millisecond as the last one
    # would otherwise be deduped away and find an empty buffer.
    ts._buffer.clear()
    ts._last_second.clear()
    yield
    ts._buffer.clear()
    ts._last_second.clear()


def q(**kw):
    base = {"ltp": 100.0, "bid": 99.5, "ask": 100.5, "high": 105.0, "low": 98.0,
            "volume": 1234, "exchange_timestamp": 1788000000}
    base.update(kw)
    return base


# ── what a row holds ──────────────────────────────────────────────────
def test_a_row_carries_everything_the_operator_asked_for():
    ts.record([("T1", q())], MS)
    r = ts._buffer[0]
    for k in ("token", "ts", "ets", "ltp", "bid", "ask",
              "open", "high", "low", "prev_close", "volume"):
        assert k in r, k


def test_it_stores_the_whole_ohlc_strip_the_user_reads():
    """The screen shows O / H / L / C. Storing only H and L would leave a row
    that says what the price was but not what the day looked like around it."""
    ts.record([("T1", q(open=99.0, prev_close=97.5))], MS)
    r = ts._buffer[0]
    assert (r["open"], r["high"], r["low"], r["prev_close"]) == (99.0, 105.0, 98.0, 97.5)


def test_the_previous_close_is_named_as_such():
    """Kite's `ohlc.close` is the PREVIOUS session's close and every change%
    on the platform is measured from it. Calling it `close` in a row stamped
    with today's date is how someone reads it as today's."""
    src = inspect.getsource(ts.record)
    assert '"prev_close": float(q.get("prev_close") or 0)' in src


def test_it_keeps_the_exchange_clock_separately_from_ours():
    """`ts` is when we saw it; `ets` is when it happened. Only the second one
    settles an argument about a fill."""
    ts.record([("T1", q(exchange_timestamp=1788000123))], MS)
    r = ts._buffer[0]
    assert r["ets"] == 1788000123
    assert r["ts"] == datetime.fromtimestamp(MS / 1000, tz=timezone.utc)


def test_a_zero_price_is_a_gap_not_a_row():
    """A zero reads back as a real print of zero, which is worse than nothing
    being there at all."""
    ts.record([("T1", q(ltp=0))], MS)
    assert ts._buffer == []


def test_a_junk_quote_does_not_take_the_batch_down():
    ts.record([("T1", q(ltp="junk")), ("T2", q())], MS)
    assert [r["token"] for r in ts._buffer] == ["T2"]


def test_an_empty_pass_does_nothing():
    ts.record([], MS)
    assert ts._buffer == []


# ── the buffer cannot eat the worker ──────────────────────────────────
def test_a_stalled_writer_cannot_grow_the_buffer_without_bound():
    """If the flush loop dies while the tick loop keeps running, dropping the
    oldest rows beats being OOM-killed with the feed inside the process."""
    ts._buffer.extend({"token": "x"} for _ in range(ts._MAX_BUFFER + 500))
    ts.record([("T1", q())], MS)
    assert len(ts._buffer) <= ts._MAX_BUFFER + 1


def test_the_buffer_is_detached_before_the_write():
    """Ticks arriving mid-write must land in the NEXT batch, not vanish with
    the list that was being inserted."""
    src = inspect.getsource(ts.flush_once)
    assert "batch = _buffer[:]" in src
    assert "del _buffer[: len(batch)]" in src
    assert src.index("del _buffer") < src.index("insert_many")


def test_one_bad_row_does_not_reject_the_batch():
    assert "ordered=False" in inspect.getsource(ts.flush_once)


# ── retention ─────────────────────────────────────────────────────────
def test_two_days_not_thirty():
    assert ts.RETENTION_DAYS == 2


def test_a_day_is_an_IST_day():
    """A dispute is phrased in the trading day it happened on. Naming by UTC
    would split one session across two collections after 05:30 IST."""
    late = datetime(2026, 9, 3, 20, 0, tzinfo=timezone.utc)  # 01:30 IST on the 4th
    assert ts.collection_name(late) == "ticks_2026_09_04"


def test_retention_drops_collections_it_does_not_delete_rows():
    """A deleteMany over millions of rows is minutes of disk on two cores. A
    drop is instant however many rows are in it."""
    src = inspect.getsource(ts.drop_old_collections)
    assert ".drop()" in src
    assert "delete_many" not in src


def test_the_keep_set_is_built_from_today_backwards():
    src = inspect.getsource(ts.drop_old_collections)
    assert "for d in range(keep_days)" in src


def test_it_only_touches_its_own_collections():
    """A prefix check is the only thing standing between this and dropping the
    orders collection."""
    src = inspect.getsource(ts.drop_old_collections)
    assert "name.startswith(_PREFIX)" in src
    assert ts._PREFIX == "ticks_"


@pytest.mark.asyncio
async def test_the_sweep_is_idempotent(monkeypatch):
    """It runs hourly. Today and yesterday must survive every one of those."""
    now = datetime.now(timezone.utc)
    names = [ts.collection_name(now - timedelta(days=d)) for d in range(5)]
    dropped: list[str] = []

    class _Coll:
        def __init__(self, n): self.n = n
        async def drop(self): dropped.append(self.n)

    class _DB:
        async def list_collection_names(self):
            return names + ["orders", "positions"]
        def __getitem__(self, n): return _Coll(n)

    monkeypatch.setattr("app.core.database.get_db", lambda: _DB())
    first = await ts.drop_old_collections()
    assert set(first) == set(names[2:]), "today and yesterday must survive"
    assert "orders" not in dropped and "positions" not in dropped


# ── wiring ────────────────────────────────────────────────────────────
def test_the_index_is_created_on_an_empty_collection():
    """Adding (token, ts) to a few million rows later would be an outage; on
    an empty one it costs nothing."""
    src = inspect.getsource(ts._ensure_index)
    assert '[("token", 1), ("ts", 1)]' in src
    assert "background=True" in src


def test_the_tick_loop_only_appends():
    """`record` is on the feed's hot path. Any await in it and the feed waits
    on Mongo."""
    assert not inspect.iscoroutinefunction(ts.record)


def test_it_is_fed_from_the_same_place_the_per_minute_store_is():
    from app.services import market_data_service as mds

    src = inspect.getsource(mds.tick_loop)
    assert "tick_store.record(mdlive_items, now_ms)" in src


def test_the_loop_runs_where_the_buffer_is_and_stops_cleanly():
    from app import main

    src = inspect.getsource(main)
    assert "tick_store_flush" in src
    assert '("app.services.tick_store", "stop_tick_store")' in src
