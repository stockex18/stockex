"""A resting order must not fire on an extreme the day made before it existed.

Production, one afternoon: 23 of 28 pending-order fires came from the
day-extreme fallback, and every one of them was history rather than a cross.

    DIVISLAB  BUY LIMIT 9200.25   filled with the tape at 9308.0  (day low 9155)
    BAJAJ-AUTO BUY LIMIT 12230    filled with the tape at 12462   (day low 12152)

The order was accepted resting INSIDE the range, and the poller fired it on the
next pass against a low made hours earlier — a free 100-230 points, paid by the
operator, on repeat from the same accounts.

The fallback itself is wanted: a thin print can cross a level with no LTP tick
on the far side. It just has to prove the extreme is NEW.
"""

from __future__ import annotations

import inspect
from decimal import Decimal as D

import pytest

from app.models.order import OrderAction, OrderType
from app.services.matching_engine import _should_fill


def buy_limit(ltp, limit, hi=None, lo=None, ref_hi=None, ref_lo=None):
    return _should_fill(OrderType.LIMIT, OrderAction.BUY, D(str(ltp)), D(str(limit)),
                        D(0), hi, lo, ref_hi, ref_lo)


def sell_limit(ltp, limit, hi=None, lo=None, ref_hi=None, ref_lo=None):
    return _should_fill(OrderType.LIMIT, OrderAction.SELL, D(str(ltp)), D(str(limit)),
                        D(0), hi, lo, ref_hi, ref_lo)


def buy_stop(ltp, trig, hi=None, lo=None, ref_hi=None, ref_lo=None):
    return _should_fill(OrderType.SL_M, OrderAction.BUY, D(str(ltp)), D(0),
                        D(str(trig)), hi, lo, ref_hi, ref_lo)


def sell_stop(ltp, trig, hi=None, lo=None, ref_hi=None, ref_lo=None):
    return _should_fill(OrderType.SL_M, OrderAction.SELL, D(str(ltp)), D(0),
                        D(str(trig)), hi, lo, ref_hi, ref_lo)


# -- the reported farm -------------------------------------------------
def test_the_divislab_fill_does_not_happen_any_more():
    """Parked at 9200.25 while the range was already 9155-9339.5 and the tape
    was at 9308. Nothing about that is a cross."""
    assert not buy_limit(9308.0, 9200.25, hi=D("9339.5"), lo=D("9155"),
                         ref_hi=D("9339.5"), ref_lo=D("9155"))


def test_the_bajaj_auto_fill_does_not_happen_any_more():
    assert not buy_limit(12462, 12230, hi=D("12540"), lo=D("12152"),
                         ref_hi=D("12540"), ref_lo=D("12152"))


# -- what the fallback is FOR ------------------------------------------
def test_a_genuinely_new_low_still_fires_a_buy_limit():
    """Parked below the range; the day then trades down through it, with no
    LTP tick the 100 ms poller sampled landing at or under the level."""
    assert buy_limit(9160, 9150, hi=D("9339.5"), lo=D("9149"),
                     ref_hi=D("9339.5"), ref_lo=D("9155"))


def test_a_genuinely_new_high_still_fires_a_sell_limit():
    assert sell_limit(9330, 9345, hi=D("9346"), lo=D("9155"),
                      ref_hi=D("9339.5"), ref_lo=D("9155"))


def test_a_new_low_that_stops_short_of_the_level_does_not_fire():
    assert not buy_limit(9160, 9140, hi=D("9339.5"), lo=D("9149"),
                         ref_hi=D("9339.5"), ref_lo=D("9155"))


def test_touching_the_level_exactly_counts():
    assert buy_limit(9160, 9149, hi=D("9339.5"), lo=D("9149"),
                     ref_hi=D("9339.5"), ref_lo=D("9155"))


# -- the LTP rule is untouched -----------------------------------------
def test_a_real_ltp_cross_fires_with_no_watermark_at_all():
    """An order parked inside the range is still perfectly legal — it just has
    to wait for the price to actually get there."""
    assert buy_limit(9200, 9200.25)
    assert sell_limit(9350, 9345)
    assert buy_stop(9400, 9390)
    assert sell_stop(9100, 9110)


def test_an_unwatermarked_order_never_fires_on_an_extreme():
    """Orders parked before this shipped, and cold tokens. LTP only."""
    assert not buy_limit(9308, 9200.25, hi=D("9339.5"), lo=D("9155"))
    assert not sell_limit(9200, 9330, hi=D("9339.5"), lo=D("9155"))
    assert not buy_stop(9200, 9330, hi=D("9339.5"), lo=D("9155"))
    assert not sell_stop(9308, 9200, hi=D("9339.5"), lo=D("9155"))


# -- both stop sides -----------------------------------------------------
def test_a_buy_stop_needs_a_new_high():
    assert not buy_stop(9200, 9300, hi=D("9339.5"), lo=D("9155"),
                        ref_hi=D("9339.5"), ref_lo=D("9155"))
    assert buy_stop(9330, 9345, hi=D("9346"), lo=D("9155"),
                    ref_hi=D("9339.5"), ref_lo=D("9155"))


def test_a_sell_stop_needs_a_new_low():
    assert not sell_stop(9308, 9200, hi=D("9339.5"), lo=D("9155"),
                         ref_hi=D("9339.5"), ref_lo=D("9155"))
    assert sell_stop(9160, 9150, hi=D("9339.5"), lo=D("9149"),
                     ref_hi=D("9339.5"), ref_lo=D("9155"))


# -- a range we cannot trust -------------------------------------------
@pytest.mark.parametrize("hi,lo", [(None, None), (D("9339.5"), D(0)), (D(0), D("9155"))])
def test_a_half_populated_range_decides_nothing(hi, lo):
    assert not buy_limit(9308, 9200.25, hi=hi, lo=lo, ref_hi=D("9339.5"), ref_lo=D("9155"))


def test_a_zero_price_order_never_fires():
    assert not buy_limit(9308, 0, hi=D("9339.5"), lo=D("9149"),
                         ref_hi=D("9339.5"), ref_lo=D("9155"))


# -- wiring ------------------------------------------------------------
def test_the_watermark_is_stamped_at_placement():
    from app.services import order_service

    src = inspect.getsource(order_service)
    assert "**_range_ref(instrument.token)," in src
    assert "if hi > 0 and lo > 0 and hi >= lo:" in inspect.getsource(order_service._range_ref)


def test_the_stamp_reads_the_same_state_the_poller_reads():
    """A stamp taken from a different source than the poller's range could
    disagree with it, and the whole check turns on that comparison."""
    from app.services import order_service, matching_engine

    assert "get_quote_instant" in inspect.getsource(order_service._range_ref)
    assert "get_quote_instant" in inspect.getsource(matching_engine.trigger_pending_orders)


def test_the_order_carries_the_fields():
    from app.models.order import Order

    assert "range_ref_high" in Order.model_fields
    assert "range_ref_low" in Order.model_fields


def test_the_poller_hands_them_over():
    from app.services import matching_engine

    src = inspect.getsource(matching_engine.trigger_pending_orders)
    assert "o.range_ref_high" in src and "o.range_ref_low" in src
