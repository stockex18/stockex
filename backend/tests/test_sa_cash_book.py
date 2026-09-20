"""The super-admin's cash book — real money, and only real money.

Operator: "cash ledger banao, tally jaisa — super admin ko total kitna paisa
aaya, security money me kitna aur normal ledger me kitna, kis admin se, aur
super admin ne kis admin ko kya diya. Ye coin ka nahi hai, ye sirf lene-dene
ka rahega."

Two streams and they must not be added into one number: security collateral
the admin lodges, and the super-admin's own cash / bank / cheque books.

Earnings are not one of them. Brokerage, the P&L share and the games result
are earned rather than received, so they post to income accounts and are read
in the trial balance — this book is what actually changed hands.
"""

from __future__ import annotations

import inspect

from app.api.v1.admin import sa_ledger


def _src() -> str:
    return inspect.getsource(sa_ledger.sa_cash_book)


def test_only_the_super_admin_may_read_it():
    assert "admin: SuperAdmin" in _src()


def test_an_earning_never_reaches_this_book():
    """Charging brokerage / P&L share / games moves no money. Counting it here
    would report income the super-admin has not been paid as cash received."""
    s = _src()
    assert "if typ in _EARN_TYPES:" in s and "continue  # earned, not received" in s
    for gone in ('"brokerage": 0.0', '"earned": 0.0', 'r["earned"]', 'd["earned"]'):
        assert gone not in s, gone


def test_only_cash_is_totalled():
    assert '("cash_in", "cash_out", "security_balance", "payable_balance")' in _src()


def test_the_three_earning_lines_are_still_named_here():
    """The names stay so this book knows exactly what to leave out."""
    assert set(sa_ledger._EARN_TYPES) == {"BROKERAGE", "PNL_SHARE", "GAMES_PNL"}
    assert sa_ledger._EARN_TYPES["BROKERAGE"] == "brokerage"
    assert sa_ledger._EARN_TYPES["PNL_SHARE"] == "pnl_share"
    assert sa_ledger._EARN_TYPES["GAMES_PNL"] == "games"


def test_money_in_and_money_out_are_not_netted():
    s = _src()
    assert '"DEPOSIT"' in s and 'r["cash_in"] += amt' in s
    assert '("WITHDRAW", "SA_TOPUP")' in s and 'r["cash_out"] += abs(amt)' in s


def test_the_books_are_a_separate_stream():
    s = _src()
    # Receipts and payments come from the super-admin's OWN books, never mixed
    # into the security totals.
    assert "LedgerBook.owner_id == admin.id" in s
    assert '"book_receipts"' in s and '"book_payments"' in s


def test_a_balance_is_never_windowed():
    # Filtering a closing balance by a date range would report a number that
    # is true of nothing.
    s = _src()
    assert s.index("AdminSecurity.find(") > s.index("if window:")
    assert "a balance has no date range" in s


def test_the_day_key_is_the_ist_calendar_day():
    s = inspect.getsource(sa_ledger._day_key)
    assert "_IST" in s and "%Y-%m-%d" in s


def test_the_window_covers_the_whole_last_day():
    s = inspect.getsource(sa_ledger._day_bound)
    assert "time(23, 59, 59, 999999)" in s
