"""Coins and ledger lines are separate records now.

Operator: "coin ko super admin kam aur zyada kare bas admin ka, aur ledger ke
liye entry alag se add karega. Same cheez se coin kam-zyada aur ledger me
entry nahi chahiye — dono alag-alag hoga."

Adding an admin's coins used to write a ledger line as a side effect, which
tied together two things that are not the same event:

    coins    the platform's internal balance for that admin
    ledger   real money that arrived by cheque, UPI or bank

They happen at different times, in different amounts, and either can happen
without the other — an admin can pay 5 lakh by cheque today against coins
given last week. One click could not express that, so it forced the two to
agree and both ended up wrong.

So `add_funds` / `deduct_funds` move coins and nothing else, and the super
admin records the money by hand on Ledgers -> Admin entry.
"""

from __future__ import annotations

import inspect

from app.services import admin_fund_service as fund
from app.services import ledger_book_service as ledger


def test_adding_coins_writes_no_ledger_line():
    src = inspect.getsource(fund.add_funds)
    assert "ledger_book_service" not in src
    assert "NO ledger line here" in src


def test_deducting_coins_writes_no_ledger_line():
    src = inspect.getsource(fund.deduct_funds)
    assert "ledger_book_service" not in src


def test_the_coin_service_no_longer_imports_the_ledger_at_all():
    # A leftover import is how the coupling creeps back one call at a time.
    assert "ledger_book_service" not in inspect.getsource(fund)


# ── the hand-written side ───────────────────────────────────────────────────

def test_a_party_entry_needs_a_direction_an_admin_a_ledger_and_an_amount():
    src = inspect.getsource(ledger.post_party_entry)
    assert 'if d not in ("RECEIVED", "PAID")' in src
    assert "Pick the admin this entry belongs to" in src
    assert "Pick which ledger the money moved through" in src
    assert "Enter an amount" in src


def test_received_debits_and_paid_credits_the_chosen_ledger():
    # Money arriving in a cash/UPI/bank book is a debit there — ordinary
    # accounting, and the same convention the auto-posted rows used.
    src = inspect.getsource(ledger.post_party_entry)
    assert 'is_inflow=(d == "RECEIVED")' in src


def test_the_entry_is_filed_under_that_admin():
    # `particulars` is what the party statement groups on; without it the line
    # lands in the cash book and nowhere else.
    src = inspect.getsource(ledger.post_party_entry)
    assert "particulars=code" in src


def test_two_identical_payments_on_one_day_both_land():
    # `post()` dedups on source_id to stop an auto-posted movement being
    # written twice. A real second cheque for the same amount must not be
    # swallowed by that, so a typed line carries a unique id.
    src = inspect.getsource(ledger.post_party_entry)
    assert "PydanticObjectId()" in src


def test_a_typed_line_can_be_deleted_again():
    # Auto-posted lines are protected because deleting one would leave the
    # money movement it mirrors unaccounted. A typed line has no such twin.
    assert "is_auto=False" in inspect.getsource(ledger.post_party_entry)
    assert "is_auto: bool = True" in inspect.getsource(ledger.post)
    assert "if e.is_auto:" in inspect.getsource(ledger.delete_entry)


def test_an_unknown_admin_code_is_refused():
    src = inspect.getsource(ledger.post_party_entry)
    assert "No admin with code" in src
