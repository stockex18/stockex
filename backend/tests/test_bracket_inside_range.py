"""A stop-loss lives inside the day's range. It has to be settable there.

Reported: SL/TP would not save. Reproduced on a live position —

    DIVISLAB26SEPFUT   ltp 9241.00   day 9204.00 - 9325.00
    stop loss 9226.20  ->  "is inside today's range"

Every stop-loss is that shape: just under the price, and therefore inside the
band the instrument has already traded through today. The gate made brackets
impossible to set on any ordinary day.

It was there because a level inside the range could be fired by a PRE-EXISTING
extreme the moment it was stored. `bracket_ref_high` / `bracket_ref_low` closed
that hole — the enforcer's range check only fires once the day moves BEYOND
where it stood when the leg was set — so the gate was guarding something that
can no longer happen.

What still guards the real risk is the DIRECTION check, and that stays.
"""

from __future__ import annotations

import inspect

from decimal import Decimal as D

from app.api.v1.user import positions as api
from app.services import order_validator as ov


# ── the gate is gone from both bracket paths ──────────────────────────
def test_neither_bracket_endpoint_applies_the_day_range_gate():
    src = inspect.getsource(api)
    assert "day_range_block_for_bracket" not in src


def test_the_reason_is_written_where_someone_would_re_add_it():
    """A removal with no explanation gets restored by the next person who
    reads the order gate and assumes the bracket path was an oversight."""
    src = inspect.getsource(api.update_sl_tp)
    assert "NO DAY-RANGE GATE HERE" in src
    assert "bracket_ref_high" in src


# ── the guard that still matters ──────────────────────────────────────
def test_the_direction_check_survives_on_both_paths():
    """This is the one that stops a leg being parked on the WRONG side of the
    price, where the enforcer fills it instantly at a price the market never
    traded."""
    for fn in (api.update_sl_tp, api.update_active_trade_sl_tp):
        assert "bracket_direction_error" in inspect.getsource(fn), fn.__name__


def test_a_long_stop_above_the_price_is_still_refused():
    assert ov.bracket_direction_error("BUY", 9241.0, sl=9300.0, tp=None)
    assert ov.bracket_direction_error("BUY", 9241.0, sl=None, tp=9100.0)


def test_a_short_stop_below_the_price_is_still_refused():
    assert ov.bracket_direction_error("SELL", 9241.0, sl=9100.0, tp=None)
    assert ov.bracket_direction_error("SELL", 9241.0, sl=None, tp=9300.0)


def test_the_ordinary_bracket_now_passes():
    """The exact case from the report: stop just under, target just over."""
    assert not ov.bracket_direction_error("BUY", 9241.0, sl=9226.2, tp=9274.6)
    assert not ov.bracket_direction_error("SELL", 9241.0, sl=9274.6, tp=9226.2)


# ── what makes an inside-range level safe ─────────────────────────────
def test_the_watermark_is_still_stamped_when_a_leg_is_written():
    """Without it, the enforcer's range check has no reference and falls back
    to LTP only — which is safe, but the leg then loses the wick catch the
    operator asked for."""
    src = inspect.getsource(api)
    assert src.count("await _stamp_bracket_ref(p)") == 2


def test_the_range_check_only_fires_past_the_watermark():
    """This is the whole reason the gate could be removed: a level inside the
    range cannot be reached by an extreme that was already there."""
    from app.services import risk_enforcer

    src = inspect.getsource(risk_enforcer)
    assert "level > _ref_hi" in src
    assert "level < _ref_lo" in src


def test_order_placement_keeps_its_own_day_range_rule():
    """A resting LIMIT fills at the user's own price the moment the poller
    sees it; a bracket has to wait for the market to come to it. Removing the
    bracket gate must not touch the order gate."""
    from app.services import order_validator

    src = inspect.getsource(order_validator.validate)
    assert 'bool(s.get("block_inside_day_range"))' in src
    assert "INSIDE_DAY_RANGE" in src


def test_the_shared_helper_is_left_in_place():
    """`day_range_block` is still what order placement uses. Only the bracket
    wrapper stopped being called."""
    assert callable(ov.day_range_block)
    assert ov.day_range_block(D("9226"), None, D("9325"), D("9204")) is not None
