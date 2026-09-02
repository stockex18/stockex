"""SL/TP has to fire on the day's range, not only on a sampled LTP.

The operator's case: long RELIANCE from 450 with a 468 target, day high 465
when it was set. The price later printed a 468.25 high, but no tick the
enforcer sampled ever showed 468 or better, so the target sat pending while
the chart plainly showed the high had gone through it.

    LONG  target -> day HIGH >= target      SHORT stop   -> day HIGH >= stop
    LONG  stop   -> day LOW  <= stop        SHORT target -> day LOW  <= target

The trap, and why the watermark exists: the range may ALREADY have passed the
level before the leg was set. A target parked under an earlier high would fire
the instant it is placed, closing at a price the market has not shown since —
paid by the operator, on every such position.
"""

from __future__ import annotations

import inspect
from decimal import Decimal as D

import pytest

from app.services import risk_enforcer

ZERO = D(0)


def _broke_high(level, d_hi, d_lo, ref_hi):
    """`_broke_high` as the enforcer defines it."""
    range_ok = d_hi > ZERO and d_lo > ZERO and d_hi >= d_lo
    return bool(range_ok and ref_hi is not None and level > ref_hi and d_hi >= level)


def _broke_low(level, d_hi, d_lo, ref_lo):
    range_ok = d_hi > ZERO and d_lo > ZERO and d_hi >= d_lo
    return bool(range_ok and ref_lo is not None and level < ref_lo and d_lo <= level)


# -- the reported case -------------------------------------------------
def test_a_wick_through_the_target_fires_it():
    """468 target, 465 high when set, day later prints 468.25. No LTP at or
    above 468 was ever sampled."""
    assert _broke_high(D("468"), d_hi=D("468.25"), d_lo=D("420"), ref_hi=D("465"))


def test_a_high_that_stops_short_does_not():
    assert not _broke_high(D("468"), d_hi=D("467.80"), d_lo=D("420"), ref_hi=D("465"))


def test_touching_the_level_exactly_counts():
    """The day has traded AT the price the user asked for."""
    assert _broke_high(D("468"), d_hi=D("468"), d_lo=D("420"), ref_hi=D("465"))


# -- the trap ----------------------------------------------------------
def test_a_target_under_an_earlier_high_does_not_fire_on_history():
    """Day high was already 465; a 460 target set afterwards must not close on
    a move the market made before the user asked for it."""
    assert not _broke_high(D("460"), d_hi=D("465"), d_lo=D("420"), ref_hi=D("465"))


def test_it_fires_once_the_day_goes_past_the_old_high():
    """Same 466 target, but now the day has genuinely moved beyond 465."""
    assert not _broke_high(D("466"), d_hi=D("465"), d_lo=D("420"), ref_hi=D("465"))
    assert _broke_high(D("466"), d_hi=D("466.50"), d_lo=D("420"), ref_hi=D("465"))


def test_a_leg_with_no_watermark_keeps_the_old_rule():
    """Legs set before this shipped have no reference range; they must stay on
    LTP alone rather than fire on whatever the day happens to show."""
    assert not _broke_high(D("468"), d_hi=D("470"), d_lo=D("420"), ref_hi=None)
    assert not _broke_low(D("410"), d_hi=D("470"), d_lo=D("400"), ref_lo=None)


# -- the down side -----------------------------------------------------
def test_a_wick_through_a_long_stop_fires_it():
    assert _broke_low(D("415"), d_hi=D("465"), d_lo=D("414.50"), ref_lo=D("420"))


def test_a_low_that_stops_short_does_not():
    assert not _broke_low(D("415"), d_hi=D("465"), d_lo=D("415.10"), ref_lo=D("420"))


def test_a_stop_above_an_earlier_low_does_not_fire_on_history():
    assert not _broke_low(D("425"), d_hi=D("465"), d_lo=D("420"), ref_lo=D("420"))


# -- a range we cannot trust -------------------------------------------
@pytest.mark.parametrize("hi,lo", [(D(0), D(0)), (D("468"), D(0)), (D(0), D("420"))])
def test_a_half_populated_range_decides_nothing(hi, lo):
    """The same missing-OHLC contracts that broke the day-range block. An
    unknown range must not be read as "the level was hit"."""
    assert not _broke_high(D("468"), d_hi=hi, d_lo=lo, ref_hi=D("465"))
    assert not _broke_low(D("415"), d_hi=hi, d_lo=lo, ref_lo=D("420"))


def test_a_backwards_range_is_not_trusted():
    assert not _broke_high(D("468"), d_hi=D("420"), d_lo=D("465"), ref_hi=D("465"))


# -- wiring ------------------------------------------------------------
def test_all_four_legs_check_the_side_they_face():
    src = inspect.getsource(risk_enforcer)
    assert "ltp_dec <= sl or _broke_low(sl)" in src        # long stop
    assert "ltp_dec >= tp or _broke_high(tp)" in src       # long target
    assert "ltp_dec >= sl or _broke_high(sl)" in src       # short stop
    assert "ltp_dec <= tp or _broke_low(tp)" in src        # short target


def test_the_ltp_rule_is_kept_alongside():
    """The range check is an addition. A crossed LTP must still fire even when
    the extremes say nothing."""
    src = inspect.getsource(risk_enforcer)
    assert "ltp_dec <= sl or" in src and "ltp_dec >= tp or" in src


def test_the_fill_still_books_at_the_users_price():
    """Whichever way it fires, the user asked for that price."""
    src = inspect.getsource(risk_enforcer)
    i = src.index("_broke_low(sl)")
    assert "fill_at = sl" in src[i:i + 200]


def test_the_watermark_is_stamped_when_a_leg_is_written():
    import io

    api = io.open(
        r"D:\stockex_new\backend\app\api\v1\user\positions.py",
        encoding="utf-8", errors="ignore",
    ).read()
    assert api.count("await _stamp_bracket_ref(p)") == 2   # both write sites
    assert "p.bracket_ref_high" in api and "p.bracket_ref_low" in api


def test_stamping_never_blocks_an_sl_tp_edit():
    """A quote hiccup must not stop a trader moving their stop."""
    import io

    api = io.open(
        r"D:\stockex_new\backend\app\api\v1\user\positions.py",
        encoding="utf-8", errors="ignore",
    ).read()
    i = api.index("async def _stamp_bracket_ref")
    body = api[i:i + 1400]
    assert "except Exception" in body and "return" in body


def test_the_watermark_needs_both_bounds():
    import io

    api = io.open(
        r"D:\stockex_new\backend\app\api\v1\user\positions.py",
        encoding="utf-8", errors="ignore",
    ).read()
    i = api.index("async def _stamp_bracket_ref")
    assert "if hi > 0 and lo > 0 and hi >= lo:" in api[i:i + 1400]
