"""An opening order has to afford its brokerage, not just its margin.

Reported: a 2-crore position sized to fit the margin exactly still went
through, leaving nothing behind for the fee the fill charges moments later.

The funds check was `margin_required > available`. Brokerage simply was not in
it. It is now, computed with the SAME calculator and the SAME resolved
settings the matching engine uses at fill — a check that disagrees with the
charge is worse than no check.
"""

from __future__ import annotations

import inspect
from decimal import Decimal as D

import pytest

from app.services import brokerage_calculator as bc
from app.services import order_validator


def _afford(margin: D, brokerage: D, available: D) -> bool:
    """The comparison as the validator now makes it."""
    return (margin + brokerage) <= available


# -- the reported case -------------------------------------------------
def test_a_position_that_fits_the_margin_but_not_the_fee_is_refused():
    """2 crore at 50x = 4,00,000 margin. The wallet holds exactly that, so the
    old check passed and the fee had nothing behind it."""
    assert _afford(D("400000"), D("2000"), D("400000")) is False


def test_the_same_position_goes_through_once_the_fee_is_covered():
    assert _afford(D("400000"), D("2000"), D("402000")) is True


def test_margin_alone_still_has_to_fit():
    assert _afford(D("400000"), D("0"), D("399999")) is False


@pytest.mark.parametrize("fee", [D("0.01"), D("1"), D("2000"), D("50000")])
def test_any_uncovered_fee_stops_it(fee):
    assert _afford(D("400000"), fee, D("400000")) is False


def test_a_segment_with_no_brokerage_configured_is_unaffected():
    """Zero fee means the check is exactly what it was before."""
    assert _afford(D("400000"), D("0"), D("400000")) is True


# -- it must agree with what is actually charged -----------------------
def test_the_estimate_uses_the_engine_s_own_calculator():
    """A check computed a second way is a check that will one day disagree
    with the charge."""
    src = inspect.getsource(order_validator.validate)
    assert "brokerage_calculator as _bc" in src
    assert "_bc.calculate(" in src


def test_it_passes_the_same_resolved_settings_the_fill_uses():
    src = inspect.getsource(order_validator.validate)
    i = src.index("_bc.calculate(")
    call = src[i:i + 420]
    assert "netting_override=s" in call
    assert 'charge_on=s.get("charge_on")' in call
    assert "price=ref_price" in call


def test_it_is_priced_as_an_opening_leg():
    """A close is exempt from this whole branch, and its fee comes out of the
    proceeds — asking for it here would double-count."""
    src = inspect.getsource(order_validator.validate)
    i = src.index("_bc.calculate(")
    assert "is_closing=False" in src[i:i + 420]


def test_the_result_field_matches_the_calculator():
    """`getattr(_ch, "brokerage")` silently yields the fallback if the field is
    ever renamed, which would turn the gate off without failing."""
    assert "brokerage" in bc.ChargesBreakdown.__dataclass_fields__


# -- what must not happen ----------------------------------------------
def test_a_calculation_failure_does_not_reject_the_trade():
    """That would be our own arithmetic refusing a trade the user can afford.
    Zero is exactly how this behaved before the fee was counted at all."""
    src = inspect.getsource(order_validator.validate)
    i = src.index("_bc.calculate(")
    tail = src[i:i + 700]
    assert "except Exception" in tail
    assert "_brokerage_due = to_decimal(0)" in tail


def test_closing_and_reducing_orders_never_reach_this_check():
    src = inspect.getsource(order_validator.validate)
    assert "if is_reducing or is_squareoff:" in src
    assert src.index("if is_reducing or is_squareoff:") < src.index("_brokerage_due")


def test_the_message_separates_margin_from_fee():
    """Otherwise the number on screen looks like it should have worked."""
    src = inspect.getsource(order_validator.validate)
    assert "margin" in src[src.index("_brokerage_due > 0"):][:400]
    assert "brokerage" in src[src.index("_brokerage_due > 0"):][:400]
