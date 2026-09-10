"""The party ledger read as the opposite of the real exposure.

Operator, on their own rows in Shivam's ledger:

    Funds from SADM...   Cr 2,000     should be Dr
    Paid to ADM72004302  Dr 1,999     should be Cr

The books record only the CASH leg of a funding, never the coin leg.
"Received" takes the admin's money AND hands them that many coins; only the
first half ever reaches a ledger. Mirroring that single leg made funding an
admin show as a credit — as though the platform owed them — when the coins had
gone the other way and they owed the platform.

So the party statement now follows the cash book instead of mirroring it. The
operator chose this against a preview of these exact rows, and chose it for
the whole party ledger, which carries the security rows along: a security you
hold now reads Dr too.

The cash books are deliberately NOT touched. Money arriving in Cash / UPI / a
bank account is a debit there, which is ordinary accounting and what their
printed statements have to keep saying.
"""

from __future__ import annotations

import inspect

from app.services import ledger_book_service as svc

PARTY = inspect.getsource(svc.party_statement)
CASH = inspect.getsource(svc.statement)


def test_funding_an_admin_reads_as_a_debit():
    # dr comes off the book's DEBIT, so a cash-in funding row lands in Dr.
    assert "dr = to_decimal(e.debit)" in PARTY
    assert "cr = to_decimal(e.credit)" in PARTY


def test_the_mirror_is_gone():
    assert "to_decimal(e.credit)\n        cr" not in PARTY
    assert "mirrored" not in PARTY.lower().replace("mirror it", "")


def test_the_opening_balance_moves_the_same_way_as_the_rows():
    # An opening balance computed the other way would make every dated
    # statement disagree with the same statement run without dates.
    assert "opening += to_decimal(e.debit) - to_decimal(e.credit)" in PARTY


def test_the_running_balance_still_nets_dr_minus_cr():
    assert "running += dr - cr" in PARTY


def test_the_cash_books_flip_the_other_way():
    """They were left alone at first, and that left the pair disagreeing.

    A party account is the MIRROR of its cash book. Once the party side reads
    "funds given to an admin are a debit", the cash side has to read the other
    way for the two to agree — which is also the operator's own rule for it:
    money reaching them is a credit, money leaving is a debit.
    """
    assert "cash_sides(" in CASH
    assert "dr = to_decimal(e.debit)" not in CASH


def test_the_posting_convention_itself_did_not_move():
    # `post()` is what both views read. Changing it would rewrite history for
    # every book at once; the fix belongs in the party VIEW only.
    src = inspect.getsource(svc.post)
    assert "debit=_d128(amt) if is_inflow else _d128(0)" in src
    assert "credit=_d128(0) if is_inflow else _d128(amt)" in src
