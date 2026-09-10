"""The cash books read the opposite way from how this operator keeps them.

Their rule, in their words: "received kar raha hu, super admin ke paas paisa
aa raha hai, matlab wo credit me hona chahiye; pay karunga wo debit me hona
chahiye."

    money reaching you   ->  CREDIT
    money leaving you    ->  DEBIT

That is the party-account orientation applied to the cash side — the exact
mirror of the textbook cash book, where money arriving is a debit. It also
agrees with the party ledger they approved a moment earlier (funds given to an
admin read Dr, funds pulled back read Cr): a party account is the mirror of
its cash book, so the two flipping TOGETHER is what keeps them agreeing. Only
the cash half was still the other way round.

Stored rows keep the textbook convention. Nothing in the database is
rewritten, so this is one helper to undo — and one helper is the point: four
separate views render these columns, and four hand-written flips is how one of
them ends up disagreeing with the other three.
"""

from __future__ import annotations

import inspect
from decimal import Decimal

from app.services import coin_trial_balance as ctb
from app.services import ledger_book_service as svc


def test_money_in_is_a_credit_and_money_out_is_a_debit():
    # A stored row from an inflow: debit 100, credit 0.
    dr, cr = svc.cash_sides(100, 0)
    assert (dr, cr) == (Decimal("0"), Decimal("100"))
    # A stored row from an outflow: debit 0, credit 100.
    dr, cr = svc.cash_sides(0, 100)
    assert (dr, cr) == (Decimal("100"), Decimal("0"))


def test_it_copes_with_the_shapes_the_two_callers_pass():
    # Beanie hands Decimal128, the raw motor read hands whatever Mongo stored.
    assert svc.cash_sides(None, None) == (Decimal("0"), Decimal("0"))
    assert svc.cash_sides("40000", "0") == (Decimal("0"), Decimal("40000"))


def test_every_cash_view_goes_through_the_one_helper():
    # statement, trial balance, day book — plus the admin breakdown below.
    for fn in (svc.statement, svc.trial_balance, svc.day_book):
        assert "cash_sides(" in inspect.getsource(fn), fn.__name__


def test_the_admin_breakdown_uses_it_too():
    # This is the page the operator was looking at when they reported it.
    assert "cash_sides(" in inspect.getsource(ctb.admin_breakdown)


def test_no_cash_view_still_reads_the_stored_columns_straight():
    for fn in (svc.statement, svc.trial_balance, svc.day_book):
        src = inspect.getsource(fn)
        assert "to_decimal(e.debit)" not in src, fn.__name__
        assert "str(e.debit)" not in src, fn.__name__


def test_the_party_statement_is_deliberately_left_alone():
    # A party account is the MIRROR of its cash book. Flipping this one too
    # would put both back to disagreeing, just the other way round.
    src = inspect.getsource(svc.party_statement)
    assert "cash_sides(" not in src
    assert "dr = to_decimal(e.debit)" in src


def test_the_stored_rows_are_not_rewritten():
    # The fix is a reading, not a migration: `post()` still writes the
    # textbook convention, so this is one helper to undo.
    src = inspect.getsource(svc.post)
    assert "debit=_d128(amt) if is_inflow else _d128(0)" in src
