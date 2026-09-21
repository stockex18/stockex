"""Where the super-admin's money came from, admin by admin.

Operator: "row pe click karne par pata chale ki is admin se P&L share me kitna
aaya, brokerage me kitna, games me kitna — kaunse section se kitna mila."

Read off the security ledger — the same rows the income accounts are posted
from — so this breakdown can never disagree with the trial balance.
"""

from __future__ import annotations

import inspect

from app.api.v1.admin import sa_ledger


def _src() -> str:
    return inspect.getsource(sa_ledger.sa_admin_earnings)


def test_only_the_super_admin_may_read_it():
    assert "admin: SuperAdmin" in _src()


def test_it_splits_the_three_streams_and_totals_them():
    s = _src()
    assert '{"brokerage": 0.0, "pnl_share": 0.0, "games": 0.0, "earned": 0.0}' in s
    assert "totals[key] += earned" in s and 'totals["earned"] += earned' in s


def test_the_sign_is_flipped_the_same_way_the_cash_book_flips_it():
    """`amount` is signed as it hit the ADMIN's collateral, so the
    super-admin's gain is its negative. Getting this backwards reports every
    earning as a loss."""
    s = _src()
    assert "earned = -_f(e.get(\"amount\"))" in s
    assert "_EARN_TYPES.get(typ)" in s


def test_nothing_but_an_earning_gets_in():
    """Deposits and withdrawals are cash, not income — they belong to the cash
    book, and counting them here would double them."""
    s = _src()
    assert "if key is None:\n            continue" in s


def test_games_shows_both_directions():
    """Netting a 1L payout against 1L collected reads as nothing happened."""
    s = _src()
    assert '{"collected": 0.0, "paid_out": 0.0}' in s
    assert 'games["collected"] += earned' in s
    assert 'games["paid_out"] += -earned' in s


def test_a_balance_is_never_windowed():
    s = _src()
    assert "a balance has no date range" in s
    assert s.index("AdminSecurity.find_one(") > s.index('match["created_at"] = window')


def test_it_refuses_a_target_that_is_not_an_admin():
    s = _src()
    assert "u.role not in (UserRole.ADMIN, UserRole.BROKER)" in s
    assert "NotFoundError" in s


def test_it_carries_the_arrangement_so_the_reader_knows_the_terms():
    assert '"admin_type": admin_type(u)' in _src()


def test_the_window_is_the_same_one_the_cash_book_uses():
    s = _src()
    assert "_day_bound(date_from, False)" in s and "_day_bound(date_to, True)" in s
    assert "_day_key(" in s
