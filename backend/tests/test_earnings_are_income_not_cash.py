"""What the super-admin EARNS is income, and it never reaches the cash book.

The operator's admin put it plainly: brokerage, the P&L share and the games
result must show in the TRIAL BALANCE so a super-admin and an admin can
reconcile against the same figure — and must NOT show in the cash book,
because charging them moves no money.
"""

from __future__ import annotations

import inspect

from app.api.v1.admin import sa_ledger
from app.models.admin_security import SecurityEntryType
from app.models.ledger_book import AccountType
from app.services import admin_security_service, ledger_book_service


def test_there_is_an_income_account_type():
    assert AccountType.INCOME == "INCOME"


def test_every_earning_kind_has_an_income_account():
    assert set(ledger_book_service.EARNING_BOOKS) == {
        "BROKERAGE", "PNL_SHARE", "GAMES_PNL",
    }
    # Each maps to a distinct account, or two streams would pile into one.
    assert len(set(ledger_book_service.EARNING_BOOKS.values())) == 3


def test_the_security_ledger_books_exactly_those_three():
    assert admin_security_service._EARNING_TYPES == {
        SecurityEntryType.BROKERAGE,
        SecurityEntryType.PNL_SHARE,
        SecurityEntryType.GAMES_PNL,
    }


def test_an_earning_is_posted_as_a_voucher_off_the_single_funnel():
    s = inspect.getsource(admin_security_service._apply)
    assert "if entry_type in _EARNING_TYPES:" in s
    assert "post_earning(" in s
    # The sign flips: collateral consumed is what the super-admin earned.
    assert "amount=-quantize_money(security_delta)" in s
    # And it runs after the entry is written, so the ledger is the record even
    # if the bookkeeping leg fails.
    assert s.index("AdminSecurityEntry(") < s.index("post_earning(")


def test_the_earning_voucher_debits_the_admin_and_credits_income():
    s = inspect.getsource(ledger_book_service.post_earning)
    assert "earned = amt > ZERO" in s
    assert "party_book(" in s and "income_book(" in s
    assert "post_voucher(" in s, "two legs, or the trial balance cannot prove it"
    assert "source_type=\"ADMIN_EARNING\"" in s


def test_a_house_loss_runs_the_voucher_the_other_way():
    """A player winning is a negative earning; the same voucher must reverse
    rather than post a negative debit, which no ledger accepts."""
    s = inspect.getsource(ledger_book_service.post_earning)
    assert '"debit": mag if earned else 0, "credit": 0 if earned else mag' in s


def test_cash_movements_now_name_the_party_they_moved_with():
    """Without the contra leg the admin's account holds only half the story,
    and nothing reconciles.

    Security receipts used to be checked here too. They no longer reach the
    cash books at all — collateral has its own ledger, and mirroring it here
    made an admin's account read 20L when 10L of it was security (24 Sept).
    """
    assert not hasattr(admin_security_service, "_to_ledger")
    assert "party_user_id=user.id" in inspect.getsource(
        ledger_book_service.post_party_entry
    )
    post = inspect.getsource(ledger_book_service.post)
    assert "pbook = await party_book(" in post
    assert "voucher_id=vid" in post


def test_the_cash_book_drops_every_earning():
    s = inspect.getsource(sa_ledger.sa_cash_book)
    assert "if typ in _EARN_TYPES:\n            continue" in s
    for gone in ('"brokerage": 0.0', '"earned": 0.0', 'd["earned"]', 'r["earned"]'):
        assert gone not in s, gone
    # Cash itself must still be totalled.
    assert '("cash_in", "cash_out", "security_balance", "payable_balance")' in s


def test_the_earning_post_can_never_undo_the_earning():
    s = inspect.getsource(ledger_book_service.post_earning)
    assert "except Exception" in s and "return False" in s
