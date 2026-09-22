"""A delivery holding can be pledged from the position itself.

Operator: "position pe button do — user click kare, shares pledge ho jaayen,
margin free ho aur wo use kar paye." The freed margin is for NSE / BSE F&O,
which is what pledged collateral has always been for here.

The shares are not sold and the position does not move. Only the F&O margin
changes.
"""

from __future__ import annotations

import inspect

from app.api.v1.user import positions as user_positions
from app.services import pledge_service


def _src() -> str:
    return inspect.getsource(user_positions.toggle_pledge)


def test_only_the_owner_can_pledge_their_own_holding():
    s = _src()
    assert 'str(pos.user_id) != str(user.id)' in s
    assert "NotFoundError" in s


def test_only_an_open_delivery_holding_qualifies():
    s = _src()
    assert "pos.status != PositionStatus.OPEN" in s
    assert '_pl.is_equity(seg)' in s and 'prod != "CNC"' in s
    assert "PLEDGE_NOT_DELIVERY" in s


def test_a_short_cannot_be_pledged():
    """You can only pledge shares you hold."""
    s = _src()
    assert "to_decimal(pos.quantity or 0) <= 0" in s
    assert "PLEDGE_NOT_LONG" in s


def test_the_operator_switch_still_governs_it():
    s = _src()
    assert "await _pl.enabled_for(user)" in s
    assert "PLEDGE_DISABLED" in s
    assert s.index("enabled_for(user)") < s.index("Position.get(")


def test_unpledging_is_refused_while_the_margin_holds_a_position_up():
    """Releasing collateral under a live F&O position is the one thing a
    collateral system must never allow."""
    s = _src()
    assert "if not want:" in s
    assert "st.used > quantize_money(st.limit - drop)" in s
    assert "PLEDGE_IN_USE" in s


def test_the_drop_is_valued_at_the_haircut():
    s = _src()
    assert "await _pl.haircut_pct()" in s
    assert "value * await _pl.haircut_pct() / Decimal(100)" in s


def test_toggling_to_what_it_already_is_changes_nothing():
    s = _src()
    assert 'bool(getattr(pos, "is_pledge", False)) == want' in s
    assert s.index("== want") < s.index("pos.is_pledge = want")


def test_the_reply_carries_the_new_margin_so_the_screen_can_settle():
    s = _src()
    assert "_pl.summary_fields(" in s


def test_pledged_value_is_what_feeds_the_limit():
    """The button only flips `is_pledge`; the limit is re-derived from the
    positions carrying it, so there is no second number to drift."""
    s = inspect.getsource(pledge_service.compute_state)
    assert 'getattr(p, "is_pledge", False)' in s
    assert "st.limit = quantize_money(st.holdings_value * haircut" in s


def test_the_collateral_is_for_fno_only():
    """It must not become a way to buy more shares — that would make delivery
    leveraged, which is exactly what the cash-only rule exists to prevent."""
    from app.services import order_validator

    s = inspect.getsource(order_validator.validate)
    assert "_pl.is_fno(segment_type)" in s
    guard = s[s.index("_pl.is_fno(segment_type)"):]
    assert "_pl_state = await _pl.state(user.id)" in guard[:400]
