"""A stop may sit inside today's range. A target may not.

The rule exists to stop a level being parked where the market has ALREADY
traded today, because such a level fires at once. For a TARGET that is the
whole exploit -- it books a profit at a price the market has since left. For
a STOP it is nothing of the kind: it fires and closes the trader at a LOSS,
which is their own business, and refusing it leaves them unable to protect a
position once the day's range has gone wide.

Operator, 30 Sept: "stop loss high or low ke bich mai lag jani chahiye fresh
or position lene kai baad -- or target nahi lagni chahiye."

Both halves are pinned. Relaxing the stop is only safe while the target stays
held back; the day they drift apart the rule protects nothing.
"""

from __future__ import annotations

import inspect
from decimal import Decimal

from app.models._base import OrderType
from app.services import order_validator
from app.services.order_validator import day_range_block

HIGH, LOW = Decimal("110"), Decimal("90")

_PLACE = inspect.getsource(order_validator.validate)
_GATE = _PLACE[_PLACE.index("block_inside_day_range") :]
_BRACKET = inspect.getsource(order_validator.day_range_block_for_bracket)


def test_placement_lets_both_kinds_of_stop_through():
    gate = _GATE[: _GATE.index("day_range_block(")]
    assert "OrderType.SL" in gate and "OrderType.SL_M" in gate


def test_placement_still_holds_a_limit_back():
    # A LIMIT is how a target is parked, and it must stay inside the rule.
    gate = _GATE[: _GATE.index("day_range_block(")]
    assert "OrderType.LIMIT" not in gate


def test_the_bracket_checks_the_target_and_not_the_stop():
    loop = _BRACKET[_BRACKET.index("for label, raw in") :]
    assert '"Target"' in loop
    assert '"Stop loss"' not in loop


def test_the_comparison_itself_is_unchanged():
    # Only WHO is asked changed. A price inside the band is still inside it,
    # bounds included, and an unknown range still stands aside.
    assert day_range_block(Decimal("100"), None, HIGH, LOW) is not None
    assert day_range_block(HIGH, None, HIGH, LOW) is not None
    assert day_range_block(LOW, None, HIGH, LOW) is not None
    assert day_range_block(Decimal("120"), None, HIGH, LOW) is None
    assert day_range_block(Decimal("80"), None, HIGH, LOW) is None
    assert day_range_block(Decimal("100"), None, Decimal("0"), Decimal("0")) is None


def test_a_market_order_was_never_in_the_rule_and_still_is_not():
    gate = _GATE[: _GATE.index("day_range_block(")]
    assert "OrderType.MARKET" in gate


def test_a_squareoff_still_passes_whatever_it_costs():
    # A forced exit must never be refused for sitting inside the range.
    gate = _GATE[: _GATE.index("day_range_block(")]
    assert "is_squareoff" in gate


def test_the_order_types_are_still_the_four_this_rule_assumes():
    assert {t.value for t in OrderType} == {"MARKET", "LIMIT", "SL", "SL_M"}
