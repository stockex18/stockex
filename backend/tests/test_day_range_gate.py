"""The day-range block must not fall silent when the range is missing.

Reported: with `block_inside_day_range` ON, orders still filled between the
open and the low — "some stocks, not all". Traced on one user's real book,
same instrument, same afternoon:

    14:28  BAJAJ-AUTO  BUY  LIMIT 12,200  EXECUTED   <- got through
    14:30  BAJAJ-AUTO  SELL LIMIT 12,499  EXECUTED   <- got through
    14:40  BAJAJ-AUTO  BUY  LIMIT 12,300  REJECTED   <- correctly stopped

Nothing about the setting changed in between: the user has no override at all
and the rule resolves True on every segment. What changed was the QUOTE.
`day_range_block` returns None whenever high or low is 0, and plenty of
contracts tick with no OHLC at all. The rule was not being bypassed — it was
standing aside, exactly as written.

Standing aside is right before the bell. It is wrong mid-session, which is
what this guards.
"""

from __future__ import annotations

import inspect
from decimal import Decimal as D

import pytest

from app.services.order_validator import day_range_block


def _blocked(price, hi, lo):
    return day_range_block(D(str(price)), None, D(str(hi)), D(str(lo)))


# -- the comparison itself ---------------------------------------------
@pytest.mark.parametrize("price", [12300, 12200, 12499])
def test_a_price_inside_the_range_is_caught(price):
    assert _blocked(price, 12500, 12100) is not None


@pytest.mark.parametrize("price", [12600, 12000])
def test_a_price_outside_the_range_is_allowed(price):
    assert _blocked(price, 12500, 12100) is None


def test_the_bounds_themselves_count_as_inside():
    """The instrument has already traded through them today."""
    assert _blocked(12500, 12500, 12100) is not None
    assert _blocked(12100, 12500, 12100) is not None


def test_a_trigger_is_checked_as_well_as_a_limit():
    """An SL-M carries price 0 and sets only the trigger, so checking the limit
    alone would let every one of them through."""
    hit = day_range_block(D(0), D("12300"), D("12500"), D("12100"))
    assert hit is not None and hit[0] == "Trigger price"


# -- the hole that was letting them through ----------------------------
@pytest.mark.parametrize("hi,lo", [(0, 0), (12500, 0), (0, 12100)])
def test_an_unknown_range_still_stands_aside_here(hi, lo):
    """The comparison cannot judge without both bounds — that part is correct
    and unchanged. The decision about what to DO moved to the caller."""
    assert _blocked(12300, hi, lo) is None


def test_a_backwards_range_is_not_trusted():
    assert _blocked(12300, 12100, 12500) is None


# -- the caller now refuses instead of guessing ------------------------
def test_a_live_quote_with_no_range_is_refused():
    """`stale is False` means the feed stamped this quote just now, so the
    session is live and a missing high/low is incomplete data, not pre-open."""
    from app.services import order_validator

    src = inspect.getsource(order_validator.validate)
    assert '(_day_high <= 0 or _day_low <= 0) and _dq.get("stale") is False' in src
    assert "DAY_RANGE_UNKNOWN" in src


def test_pre_open_and_clockless_feeds_are_untouched():
    """`stale` is False only for a fresh exchange stamp. Pre-open, a closed
    session and Infoway crypto/forex never satisfy it, so they still stand
    aside — blocking those would stop trading outright."""
    from app.services import order_validator

    src = inspect.getsource(order_validator.validate)
    i = src.index("DAY_RANGE_UNKNOWN")
    guard = src[src.rindex("if ", 0, i):i]
    assert 'is False' in guard          # not "not stale", which None satisfies


def test_the_refusal_comes_after_the_real_check():
    """A price that IS inside the range must report that, not the vaguer
    'range unavailable'."""
    from app.services import order_validator

    src = inspect.getsource(order_validator.validate)
    assert src.index("INSIDE_DAY_RANGE") < src.index("DAY_RANGE_UNKNOWN")


def test_exits_and_market_orders_are_still_exempt():
    """A market order fills at LTP, which is inside the range by definition,
    and a user must always be able to flatten."""
    from app.services import order_validator

    src = inspect.getsource(order_validator.validate)
    i = src.index("block_inside_day_range")
    gate = src[i:i + 260]
    assert "order_type != OrderType.MARKET" in gate
    assert "not is_squareoff" in gate
    assert "not is_reducing" in gate
