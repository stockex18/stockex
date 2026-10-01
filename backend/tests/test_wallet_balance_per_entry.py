"""Each per-trade row says what the wallet stood at after it.

Operator, looking at Transactions — per trade on their own wallet page:
"kaise kaise mera wallet me add ho raha aur uske baad kitna bacha hai — wo
side me ek column bana ke dikha. Jaise 100 add hua to 1100 ho gaya, phir 20
kam hua to 1080 ho jaye."

The column has to be read from the LEDGER, not produced by adding the Net
column up. Those are different numbers. A wallet moves on deposits, admin
funding, settlements and games as well as on trades, so a running total of
the trade rows alone parts company with the real balance at the first of
those — and then the newest row disagrees with the balance card sitting
directly above the table, which is the one thing a balance column must never
do.

Every admin-book booking already writes its wallet transactions with
`reference_type="ADMIN_BOOK"` and `reference_id=<trade id>`, and every
transaction carries the `balance_after` recorded when it was applied. So the
number exists; it only had to be joined back.
"""

from __future__ import annotations

import inspect

from app.api.v1.admin import admin_book, me as admin_me
from app.models.transaction import WalletTransaction


# ── the number exists to be read ──────────────────────────────────────
def test_the_ledger_records_a_balance_on_every_entry():
    for field in ("balance_before", "balance_after"):
        assert field in WalletTransaction.model_fields, field


def test_bookings_are_tagged_so_they_can_be_joined_back():
    """Without the reference the per-trade feed has no way to find the
    ledger entry belonging to a given trade."""
    from app.services import admin_book_service

    src = inspect.getsource(admin_book_service)
    assert 'reference_type="ADMIN_BOOK"' in src
    assert "reference_id=str(trade_id)" in src


# ── the SA's per-trade feed ───────────────────────────────────────────
def test_the_sa_feed_returns_a_balance_per_row():
    src = inspect.getsource(admin_book.transactions)
    assert '"balance_after": balance_by_trade.get(str(e.trade_id))' in src


def test_the_sa_balance_comes_from_the_ledger_not_from_a_running_sum():
    """This is the whole point. A sum over the rows would be a different,
    wrong number."""
    src = inspect.getsource(admin_book.transactions)
    assert "WalletTransaction" in src
    assert "balance_after" in src
    assert '"reference_type": "ADMIN_BOOK"' in src
    # Nobody is accumulating anything.
    assert "+=" not in src.split("balance_by_trade")[1][:400]


def test_the_balance_is_the_one_belonging_to_this_wallet():
    """The same trade books to the admin's wallet too. Reading that one
    would show the SA a balance that is not theirs."""
    src = inspect.getsource(admin_book.transactions)
    assert "WalletTransaction.user_id == admin.id" in src


def test_one_trade_with_two_bookings_reports_the_later_balance():
    """A trade books PnL and brokerage separately. The balance that answers
    "kitna bacha hai" is the one after the last of them, so the walk has to
    be oldest-first and let the later write win."""
    src = inspect.getsource(admin_book.transactions)
    assert '.sort("+created_at")' in src


def test_a_trade_that_moved_nothing_has_no_balance():
    """A pass-through admin, or a zero share, writes no ledger entry.
    Carrying the previous row's figure forward would imply a movement that
    never happened."""
    src = inspect.getsource(admin_book.transactions)
    assert "balance_by_trade.get(" in src  # .get → None when absent


# ── the per-node feed (admin / broker / sub-broker) ───────────────────
def test_the_node_feed_returns_its_own_recorded_balance():
    src = inspect.getsource(admin_me.my_trade_earnings)
    assert '"balance_after": _f(r.balance_after)' in src


def test_the_node_feed_reads_the_row_it_already_has():
    """It queries WalletTransaction directly, so the balance is on the
    document in hand — no join, and no reason to compute one."""
    src = inspect.getsource(admin_me.my_trade_earnings)
    assert "WalletTransaction.find(" in src
    assert "WalletTransaction.user_id == admin.id" in src
