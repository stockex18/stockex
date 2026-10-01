"""A stop-loss lives inside the day's range. A target does not.

Reported: SL/TP would not save. Reproduced on a live position —

    DIVISLAB26SEPFUT   ltp 9241.00   day 9204.00 - 9325.00
    stop loss 9226.20  ->  "is inside today's range"

Every stop-loss is that shape: just under the price, and therefore inside the
band the instrument has already traded through today. A gate covering BOTH
legs made brackets impossible to set on any ordinary day, so it was removed
whole.

Removing it whole went too far the other way. Operator, 30 Sept: "stop loss
high or low ke bich mai lag jani chahiye fresh or position lene kai baad -- or
target nahi lagni chahiye." The legs are not alike:

  * A STOP inside the range fires and closes the trader at a LOSS. That is
    their own call, and refusing it leaves a position unprotected once the
    day's range has gone wide.
  * A TARGET inside the range books a PROFIT at a price the market has
    already left — the same exploit the placement gate refuses a resting
    LIMIT for.

So the gate is back on both bracket paths, checking the target only. What
makes an inside-range STOP safe is unchanged: `bracket_ref_high` /
`bracket_ref_low` mean the enforcer's range check only fires once the day
moves BEYOND where it stood when the leg was set.

These pin the split. Relaxing the stop is only safe while the target stays
held back; the day they drift apart the rule protects nothing.
"""

from __future__ import annotations

import inspect

from decimal import Decimal as D

from app.api.v1.user import positions as api
from app.services import order_validator as ov


# ── the gate is back, on both bracket paths ───────────────────────────
def test_both_bracket_endpoints_apply_the_day_range_gate():
    """A leg set from the Active list and the same leg set from the Position
    list must be judged identically — otherwise the rule is one tab wide."""
    for fn in (api.update_sl_tp, api.update_active_trade_sl_tp):
        assert "day_range_block_for_bracket" in inspect.getsource(fn), fn.__name__


def test_the_gate_runs_after_the_direction_check_on_both_paths():
    """Wrong-side is the more basic error and gives the clearer message, so
    it should be the one the trader sees first."""
    for fn in (api.update_sl_tp, api.update_active_trade_sl_tp):
        src = inspect.getsource(fn)
        assert src.index("bracket_direction_error") < src.index(
            "day_range_block_for_bracket"
        ), fn.__name__


def test_only_the_target_is_held_back():
    """The whole point of the split. If the stop is checked too, every
    ordinary bracket is refused again and we are back to the bug."""
    src = inspect.getsource(ov.day_range_block_for_bracket)
    loop = src[src.index("for label, raw in"):]
    head = loop[: loop.index("\n")]
    assert '"Target"' in head
    assert '"Stop' not in head and "sl" not in head.split("(")[-1]


def test_the_reason_is_written_where_someone_would_undo_it():
    """Both halves have been wrong before — the gate on everything, then the
    gate on nothing. Whoever touches this next needs the history."""
    src = inspect.getsource(api.update_sl_tp)
    assert "TARGET ONLY" in src
    assert "bracket_ref_high" in src


def test_the_gate_reads_the_admins_own_toggle():
    """It must not be a second, separate rule — the admin's
    `block_inside_day_range` switch is what turns it on."""
    src = inspect.getsource(ov.day_range_block_for_bracket)
    assert 'block_inside_day_range' in src
    assert "get_effective_settings" in src


def test_the_gate_fails_open():
    """An unresolvable range or a settings hiccup must never leave a trader
    unable to move a stop off a losing position."""
    src = inspect.getsource(ov.day_range_block_for_bracket)
    assert "except Exception" in src
    assert "return None" in src


# ── the guard that still matters most ─────────────────────────────────
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


def test_the_ordinary_bracket_still_passes_the_direction_check():
    """The exact case from the report: stop just under, target just over."""
    assert not ov.bracket_direction_error("BUY", 9241.0, sl=9226.2, tp=9274.6)
    assert not ov.bracket_direction_error("SELL", 9241.0, sl=9274.6, tp=9226.2)


# ── what makes an inside-range STOP safe ──────────────────────────────
def test_the_watermark_is_still_stamped_when_a_leg_is_written():
    """Without it, the enforcer's range check has no reference and falls back
    to LTP only — which is safe, but the leg then loses the wick catch the
    operator asked for."""
    src = inspect.getsource(api)
    # The Active tab writes to the FILL now, so the stamp takes whatever that
    # path wrote to. Two write sites, two stamps, is the invariant.
    assert src.count("await _stamp_bracket_ref(") == 2


def test_the_range_check_only_fires_past_the_watermark():
    """This is why a stop may sit inside the range at all: a level inside it
    cannot be reached by an extreme that was already there."""
    from app.services import risk_enforcer

    src = inspect.getsource(risk_enforcer)
    assert "level > _ref_hi" in src
    assert "level < _ref_lo" in src


def test_order_placement_keeps_its_own_day_range_rule():
    """A resting LIMIT fills at the user's own price the moment the poller
    sees it; a bracket has to wait for the market to come to it."""
    from app.services import order_validator

    src = inspect.getsource(order_validator.validate)
    assert 'bool(s.get("block_inside_day_range"))' in src
    assert "INSIDE_DAY_RANGE" in src


def test_the_shared_comparison_is_the_same_one_placement_uses():
    """`day_range_block` is what order placement uses, and the bracket
    wrapper calls it too — so the two can never disagree about what "inside
    the range" means."""
    assert callable(ov.day_range_block)
    assert ov.day_range_block(D("9226"), None, D("9325"), D("9204")) is not None
    assert "day_range_block(" in inspect.getsource(ov.day_range_block_for_bracket)
