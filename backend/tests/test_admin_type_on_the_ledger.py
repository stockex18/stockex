"""Every admin wears which of the five arrangements they are on.

Operator: "ledger me admin ke side me likha rahe ki ye kaunse type ka admin
hai." The five, in their words:

  1. No-brokerage admin (office admin)
  2. Fixed brokerage to the admin, all P&L handled by the admin
  3. Fixed brokerage to the admin, 100% P&L for the super-admin
  4. Patti sharing P&L, fixed brokerage to the admin
  5. Patti sharing, no fixed brokerage

It is derived, never stored: the same fields the money is split by decide the
label, so the two can never disagree.
"""

from __future__ import annotations

import inspect

from app.api.v1.admin import sa_ledger
from app.services.admin_book_service import ADMIN_TYPE_NAMES, admin_type


class _Admin:
    def __init__(self, **kw):
        self.no_self_brokerage = False
        self.is_fixed_brokerage = False
        self.pnl_share_pct = None
        self.admin_brokerage_share_pct = None
        self.__dict__.update(kw)


def test_the_office_admin_keeps_nothing():
    t = admin_type(_Admin(no_self_brokerage=True))
    assert t["n"] == 1
    # Even with a P&L percentage set, pass-through wins — that is what the
    # money path does (`no_self` forces the share to 100).
    assert admin_type(_Admin(no_self_brokerage=True, pnl_share_pct=30))["n"] == 1


def test_fixed_brokerage_with_the_book_left_to_the_admin():
    assert admin_type(_Admin(is_fixed_brokerage=True, pnl_share_pct=0))["n"] == 2


def test_fixed_brokerage_with_the_whole_book_to_the_super_admin():
    assert admin_type(_Admin(is_fixed_brokerage=True, pnl_share_pct=100))["n"] == 3


def test_fixed_brokerage_with_the_book_on_patti():
    t = admin_type(_Admin(is_fixed_brokerage=True, pnl_share_pct=40))
    assert t["n"] == 4
    assert "40%" in t["label"], "the share is the whole point of a patti"


def test_patti_with_no_fixed_brokerage():
    t = admin_type(_Admin(pnl_share_pct=30, admin_brokerage_share_pct=25))
    assert t["n"] == 5
    assert "30%" in t["label"]
    assert "25%" in t["detail"], "brokerage split belongs in the reason"


def test_a_legacy_admin_still_lands_somewhere():
    """Nothing configured must not produce a blank badge — it is a patti admin
    on zero, which is exactly how the money path reads it."""
    assert admin_type(_Admin())["n"] == 5


def test_a_missing_admin_is_not_given_a_type():
    assert admin_type(None)["n"] == 0


def test_all_five_are_named():
    assert set(ADMIN_TYPE_NAMES) == {1, 2, 3, 4, 5}
    assert len(set(ADMIN_TYPE_NAMES.values())) == 5


def test_the_ledger_row_carries_it():
    s = inspect.getsource(sa_ledger.sa_cash_book)
    assert '"admin_type": admin_type(a)' in s


def test_the_label_trims_the_noise_off_a_percentage():
    from app.services.admin_book_service import _pct_str

    assert _pct_str(40) == "40"
    assert _pct_str("12.50") == "12.5"
    assert _pct_str(0) == "0"


def test_the_coin_sheet_names_an_admin_by_type_not_by_id():
    """Operator: "admin id mat likho, Type 2 / Type 1 likho.\""""
    from app.services import coin_trial_balance

    s = inspect.getsource(coin_trial_balance.build)
    assert 'f"{label} (Type {t[\'n\']})"' in s
    assert '"no_self_brokerage": 1' in s, "the type needs its fields fetched"
    # Keyed by id so two admins sharing a name and a type keep separate rows.
    assert "per_admin[u[\"_id\"]]" in s


def test_a_plain_mapping_is_classified_too():
    """The coin sheet reads users straight off motor, not through the ODM."""
    t = admin_type({"is_fixed_brokerage": True, "pnl_share_pct": 100})
    assert t["n"] == 3
