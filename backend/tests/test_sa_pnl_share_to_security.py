"""Where each thing the super admin earns off an admin is settled.

The operator's rule, given 24 Sept: "pnl main ledger se kaam hoga aur security
money se brokerage aur game ka paisa." Two pockets, and which one answers for
what is not a detail — it decides whether an admin's collateral draws down.

    P&L share  -> the MAIN ledger. An ordinary running account with the
                  admin, provable on the trial balance. It never touches the
                  collateral, whether the admin lodged any or not.
    brokerage  -> the collateral when there is some, the wallet when there is
                  not. Either way the income is booked, because brokerage
                  earned is income whichever pocket settled it -- leaving that
                  out is why Brokerage Income read zero for days while the
                  super admin's wallet filled up.
    games      -> the collateral, unchanged.

This file used to pin the opposite rule for the P&L share. It was right for
its day; the operator has since moved that leg.
"""

from __future__ import annotations

import inspect

from app.models.admin_security import SecurityEntryType
from app.services import admin_book_service, admin_security_service as sec

_SRC = inspect.getsource(admin_book_service.distribute_on_close)

# `distribute_on_close` splits in two: a pass-through admin, whose own wallet
# is never touched, and a normal / fixed one, who is charged. They each have
# their own `sa_pnl != ZERO`, so anchor on the split or the assertions below
# read the wrong branch.
_NORMAL = _SRC[_SRC.index("NORMAL / FIXED admin") :]


def test_the_pnl_share_goes_to_the_main_ledger():
    i = _NORMAL.index("sa_pnl != ZERO")
    leg = _NORMAL[i : _NORMAL.index("sa_bkg != ZERO", i)]
    assert 'kind="PNL_SHARE"' in leg
    assert "post_earning(" in leg


def test_the_pnl_share_never_touches_the_collateral():
    # The whole point of the move: no security call anywhere on that leg, and
    # the function that used to make one is gone rather than left to be found.
    i = _NORMAL.index("sa_pnl != ZERO")
    leg = _NORMAL[i : _NORMAL.index("sa_bkg != ZERO", i)]
    assert "charge_pnl_share" not in leg
    assert "admin_security_service" not in leg
    assert not hasattr(sec, "charge_pnl_share")


def test_both_wallets_still_move_on_the_pnl_share():
    # Only WHERE it is recorded changed. The coins move exactly as before:
    # the admin is debited, the super admin credited.
    assert _SRC.count("TransactionType.SA_PNL_SHARE") >= 2


def test_brokerage_still_draws_the_collateral_first():
    i = _NORMAL.index("sa_bkg != ZERO")
    leg = _NORMAL[i:]
    a = leg.index("charge_brokerage(")
    b = leg.index("if not charged:", a)
    c = leg.index("TransactionType.SA_BROKERAGE_SHARE", b)
    assert a < b < c, "collateral first, wallet only as the fallback"


def test_brokerage_is_booked_as_income_even_without_collateral():
    i = _NORMAL.index("sa_bkg != ZERO")
    fallback = _NORMAL[_NORMAL.index("if not charged:", i) :]
    assert 'kind="BROKERAGE"' in fallback
    assert "post_earning(" in fallback


def test_the_security_statement_still_names_the_old_rows():
    # Historical PNL_SHARE rows predate the move and must keep reading right.
    assert sec._ENTRY_LABEL[SecurityEntryType.PNL_SHARE] == "SA P&L share"
    assert sec._TYPE_FIXED[SecurityEntryType.PNL_SHARE] == "P&L share"
