"""Double entry — the rule the whole accounting side rests on.

The super-admin keeps every admin's books here: cash, bank, third-party and
expense accounts, and a trial balance over the lot.

Before this, an entry landed in ONE book with a debit or a credit, and
"Particulars" was free text naming a contra account nobody could follow. Under
that model a trial balance can never be produced — nothing guarantees that
total debits equal total credits, so "balanced" would be a claim rather than a
proof.

A voucher now carries two or more legs sharing a `voucher_id`, and the sides
must match. That check IS the feature.
"""

from __future__ import annotations

import inspect
from decimal import Decimal as D

import pytest
from beanie import PydanticObjectId

from app.core.exceptions import ValidationFailedError
from app.models.ledger_book import AccountType, VoucherType
from app.services import ledger_book_service as svc

T = __import__("datetime").datetime(2026, 9, 1)


class _Book:
    def __init__(self, name):
        self.id = PydanticObjectId()
        self.owner_id = "own"
        self.name = name
        self.account_type = AccountType.OTHER
        self.opening_balance = "0"


def _wire(monkeypatch, books):
    written = []
    by_id = {str(b.id): b for b in books}

    async def _get_book(_owner, bid):
        return by_id[str(bid)]

    class _E:
        def __init__(self, **kw):
            self.kw = kw

        async def insert(self):
            written.append(self.kw)

    monkeypatch.setattr(svc, "_get_book", _get_book)
    monkeypatch.setattr(svc, "LedgerBookEntry", _E)
    return written


# -- the rule ----------------------------------------------------------
async def test_a_balanced_voucher_is_written_as_linked_legs(monkeypatch):
    cash, party = _Book("Cash"), _Book("Shivam")
    written = _wire(monkeypatch, [cash, party])

    vid = await svc.post_voucher(
        "own", entry_date=T, voucher_type="Rcpt",
        legs=[
            {"book_id": cash.id, "debit": 50000},
            {"book_id": party.id, "credit": 50000},
        ],
    )
    assert len(written) == 2
    assert {str(w["voucher_id"]) for w in written} == {vid}


@pytest.mark.parametrize("dr,cr", [(50000, 40000), (1, 2), (100, 0)])
async def test_a_voucher_that_does_not_balance_is_refused(monkeypatch, dr, cr):
    """The only thing that makes a trial balance provable."""
    a, b = _Book("Cash"), _Book("Shivam")
    written = _wire(monkeypatch, [a, b])
    with pytest.raises(ValidationFailedError):
        await svc.post_voucher("own", entry_date=T, legs=[
            {"book_id": a.id, "debit": dr},
            {"book_id": b.id, "credit": cr},
        ])
    assert written == []


async def test_one_account_is_not_a_voucher(monkeypatch):
    a = _Book("Cash")
    _wire(monkeypatch, [a])
    with pytest.raises(ValidationFailedError):
        await svc.post_voucher("own", entry_date=T, legs=[{"book_id": a.id, "debit": 100}])


async def test_a_leg_is_one_side_or_the_other(monkeypatch):
    a, b = _Book("Cash"), _Book("Shivam")
    _wire(monkeypatch, [a, b])
    with pytest.raises(ValidationFailedError):
        await svc.post_voucher("own", entry_date=T, legs=[
            {"book_id": a.id, "debit": 100, "credit": 100},
            {"book_id": b.id, "credit": 100},
        ])


async def test_negative_amounts_are_refused(monkeypatch):
    a, b = _Book("Cash"), _Book("Shivam")
    _wire(monkeypatch, [a, b])
    with pytest.raises(ValidationFailedError):
        await svc.post_voucher("own", entry_date=T, legs=[
            {"book_id": a.id, "debit": -100},
            {"book_id": b.id, "credit": -100},
        ])


async def test_more_than_two_accounts_is_fine(monkeypatch):
    """One receipt split across two parties, say."""
    cash, p1, p2 = _Book("Cash"), _Book("A"), _Book("B")
    written = _wire(monkeypatch, [cash, p1, p2])
    await svc.post_voucher("own", entry_date=T, legs=[
        {"book_id": cash.id, "debit": 300},
        {"book_id": p1.id, "credit": 100},
        {"book_id": p2.id, "credit": 200},
    ])
    assert len(written) == 3


# -- what each leg reads like -----------------------------------------
async def test_each_leg_names_the_other_side(monkeypatch):
    """So a single row still reads on its own, the way a printed line does."""
    cash, party = _Book("Cash"), _Book("Shivam")
    written = _wire(monkeypatch, [cash, party])
    await svc.post_voucher("own", entry_date=T, legs=[
        {"book_id": cash.id, "debit": 500},
        {"book_id": party.id, "credit": 500},
    ])
    parts = {w["particulars"] for w in written}
    assert parts == {"Cash", "Shivam"}


async def test_legs_do_not_collide_on_the_idempotency_guard(monkeypatch):
    """They share a source but the unique (source_type, source_id) index would
    reject the second one if they carried the same id."""
    a, b = _Book("Cash"), _Book("Shivam")
    written = _wire(monkeypatch, [a, b])
    await svc.post_voucher("own", entry_date=T, source_type="X", source_id="abc", legs=[
        {"book_id": a.id, "debit": 5},
        {"book_id": b.id, "credit": 5},
    ])
    ids = [w["source_id"] for w in written]
    assert ids == ["abc:0", "abc:1"]
    assert len(set(ids)) == 2


async def test_an_unknown_voucher_type_falls_back_to_journal(monkeypatch):
    a, b = _Book("Cash"), _Book("Shivam")
    written = _wire(monkeypatch, [a, b])
    await svc.post_voucher("own", entry_date=T, voucher_type="Nonsense", legs=[
        {"book_id": a.id, "debit": 5},
        {"book_id": b.id, "credit": 5},
    ])
    assert written[0]["voucher_type"] == VoucherType.JOURNAL


# -- the accounts the operator asked for -------------------------------
def test_every_account_kind_the_operator_named_exists():
    assert {t.value for t in AccountType} >= {"CASH", "BANK", "PARTY", "EXPENSE"}


def test_a_party_account_is_found_by_person_not_by_name():
    """Renaming an admin's ledger must not orphan the rows posted to it."""
    src = inspect.getsource(svc.party_book)
    assert '"party_user_id": uid' in src


# -- trial balance -----------------------------------------------------
def test_the_trial_balance_reports_whether_it_squares():
    src = inspect.getsource(svc.trial_balance)
    assert '"balanced": tot_dr == tot_cr' in src
    assert '"difference"' in src


def test_single_sided_legacy_rows_are_called_out_separately():
    """They sit in the balances but cannot square by themselves — a mismatch
    needs an explanation, not a shrug."""
    src = inspect.getsource(svc.trial_balance)
    assert "e.voucher_id is None" in src
    assert '"unlinked_debit"' in src


def test_the_day_book_groups_by_voucher_not_by_line():
    src = inspect.getsource(svc.day_book)
    assert '"legs"' in src
    assert "e.voucher_id" in src
