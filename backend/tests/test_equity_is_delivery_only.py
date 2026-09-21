"""Equity has no intraday. A share bought here is a share owned.

Operator: "equity me intraday ka section mat rahe, direct delivery me hi buy
ho — matlab margin delivery wala hi use ho."

So every equity order is CNC, and a delivery buy is paid for in full: no
leverage, no auto-squareoff at the bell. The one carve-out is an instrument
the user already has an open position in — that order keeps the position's own
product type, because positions are matched BY product type and a CNC sell
against an old MIS holding would open a second row instead of closing it.
"""

from __future__ import annotations

import inspect

from app.models._base import ProductType
from app.services import order_service, order_validator, pledge_service


def _src() -> str:
    return inspect.getsource(order_service.resolve_equity_product)


def test_every_order_goes_through_the_one_resolver():
    s = inspect.getsource(order_service.place_order)
    assert "product_type = await resolve_equity_product(" in s
    # Before anything is validated, locked or persisted.
    assert s.index("resolve_equity_product(") < s.index("validate(")


def test_a_fresh_equity_order_is_delivery():
    s = _src()
    assert "return ProductType.CNC" in s
    assert "_pl.is_equity(" in s


def test_anything_that_is_not_equity_is_untouched():
    s = _src()
    assert "if not _pl.is_equity(" in s
    assert s.index("if not _pl.is_equity(") < s.index("Position.find_one(")


def test_an_open_position_keeps_its_own_product_type():
    """Otherwise the sell that was meant to close an old MIS holding opens a
    short beside it and the user is left holding both."""
    s = _src()
    assert "Position.status == PositionStatus.OPEN" in s
    assert "product_type" in s
    # The lookup must NOT filter by product type, or it would never find the
    # old row it exists to protect.
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
