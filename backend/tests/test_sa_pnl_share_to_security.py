"""Where each thing the super admin earns off an admin is settled.

The operator's rule, given 24 Sept: "pnl main ledger se kaam hoga aur security
money se brokerage aur game ka paisa." Two pockets, and which one answers for
what is not a detail -- it decides whether an admin's collateral draws down.

    P&L share  -> the MAIN ledger. An ordinary running account with the
                  admin, provable on the trial balance. It never touches the
                  collateral, whether the admin lodged any or not.
    brokerage  -> the collateral when there is some, the wallet when there is
                  not. Either way the income is booked, because brokerage
                  earned is income whichever pocket settled it -- leaving that
                  out is why Brokerage Income read zero for days while the
                  super admin's wallet filled up.
    games      -> the collateral, unchanged.

A PASS-THROUGH admin follows the same two pockets, and the operator settled
the direction against their own rows: "es security money se brokerage aaya hai
usko kam kar de; ledger se jo pnl aaya hai super admin ka -- profit hua to kam
kar, loss hua to add kar." So the admin bears their own book. A house LOSS is
debited to them and their balance goes UP; a house PROFIT is credited and it
comes down.

That P&L leg is contra'd to the super admin's coins rather than to an income
account, because the operator's direction needs a debit on a loss and a credit
on a profit -- pairing that with income would report the house earning on the
days it paid out.

This file used to pin the P&L share against the collateral. It was right for
its day; the operator has since moved that leg.
"""

from __future__ import annotations

import inspect

from app.models.admin_security import SecurityEntryType
from app.services import admin_book_service, admin_security_service as sec
from app.services import ledger_book_service as lbs

_SRC = inspect.getsource(admin_book_service.distribute_on_close)

# `distribute_on_close` splits in two, and each half has its own
# `sa_pnl != ZERO` -- anchor on the split by name or the assertions below read
# whichever branch happens to come first.
_PASS = _SRC[_SRC.index("PASS-THROUGH admin") : _SRC.index("NORMAL / FIXED admin")]
_NORMAL = _SRC[_SRC.index("NORMAL / FIXED admin") :]


# -- the normal / fixed admin, who is charged ------------------------------


def test_the_pnl_share_goes_to_the_main_ledger():
    i = _NORMAL.index("sa_pnl != ZERO")
    leg = _NORMAL[i : _NORMAL.index("sa_bkg != ZERO", i)]
    assert 'kind="PNL_SHARE"' in leg
    assert "post_earning(" in leg


def test_the_pnl_share_never_touches_the_collateral():
    i = _NORMAL.index("sa_pnl != ZERO")
    leg = _NORMAL[i : _NORMAL.index("sa_bkg != ZERO", i)]
    assert "charge_pnl_share" not in leg
    assert "admin_security_service" not in leg
    # Gone, rather than left lying around for someone to call again.
    assert not hasattr(sec, "charge_pnl_share")


def test_both_wallets_still_move_on_the_pnl_share():
    # Only WHERE it is recorded changed. The coins move exactly as before:
    # the admin is debited, the super admin credited.
    assert _SRC.count("TransactionType.SA_PNL_SHARE") >= 2


def test_brokerage_still_draws_the_collateral_first():
    leg = _NORMAL[_NORMAL.index("sa_bkg != ZERO") :]
    a = leg.index("charge_brokerage(")
    b = leg.index("if not charged:", a)
    c = leg.index("TransactionType.SA_BROKERAGE_SHARE", b)
    assert a < b < c, "collateral first, wallet only as the fallback"


def test_brokerage_is_booked_as_income_even_without_collateral():
    i = _NORMAL.index("sa_bkg != ZERO")
    fallback = _NORMAL[_NORMAL.index("if not charged:", i) :]
    assert 'kind="BROKERAGE"' in fallback
    assert "post_earning(" in fallback


# -- the pass-through admin, who earns nothing and so is charged nothing ----


def test_pass_through_brokerage_comes_out_of_the_security_money():
    leg = _PASS[_PASS.index("sa_bkg != ZERO") :]
    assert "charge_brokerage(" in leg
    # Only when they lodged none does it fall to the house's own account.
    assert "post_house_earning(" in leg


def test_pass_through_pnl_lands_on_the_admins_own_ledger():
    leg = _PASS[_PASS.index("sa_pnl != ZERO") : _PASS.index("sa_bkg != ZERO")]
    assert "post_admin_pnl_share(" in leg
    assert "charge_" not in leg


def test_the_admin_pnl_voucher_runs_the_operators_way():
    # Their direction, given against their own rows: "if super admin profit
    # hua hai to usse kam kar, loss hua hai to add kar." A house LOSS debits
    # the admin and the balance goes UP.
    src = inspect.getsource(lbs.post_admin_pnl_share)
    assert "house_profit = amt > ZERO" in src
    assert '"debit": 0 if house_profit else mag' in src
    assert '"credit": mag if house_profit else 0' in src


def test_only_the_admins_own_leg_carries_their_code():
    # "By admin" matches on the code. Both legs carrying it put both on that
    # statement, where they cancelled to nothing.
    src = inspect.getsource(lbs.post_admin_pnl_share)
    assert src.count('str(admin.user_code or "")') == 1
    assert '"particulars": party.name' in src


def test_the_house_voucher_uses_its_own_contra_not_the_cash_book():
    # Cash is counted against what is in the drawer. Coins earned off a book
    # never went near it, so they get their own account.
    assert lbs._HOUSE_CONTRA == "Coins in hand"
    src = inspect.getsource(lbs.post_house_earning)
    assert "house_contra_book(" in src
    assert "party_book(" not in src


def test_the_house_voucher_runs_both_ways():
    # A user WINNING makes the amount negative -- the house pays, and the same
    # voucher has to reverse rather than refuse.
    src = inspect.getsource(lbs.post_house_earning)
    assert "earned = amt > ZERO" in src
    assert "mag if earned else 0" in src
    assert "0 if earned else mag" in src


def test_the_security_statement_still_names_the_old_rows():
    # Historical PNL_SHARE rows predate the move and must keep reading right.
    assert sec._ENTRY_LABEL[SecurityEntryType.PNL_SHARE] == "SA P&L share"
    assert sec._TYPE_FIXED[SecurityEntryType.PNL_SHARE] == "P&L share"
