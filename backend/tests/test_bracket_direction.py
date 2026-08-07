"""Wrong-side SL/TP guard — a leg on the profitable side is "already hit" and
fills at an untraded price (fake P&L). See order_validator.bracket_direction_error.

Plain asserts, no fixtures. Run: pytest -q tests/test_bracket_direction.py
"""

from app.services.order_validator import bracket_direction_error as err


def test_the_real_incident_short_sl_below_market():
    # SELL SILVERM @ 2,32,400; SL 1,32,680 is BELOW market → impossible short SL.
    assert err("SELL", 232400, sl=132680) is not None


def test_valid_short_passes():
    assert err("SELL", 232400, sl=232500, tp=232000) is None


def test_valid_long_passes():
    assert err("BUY", 232400, sl=232000, tp=232900) is None


def test_every_wrong_side_combo_flags():
    # Long: SL must be < ref, TP must be > ref.
    assert err("BUY", 100, sl=120) is not None   # SL above → wrong
    assert err("BUY", 100, tp=90) is not None    # TP below → wrong
    # Short: SL must be > ref, TP must be < ref.
    assert err("SELL", 100, sl=90) is not None    # SL below → wrong
    assert err("SELL", 100, tp=120) is not None   # TP above → wrong


def test_fail_open_when_no_mark():
    # ref <= 0 (feed momentarily unavailable) → never block a trade.
    assert err("BUY", 0, sl=120) is None
    assert err("SELL", 0, tp=120) is None


def test_boundary_equal_is_rejected():
    # A leg exactly AT the market is also instantly eligible → reject.
    assert err("BUY", 100, sl=100) is not None
    assert err("SELL", 100, sl=100) is not None


def test_clearing_legs_are_ignored():
    # None / 0 / "" legs are "clear", not a wrong-side value.
    assert err("BUY", 100, sl=None, tp=None) is None
    assert err("SELL", 100, sl=0, tp="") is None
