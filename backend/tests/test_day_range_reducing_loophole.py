"""A position must not become a way around the day-range rule.

Reported from NSE: a resting order inside the day's high/low is correctly
refused — until you buy something. Then the same level goes through.

The cause was an exemption on REDUCING orders, added on the reasoning that "an
exit must never be blocked". Every real exit was already covered:

    Close button        places a MARKET order   -> exempt by order type
    stop-out engine     sets is_squareoff       -> exempt by that flag

So `is_reducing` only ever exempted a RESTING limit / SL that happened to
reduce — which is exactly the order the rule exists to stop, and it handed
anyone a way to place one: open a position first.
"""

from __future__ import annotations

import inspect

from app.services import order_validator as ov


def _gate() -> str:
    """The `if` that guards the day-range block, as deployed."""
    src = inspect.getsource(ov.validate)
    i = src.index('bool(s.get("block_inside_day_range"))')
    start = src.rindex("if (", 0, i)
    return src[start : src.index("):", i) + 2]


# ── the loophole is closed ────────────────────────────────────────────
def test_a_reducing_order_is_no_longer_exempt():
    assert "is_reducing" not in _gate()


def test_the_rule_still_only_looks_at_resting_orders():
    """A MARKET order fills on touch and never rests, so "inside the range" is
    meaningless for it — and that is how a user still exits at any price."""
    assert "order_type != OrderType.MARKET" in _gate()


def test_the_stop_out_is_still_exempt():
    """The enforcer retries a rejected close forever. Blocking one here would
    hot-loop and the position would never flatten."""
    assert "not is_squareoff" in _gate()


# ── the exits that must keep working ──────────────────────────────────
def test_the_close_button_places_a_market_order():
    """If this ever changes to a limit, closing a position breaks the moment
    the price sits inside the day's range."""
    import io

    api = io.open(
        r"D:\stockex_new\backend\app\api\v1\user\positions.py",
        encoding="utf-8", errors="ignore",
    ).read()
    assert api.count('"order_type": OrderType.MARKET.value') >= 4


def test_the_enforcer_marks_its_own_orders():
    from app.services import risk_enforcer

    assert "is_squareoff" in inspect.getsource(risk_enforcer)


# ── the rule itself is unchanged ──────────────────────────────────────
def test_a_level_inside_the_range_is_still_what_gets_blocked():
    from decimal import Decimal as D

    assert ov.day_range_block(D("9200"), None, D("9339"), D("9155")) is not None
    assert ov.day_range_block(D("9400"), None, D("9339"), D("9155")) is None
    assert ov.day_range_block(D("9100"), None, D("9339"), D("9155")) is None


def test_both_prices_are_checked():
    """An SL-M carries price 0 and sets only the trigger, so checking the limit
    price alone would let every SL-M through."""
    from decimal import Decimal as D

    hit = ov.day_range_block(D(0), D("9200"), D("9339"), D("9155"))
    assert hit is not None and hit[0] == "Trigger price"


def test_the_bounds_are_inclusive():
    """An order resting exactly ON the high or low is still inside the band the
    instrument has already traded through today."""
    from decimal import Decimal as D

    assert ov.day_range_block(D("9339"), None, D("9339"), D("9155")) is not None
    assert ov.day_range_block(D("9155"), None, D("9339"), D("9155")) is not None


def test_an_unknown_range_still_decides_nothing_here():
    """Pre-open and missing OHLC. The separate fail-closed check handles a live
    session with no range; this function must stay silent."""
    from decimal import Decimal as D

    assert ov.day_range_block(D("9200"), None, D(0), D(0)) is None


def test_the_fail_closed_check_is_still_there():
    """A session the feed has just stamped, with no high/low, refuses rather
    than guessing — that is what made the rule apply to every contract instead
    of only the ones with OHLC."""
    src = inspect.getsource(ov.validate)
    assert "DAY_RANGE_UNKNOWN" in src
    assert '_dq.get("stale") is False' in src
