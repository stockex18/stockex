"""Equity has no intraday. A share bought here is a share owned.

Operator: "equity me intraday ka section mat rahe, direct delivery me hi buy
ho — matlab margin delivery wala hi use ho."

So every equity order is CNC, and a delivery buy is paid for in full: no
leverage, no auto-squareoff at the bell. The one carve-out is an instrument
the user already has an open position in — that order keeps the position's own
product type, because positions are matched BY product type and a CNC sell
against an old MIS holding would open a second row instead of closing it.

That carve-out is no longer equity-only (see test_overnight_leg_nets), so
what is pinned here is the equity DEFAULT: with no open position, an equity
order is delivery.
"""

from __future__ import annotations

import inspect

from app.models._base import ProductType
from app.services import order_service, order_validator, pledge_service


def _src() -> str:
    return inspect.getsource(order_service.resolve_product_type)


def test_every_order_goes_through_the_one_resolver():
    s = inspect.getsource(order_service.place_order)
    assert "product_type = await resolve_product_type(" in s
    # Before anything is validated, locked or persisted.
    assert s.index("resolve_product_type(") < s.index("validate(")


def test_a_fresh_equity_order_is_delivery():
    s = _src()
    assert "return ProductType.CNC" in s
    assert "_pl.is_equity(" in s


def test_an_open_position_is_consulted_before_the_equity_default():
    """Otherwise the sell meant to close an old holding opens a second row
    beside it and the user is left holding both sides."""
    s = _src()
    assert "Position.status == PositionStatus.OPEN" in s
    assert s.index("Position.find_one(") < s.index("_pl.is_equity(")
    # The lookup must NOT filter by product type, or it would only ever find
    # the row that already matches — which is the bug, not the fix.
    assert "Position.product_type" not in s


def test_a_delivery_buy_is_paid_in_full():
    s = inspect.getsource(order_validator.validate)
    assert "margin_required = notional" in s
    block = s[s.index("A delivery buy is paid in full, pledge or no pledge"):]
    for cond in ("action == OrderAction.BUY", "_pl.is_equity(segment_type)",
                 '.upper() == "CNC"', "not is_squareoff", "not is_reducing"):
        assert cond in block[:700], cond


def test_closing_and_squareoff_are_never_charged_full_value():
    """A reducing order frees margin, it does not demand it again — and a
    forced squareoff must never be blocked by a margin rule."""
    s = inspect.getsource(order_validator.validate)
    block = s[s.index("A delivery buy is paid in full, pledge or no pledge"):]
    head = block[:block.index("margin_required = notional")]
    assert "not is_squareoff" in head and "not is_reducing" in head


def test_the_pledge_path_still_stands_on_its_own():
    """Pledge decides whether the shares back F&O margin. It no longer decides
    whether delivery is paid in full — that is now true either way."""
    s = inspect.getsource(order_validator.validate)
    assert "is_pledge_order = await _pl.pledge_mode(" in s
    assert "PLEDGE_NO_HOLDING" in s and "PLEDGE_IN_USE" in s
    # F&O pledge margin must not double up on a pledged equity order.
    assert "and not is_pledge_order" in s


def test_equity_means_both_exchanges():
    assert pledge_service.is_equity("NSE_EQUITY")
    assert pledge_service.is_equity("BSE_EQUITY")
    assert not pledge_service.is_equity("NSE_INDEX_FUTURE")
    assert not pledge_service.is_equity("MCX_FUTURE")


def test_delivery_is_the_carry_product_not_the_intraday_one():
    """CNC sits with NRML on the holding side of every cap, so an equity
    delivery counts against the holding limit and not the intraday one."""
    s = inspect.getsource(order_validator.validate)
    assert "product_type in (ProductType.NRML, ProductType.CNC)" in s
    assert "product_type == ProductType.MIS" in s
    assert ProductType.CNC == "CNC"
