"""Per-segment "block parked orders inside today's traded range" gate.

A resting order priced between today's low and high fills on the next small
wobble instead of a real breakout, so with the toggle on it must sit ABOVE the
high or BELOW the low.

Most of these guard the EXEMPTIONS rather than the block itself — that is
where this class of gate goes wrong.
"""

from __future__ import annotations

from decimal import Decimal as D

import pytest

from app.services.order_validator import day_range_block

HIGH, LOW = D("110"), D("90")


def test_price_inside_range_is_blocked():
    assert day_range_block(D("100"), None, HIGH, LOW) == ("Limit price", D("100"))


def test_price_above_high_is_allowed():
    assert day_range_block(D("111"), None, HIGH, LOW) is None


def test_price_below_low_is_allowed():
    assert day_range_block(D("89"), None, HIGH, LOW) is None


@pytest.mark.parametrize("edge", [HIGH, LOW])
def test_bounds_are_inclusive(edge):
    """Exactly on the high or the low is still INSIDE the traded band."""
    assert day_range_block(edge, None, HIGH, LOW) is not None


def test_slm_trigger_is_checked_not_just_limit_price():
    """An SL-M carries price 0 and sets only the trigger — checking the limit
    price alone would let every SL-M straight through."""
    assert day_range_block(D("0"), D("100"), HIGH, LOW) == ("Trigger price", D("100"))


def test_both_prices_checked_limit_reported_first():
    hit = day_range_block(D("100"), D("105"), HIGH, LOW)
    assert hit == ("Limit price", D("100"))


def test_trigger_inside_blocks_even_when_limit_is_outside():
    assert day_range_block(D("200"), D("95"), HIGH, LOW) == ("Trigger price", D("95"))


@pytest.mark.parametrize(
    "high,low",
    [(D("0"), D("0")), (D("110"), D("0")), (D("0"), D("90"))],
)
def test_unknown_range_stands_aside(high, low):
    """Pre-open / fresh subscribe / no OHLC. Treating an unknown range as
    "everything is inside" would reject every parked order before the bell."""
    assert day_range_block(D("100"), D("100"), high, low) is None


def test_inverted_range_stands_aside():
    """A half-populated OHLC tells us nothing — never block on it."""
    assert day_range_block(D("100"), None, D("90"), D("110")) is None


@pytest.mark.parametrize("p", [None, D("0"), D("-5")])
def test_missing_or_zero_price_is_skipped(p):
    assert day_range_block(p, None, HIGH, LOW) is None


def test_market_order_exemption_is_enforced_by_the_caller():
    """MARKET fills on touch and never rests, so the gate must not run for it.
    The helper is price-only; the exemption lives in the call site — assert it
    is still written there."""
    import inspect

    from app.services import order_validator

    src = inspect.getsource(order_validator.validate)
    i = src.index("block_inside_day_range")
    window = src[i : i + 260]
    assert "order_type != OrderType.MARKET" in window
    assert "not is_squareoff" in window
    # NOT `is_reducing`. Exempting it was the loophole — open a position and
    # every level inside the range became placeable. Real exits are already
    # covered: Close places a MARKET order, the stop-out sets is_squareoff.
    assert "not is_reducing" not in window


def test_gate_is_independent_of_the_limit_away_band():
    """Both may be configured; this one must not sit inside the limit_pct
    block, or turning limit-away off would silently disable it too."""
    import inspect

    from app.services import order_validator

    src = inspect.getsource(order_validator.validate)
    gate_line = next(
        ln for ln in src.splitlines() if "bool(s.get(\"block_inside_day_range\"))" in ln
    )
    # 8 spaces of indent would mean it is nested inside `if limit_pct > 0:`.
    assert len(gate_line) - len(gate_line.lstrip()) == 8
    guard = next(ln for ln in src.splitlines() if "if (" in ln and src.index(ln) < src.index(gate_line))
    assert len(guard) - len(guard.lstrip()) <= 4
