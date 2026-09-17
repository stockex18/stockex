"""The tick archive keeps one row per instrument per second, not four.

Measured on the box: MongoDB was taking 3,393 inserts a second on two cores
while user queries ran at 50 — 111 million rows and 7.9 GB written on 16 Sep
alone. The feed pump passes each token about four times a second and the extra
rows say the same thing. One a second still answers "what did this print at
11:42:07", which is the only question this archive exists for.
"""

from __future__ import annotations

from app.services import tick_store


def _reset():
    tick_store._buffer.clear()
    tick_store._last_second.clear()


def _quote(ltp: float) -> dict:
    return {"ltp": ltp, "bid": ltp - 0.5, "ask": ltp + 0.5}


def test_four_passes_in_one_second_store_one_row():
    _reset()
    base = 1_789_552_800_000  # some second, in ms
    for offset in (0, 250, 500, 750):
        tick_store.record([("17512194", _quote(23274 + offset))], base + offset)
    assert len(tick_store._buffer) == 1


def test_the_next_second_stores_again():
    _reset()
    base = 1_789_552_800_000
    tick_store.record([("17512194", _quote(23274))], base)
    tick_store.record([("17512194", _quote(23280))], base + 1000)
    assert len(tick_store._buffer) == 2
    assert [r["ltp"] for r in tick_store._buffer] == [23274, 23280]


def test_each_instrument_gets_its_own_row():
    _reset()
    base = 1_789_552_800_000
    tick_store.record(
        [("17512194", _quote(23274)), ("144870151", _quote(9940))], base
    )
    tick_store.record(
        [("17512194", _quote(23275)), ("144870151", _quote(9941))], base + 300
    )
    assert len(tick_store._buffer) == 2
    assert {r["token"] for r in tick_store._buffer} == {"17512194", "144870151"}


def test_a_priceless_pass_does_not_claim_the_second():
    """A token with no live price writes nothing — and must not block the row
    that arrives later in the same second."""
    _reset()
    base = 1_789_552_800_000
    tick_store.record([("17512194", {"ltp": 0})], base)
    assert tick_store._buffer == []
    tick_store.record([("17512194", _quote(23274))], base + 400)
    assert len(tick_store._buffer) == 1


def test_the_second_map_cannot_grow_without_bound():
    _reset()
    base = 1_789_552_800_000
    tick_store._last_second.update({str(i): 1 for i in range(tick_store._MAX_SECOND_KEYS + 1)})
    tick_store.record([("17512194", _quote(23274))], base)
    assert len(tick_store._last_second) == 1
