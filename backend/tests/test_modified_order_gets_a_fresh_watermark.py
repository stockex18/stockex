"""A modified order may not fire on an extreme the day made before the change.

Operator: "In any instrument, after placing a buy or sell offer, if you
modified it and place an offer between the high and low price, it gets placed
— high low ke beech me order modify hoke bhi mat lage."

The poller's day-extreme fallback only fires a level that the session reached
AFTER the order was parked, measured against a watermark stamped at placement
(`order_service._range_ref`). Modify rewrote the price but left that mark
where it was, so a level moved to somewhere INSIDE today's range still read as
"beyond the mark" and filled the instant it was saved.
"""

from __future__ import annotations

import asyncio
import inspect
from decimal import Decimal
from types import SimpleNamespace

from bson import Decimal128

from app.models.order import OrderAction, OrderType
from app.services import order_service
from app.services.matching_engine import _should_fill

D = Decimal
# Today: low 100, high 110, trading at 108.
DAY_LOW, DAY_HIGH, LTP = D("100"), D("110"), D("108")


def _buy_limit(level, ref_high, ref_low):
    return _should_fill(
        OrderType.LIMIT, OrderAction.BUY, LTP, D(level), D("0"),
        DAY_HIGH, DAY_LOW, ref_high, ref_low,
    )


def test_a_level_inside_todays_range_does_not_fire_on_a_fresh_mark():
    # Re-stamped on modify: the mark IS today's range, so nothing is "beyond".
    assert _buy_limit("105", DAY_HIGH, DAY_LOW) is False


def test_the_stale_mark_is_what_used_to_fire_it():
    # The mark as it stood when the order was first parked, before the day
    # widened. 105 reads as below it, so the fallback fired at once.
    assert _buy_limit("105", D("107"), D("106")) is True


def test_a_real_price_cross_still_fills():
    # LTP at or under the limit — the ordinary rule, untouched.
    assert _buy_limit("108", DAY_HIGH, DAY_LOW) is True


def test_a_new_low_after_the_modify_still_fills():
    # Mark re-stamped at 100; the session then prints 99 and reaches the level.
    assert _should_fill(
        OrderType.LIMIT, OrderAction.BUY, LTP, D("99.5"), D("0"),
        DAY_HIGH, D("99"), DAY_HIGH, D("100"),
    ) is True


def test_restamping_takes_the_range_as_it_stands_now(monkeypatch):
    async def fresh(_token):
        return {"range_ref_high": Decimal128("110"), "range_ref_low": Decimal128("100")}

    monkeypatch.setattr(order_service, "_range_ref", fresh)
    o = SimpleNamespace(
        instrument=SimpleNamespace(token="1"),
        range_ref_high=Decimal128("107"),
        range_ref_low=Decimal128("106"),
    )
    asyncio.run(order_service.restamp_range_ref(o))
    assert str(o.range_ref_high) == "110" and str(o.range_ref_low) == "100"


def test_no_readable_range_clears_the_mark_instead_of_keeping_it(monkeypatch):
    async def cold(_token):
        return {}

    monkeypatch.setattr(order_service, "_range_ref", cold)
    o = SimpleNamespace(
        instrument=SimpleNamespace(token="1"),
        range_ref_high=Decimal128("107"),
        range_ref_low=Decimal128("106"),
    )
    asyncio.run(order_service.restamp_range_ref(o))
    # Fallback off, plain LTP rule — the safe direction to fail in.
    assert o.range_ref_high is None and o.range_ref_low is None


def test_modify_restamps_before_it_saves():
    from app.api.v1.user import orders as user_orders

    src = inspect.getsource(user_orders.modify)
    assert "order_service.restamp_range_ref(o)" in src
    assert src.index("restamp_range_ref") < src.index("await o.save()")


def test_only_a_moved_level_restamps():
    from app.api.v1.user import orders as user_orders

    src = inspect.getsource(user_orders.modify)
    # Changing lots alone leaves the mark alone.
    assert "level_moved = payload.price is not None or payload.trigger_price is not None" in src
    assert "if level_moved:" in src
