"""A frame that carries no price must not erase the price we have.

Every field of a tick is built as `float(... or 0)`, and Kite's frames are not
uniform: the 8-byte LTP packet has no OHLC block at all, and a frame can arrive
with no `last_price` (pre-open, a halted contract, a mode change that has not
taken). The handler replaced the whole cached payload, so a thin frame wrote
hard zeros over good live values.

That dict IS the price for everything downstream — `ticks_by_token`,
`get_ltp_live`, `get_quote_instant`, the day high/low the pending poller reads,
and the `market:tick` publish the chart renders. Hence "rate ek second ke liye
0 ho jata hai" and "high-low galat dikhta hai": never bad exchange data, only a
thinner frame overwriting a fuller one.
"""

from __future__ import annotations

import pytest

from app.services.zerodha_service import zerodha

TOKEN = 999999001


@pytest.fixture(autouse=True)
def _clean():
    zerodha.ticks_by_token.pop(TOKEN, None)
    yield
    zerodha.ticks_by_token.pop(TOKEN, None)


def feed(**tick):
    tick.setdefault("instrument_token", TOKEN)
    zerodha._handle_parsed_ticks([tick])
    return zerodha.ticks_by_token[TOKEN]


FULL = dict(
    last_price=9308.0,
    ohlc={"open": 9200.0, "high": 9339.5, "low": 9155.0, "close": 9190.0},
    volume_traded=125000,
    exchange_timestamp=1788000000,
    last_trade_time=1788000000,
)


def test_a_full_frame_lands_as_itself():
    q = feed(**FULL)
    assert q["ltp"] == 9308.0
    assert (q["high"], q["low"]) == (9339.5, 9155.0)


def test_a_priceless_frame_holds_the_last_real_price():
    feed(**FULL)
    q = feed(last_price=0)
    assert q["ltp"] == 9308.0


def test_a_priceless_frame_holds_the_range_too():
    """The day-range order gate and the poller's extreme check both read this."""
    feed(**FULL)
    q = feed(last_price=0)
    assert (q["high"], q["low"], q["open"], q["close"]) == (9339.5, 9155.0, 9200.0, 9190.0)


def test_an_ltp_only_frame_keeps_the_ohlc_and_takes_the_new_price():
    """The 8-byte packet: a real price, no OHLC block. Both halves matter."""
    feed(**FULL)
    q = feed(last_price=9312.5)
    assert q["ltp"] == 9312.5
    assert (q["high"], q["low"]) == (9339.5, 9155.0)


def test_a_new_extreme_still_gets_through():
    """Carrying forward must never mean freezing."""
    feed(**FULL)
    q = feed(last_price=9350.0, ohlc={"open": 9200.0, "high": 9350.0, "low": 9155.0, "close": 9190.0})
    assert (q["ltp"], q["high"]) == (9350.0, 9350.0)


def test_a_priceless_frame_does_not_refresh_the_exchange_clock():
    """The 2-second order gate ages off `exchange_timestamp`. Restamping a
    price we did not observe would make a dead feed look live and let orders
    fill against it."""
    feed(**FULL)
    q = feed(last_price=0, exchange_timestamp=1788009999)
    assert q["exchange_timestamp"] == 1788000000


def test_a_real_frame_does_refresh_it():
    feed(**FULL)
    q = feed(last_price=9312.5, exchange_timestamp=1788009999)
    assert q["exchange_timestamp"] == 1788009999


def test_frame_liveness_still_advances_on_a_priceless_frame():
    """`received_at` answers "is the socket alive", not "is the price new" —
    we did receive a frame."""
    first = feed(**FULL)["received_at"]
    assert feed(last_price=0)["received_at"] >= first


def test_a_cold_token_with_no_price_stays_at_zero():
    """Nothing to carry forward, and 0 must keep meaning "no live price" so
    the order gate refuses to fill. Never invent one."""
    assert feed(last_price=0)["ltp"] == 0


def test_the_book_is_held_with_the_price():
    """bid/ask are derived from the frame; a price-less frame zeroes them, and
    a 0 bid/ask reads downstream as "cannot fill"."""
    feed(**FULL, depth={"buy": [{"price": 9307.5}], "sell": [{"price": 9308.5}]})
    q = feed(last_price=0)
    assert (q["bid"], q["ask"]) == (9307.5, 9308.5)
    assert q["has_depth"] is True
