"""An expiry settlement books the house side like any other close.

Settlements never pass through the matching engine, so the admin book (the
owning admin's house result + the super admin's share) and the patti cascade
never saw them: the user's wallet moved and the admin's and super admin's
transaction history said nothing. Operator, on CL41006170's
BTC-260913-78000-P/C: "wallet se cut ho gaya hai but admin aur super admin ke
transaction history me dikh nahi raha".
"""

from __future__ import annotations

import inspect

from app.services import position_service


def _src() -> str:
    return inspect.getsource(position_service.settle_expired_position)


def test_the_admin_book_runs_on_an_expiry_close():
    s = _src()
    assert "admin_book_service.distribute_on_close(" in s


def test_the_patti_cascade_runs_on_an_expiry_close():
    s = _src()
    assert "patti_service.distribute_patti_on_close(" in s


def test_it_books_against_the_closing_trade_it_just_wrote():
    # The admin book is idempotent per trade id; keying it on the settlement's
    # own closing trade is what makes a re-run a no-op instead of a double book.
    s = _src()
    assert s.index("_close_trade = await _Trade(") < s.index("distribute_on_close(")
    assert "str(_close_trade.id)" in s[s.index("distribute_on_close("):]


def test_it_books_the_realized_pnl_with_no_brokerage():
    s = _src()
    call = s[s.index("distribute_on_close("): s.index("distribute_on_close(") + 400]
    assert "_u, realized, ZERO" in call  # signed realized P&L, no brokerage at expiry


def test_a_failed_hook_cannot_stop_the_settlement():
    s = _src()
    hook = s[s.index("2c) The house side of the close"): s.index("3) Close the position for good")]
    assert "except Exception" in hook
    assert "expiry_admin_book_hook_failed" in hook
