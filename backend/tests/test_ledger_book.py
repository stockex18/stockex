"""The ledger statement — the arithmetic a printed ledger is judged on.

    running = opening + sum(debit) - sum(credit)      positive => Dr

and the printed totals must SQUARE: the closing figure joins whichever column
is short so both add to the same grand total. If that stops holding, the page
still renders and the numbers are quietly wrong — the worst outcome for a
document handed to an accountant.
"""

from __future__ import annotations

import inspect
from datetime import datetime, timedelta, timezone
from decimal import Decimal as D

import pytest
from beanie import PydanticObjectId
from bson import Decimal128

from app.core.exceptions import ValidationFailedError
from app.models.ledger_book import VoucherType
from app.services import ledger_book_service as svc
from app.services.ledger_pdf_service import build_ledger_pdf

OWNER = PydanticObjectId()
BOOK = PydanticObjectId()
T0 = datetime(2026, 7, 1, tzinfo=timezone.utc)


class _Book:
    def __init__(self, opening="0"):
        self.id = BOOK
        self.owner_id = OWNER
        self.name = "Cash"
        self.code = "CASH"
        self.is_payment_mode = True
        self.opening_balance = Decimal128(opening)


class _E:
    def __init__(self, day, dr="0", cr="0"):
        self.id = PydanticObjectId()
        self.entry_date = T0 + timedelta(days=day)
        self.voucher_type = VoucherType.RECEIPT
        self.voucher_no = "V" + str(day)
        self.particulars = "ADM1"
        self.narration = ""
        self.debit = Decimal128(dr)
        self.credit = Decimal128(cr)
        self.is_auto = False


def _wire(monkeypatch, rows, opening="0", before=()):
    book = _Book(opening)

    async def _get_book(_o, _b):
        return book

    class _Find:
        def __init__(self, q):
            self.q = q

        def sort(self, *_a):
            return self

        async def to_list(self):
            return list(rows)

        def __aiter__(self):
            async def gen():
                for e in before:
                    yield e

            return gen()

    monkeypatch.setattr(svc, "_get_book", _get_book)
    monkeypatch.setattr(svc.LedgerBookEntry, "find", staticmethod(lambda q: _Find(q)))
    return book


def _post_wire(monkeypatch):
    """Stub out the two collections `post` touches; return what it wrote."""
    posted = []

    class _Entry:
        def __init__(self, **kw):
            self.kw = kw

        async def insert(self):
            posted.append(self.kw)

    async def _find_one(_q):
        return _Book()

    monkeypatch.setattr(svc.LedgerBook, "find_one", staticmethod(_find_one))
    monkeypatch.setattr(svc, "LedgerBookEntry", _Entry)
    return posted


# -- the running balance ----------------------------------------------
# `_E(dr=…)` is what is STORED, and a stored debit is an inflow. These books
# are read the operator's way — money reaching you is a credit, money leaving
# is a debit — so a stored dr renders in the Cr column. See
# `ledger_book_service.cash_sides`. The mechanics under test are the running
# balance and the opening carry; only which side they land on has moved.
async def test_running_balance_walks_the_rows(monkeypatch):
    # Received 1000, paid 400, received 150 — 750 still with you, so Cr.
    _wire(monkeypatch, [_E(1, dr="1000"), _E(2, cr="400"), _E(3, dr="150")])
    st = await svc.statement(OWNER, BOOK)
    assert [r["balance"] for r in st["rows"]] == ["1000.00", "600.00", "750.00"]
    assert st["closing_balance"] == "750.00"
    assert st["closing_side"] == "Cr"


async def test_going_past_zero_flips_the_side(monkeypatch):
    """Paid out more than came in — the side flips rather than going negative."""
    _wire(monkeypatch, [_E(1, dr="100"), _E(2, cr="450")])
    st = await svc.statement(OWNER, BOOK)
    assert st["closing_balance"] == "350.00"
    assert st["closing_side"] == "Dr"
    assert st["rows"][-1]["balance_side"] == "Dr"


async def test_opening_balance_is_the_starting_point(monkeypatch):
    _wire(monkeypatch, [_E(1, cr="150000")], opening="2311735")
    st = await svc.statement(OWNER, BOOK)
    assert st["opening_balance"] == "2311735.00"
    assert st["rows"][0]["balance"] == "2461735.00"


async def test_earlier_rows_are_folded_into_the_opening(monkeypatch):
    """Narrowing the window must SHOW less, not RESTATE the balance."""
    _wire(monkeypatch, [_E(9, cr="100")], opening="500", before=[_E(1, dr="1000")])
    st = await svc.statement(OWNER, BOOK, start=T0 + timedelta(days=5))
    # 500 carried, less the 1000 received before the window — 500 the other way.
    assert st["opening_balance"] == "500.00"
    assert st["opening_side"] == "Cr"
    assert st["rows"][0]["balance"] == "400.00"


async def test_the_printed_totals_square(monkeypatch):
    """Closing joins the short column; both columns must reach the grand total."""
    _wire(monkeypatch, [_E(1, cr="150000"), _E(2, cr="100000")], opening="2311735")
    st = await svc.statement(OWNER, BOOK)
    dr = D(st["total_debit"])
    cr = D(st["total_credit"])
    closing = D(st["closing_balance"])
    grand = D(st["grand_total"])
    short = cr if st["closing_side"] == "Dr" else dr
    assert short + closing == grand
    assert max(dr, cr) == grand


async def test_a_book_with_no_movement_still_reports(monkeypatch):
    _wire(monkeypatch, [])
    st = await svc.statement(OWNER, BOOK)
    assert st["rows"] == []
    assert st["closing_balance"] == "0.00"
    assert st["grand_total"] == "0.00"


# -- posting rules -----------------------------------------------------
async def test_a_line_must_be_one_sided(monkeypatch):
    async def _get_book(_o, _b):
        return _Book()

    monkeypatch.setattr(svc, "_get_book", _get_book)
    for dr, cr in ((100, 100), (0, 0)):
        with pytest.raises(ValidationFailedError):
            await svc.add_entry(OWNER, BOOK, entry_date=T0, debit=dr, credit=cr)


async def test_negative_amounts_are_refused(monkeypatch):
    async def _get_book(_o, _b):
        return _Book()

    monkeypatch.setattr(svc, "_get_book", _get_book)
    with pytest.raises(ValidationFailedError):
        await svc.add_entry(OWNER, BOOK, entry_date=T0, debit=-5, credit=0)


# -- auto-posting ------------------------------------------------------
@pytest.mark.parametrize("mode", ["CASH", "cash", " Cheque ", "UPI"])
async def test_a_stamped_mode_finds_its_book(monkeypatch, mode):
    posted = _post_wire(monkeypatch)
    ok = await svc.post(OWNER, mode, amount=D("500"), is_inflow=True,
                        source_type="X", source_id="1")
    assert ok is True
    assert D(str(posted[0]["debit"])) == D("500")
    assert D(str(posted[0]["credit"])) == D("0")
    assert posted[0]["voucher_type"] == VoucherType.RECEIPT


async def test_money_going_out_is_a_credit(monkeypatch):
    posted = _post_wire(monkeypatch)
    await svc.post(OWNER, "CASH", amount=D("500"), is_inflow=False,
                   source_type="X", source_id="2")
    assert D(str(posted[0]["credit"])) == D("500")
    assert D(str(posted[0]["debit"])) == D("0")
    assert posted[0]["voucher_type"] == VoucherType.PAYMENT


async def test_a_mode_this_owner_has_never_used_opens_its_book(monkeypatch):
    """Never drop a real movement: if the book is missing, open it."""
    posted = _post_wire(monkeypatch)
    opened = []

    async def _none(_q):
        return None

    async def _open(_o, code):
        opened.append(code)
        return _Book()

    monkeypatch.setattr(svc.LedgerBook, "find_one", staticmethod(_none))
    monkeypatch.setattr(svc, "_open_book_for", _open)
    assert await svc.post(OWNER, "NEFT Transfer", amount=D("5"), is_inflow=True,
                          source_type="X", source_id="9") is True
    assert opened == ["NEFT_TRANSFER"]
    assert posted


async def test_an_unstamped_movement_is_not_a_ledger_line():
    """Internal coin moves carry no payment mode — they are not physical money."""
    assert await svc.post(OWNER, None, amount=D("500"), is_inflow=True,
                          source_type="X", source_id="3") is False
    assert await svc.post(OWNER, "", amount=D("500"), is_inflow=True,
                          source_type="X", source_id="4") is False


@pytest.mark.parametrize("bad", [D("0"), D("-5")])
async def test_nothing_to_post_is_a_no_op(monkeypatch, bad):
    posted = _post_wire(monkeypatch)
    assert await svc.post(OWNER, "CASH", amount=bad, is_inflow=True,
                          source_type="X", source_id="6") is False
    assert posted == []


async def test_posting_never_raises(monkeypatch):
    """It records money that ALREADY moved — it must not be able to undo it."""
    async def _boom(_q):
        raise RuntimeError("db down")

    monkeypatch.setattr(svc.LedgerBook, "find_one", staticmethod(_boom))
    assert await svc.post(OWNER, "CASH", amount=D("1"), is_inflow=True,
                          source_type="X", source_id="5") is False


# -- wiring + guards ---------------------------------------------------
def test_a_coin_move_is_no_longer_hooked_to_a_ledger():
    """It used to be, and being one click is what made both records wrong.

    Coins are the platform's internal balance; a ledger line is real money
    that arrived by cheque or UPI. They happen at different times and in
    different amounts — an admin can pay 5 lakh by cheque today against coins
    given last week — so the super admin records them separately now.
    """
    from app.services import admin_fund_service as afs

    for fn in (afs.add_funds, afs.deduct_funds):
        assert "ledger_book_service" not in inspect.getsource(fn)


def test_the_hand_written_side_replaced_it():
    """Removing the hook without the replacement would just lose the record."""
    src = inspect.getsource(svc.post_party_entry)
    assert 'is_inflow=(d == "RECEIVED")' in src
    assert "source_id=" in src  # the unique index is what stops double-posting


def test_security_money_movements_are_hooked():
    from app.services import admin_security_service as ass

    for fn in (ass.record_deposit, ass.record_withdraw):
        assert "_to_ledger" in inspect.getsource(fn)


def test_a_book_that_has_recorded_money_cannot_be_deleted():
    """Those lines ARE the record of money that moved — archive, never delete."""
    src = inspect.getsource(svc.delete_book)
    assert "is_auto" in src and "archive" in src.lower()


def test_auto_lines_cannot_be_hand_deleted():
    assert "is_auto" in inspect.getsource(svc.delete_entry)


# -- payment-mode codes ------------------------------------------------
@pytest.mark.parametrize("name,code", [
    ("Cash", "CASH"),
    ("HDFC Bank", "HDFC_BANK"),
    ("  Cheque  ", "CHEQUE"),
    ("Bank / OD a-c", "BANK_OD_A_C"),
    ("UPI", "UPI"),
    ("", "MODE"),
    ("!!!", "MODE"),
])
def test_the_mode_code_is_a_stable_slug(name, code):
    assert svc.slug(name) == code


def test_the_code_is_not_editable():
    """It is stamped on movements that already happened — changing it would
    orphan every one of them."""
    src = inspect.getsource(svc.update_book)
    assert "b.code =" not in src


def test_creating_a_mode_opens_its_ledger():
    """One act, so a mode can never exist with nowhere to post."""
    assert "is_payment_mode" in inspect.getsource(svc.create_book)


def test_modes_come_from_the_super_admin():
    src = inspect.getsource(svc.payment_modes)
    assert "SUPER_ADMIN" in src
    assert "is_payment_mode" in src


# -- the printed document ----------------------------------------------
def test_the_pdf_actually_renders():
    st = {
        "book": {"name": "M/S DEEPAK ENTERPRISES"},
        "opening_balance": "2311735.00", "opening_side": "Dr",
        "rows": [{
            "entry_date": "2026-07-02T00:00:00+00:00", "voucher_type": "Rcpt",
            "voucher_no": "U70427212", "particulars": "UNION BANK OF INDIA O/D",
            "narration": "", "debit": "0", "credit": "150000.00",
            "balance": "2161735.00", "balance_side": "Dr",
        }],
        "total_debit": "2311735.00", "total_credit": "150000.00",
        "closing_balance": "2161735.00", "closing_side": "Dr",
        "grand_total": "2311735.00",
        "start": "2026-07-01T00:00:00+00:00", "end": "2026-08-18T00:00:00+00:00",
    }
    out = build_ledger_pdf(st, {"name": "V N AGENCIES PVT LTD", "address": "NEW DELHI-110059"})
    assert out.startswith(b"%PDF")
    assert len(out) > 1500


def test_the_pdf_survives_a_missing_firm_header():
    out = build_ledger_pdf({"book": {"name": "Cash"}, "rows": []}, None)
    assert out.startswith(b"%PDF")


def test_empty_columns_print_blank_not_zero():
    """A printed ledger leaves the untouched column empty."""
    from app.services.ledger_pdf_service import _money

    assert _money(0) == ""
    assert _money("0.00") == ""
    assert _money("1500") == "1,500.00"


def test_amounts_use_indian_grouping():
    """These get read next to printed ledgers written in lakhs, not thousands."""
    from app.services.ledger_pdf_service import _money

    assert _money("2311735") == "23,11,735.00"
    assert _money("161735") == "1,61,735.00"
    assert _money("999") == "999.00"
    assert _money("12345678901.5") == "12,34,56,78,901.50"


def test_the_printed_table_fits_the_page():
    """186mm of usable A4. The columns totalled 202mm and ran off the edge."""
    import inspect

    from app.services import ledger_pdf_service as lp

    src = inspect.getsource(lp.build_ledger_pdf)
    assert "assert sum(widths) == 186 * mm" in src


def test_a_nil_balance_prints_blank_not_a_lone_side():
    from app.services.ledger_pdf_service import _bal

    assert _bal(0, "Dr") == ""
    assert _bal("49400", "Dr") == "49,400.00 Dr"
    assert _bal("7129.98", "Cr") == "7,129.98 Cr"


# -- the per-admin party account ---------------------------------------
def test_a_party_account_follows_the_cash_books():
    """It used to mirror them, and the mirror read backwards.

    The books record only the CASH leg of a funding, never the coin leg:
    "Received" takes the admin's money AND hands them that many coins, and
    only the first half reaches a ledger. Mirroring that one leg made funding
    an admin show as a credit — as though the platform owed them — when the
    coins had gone the other way. Operator's call on their own rows: funds
    given read Dr, funds pulled back read Cr.
    """
    src = inspect.getsource(svc.party_statement)
    assert "dr = to_decimal(e.debit)" in src
    assert "cr = to_decimal(e.credit)" in src


def test_the_party_opening_follows_the_rows():
    """An opening on the other sign would make a dated statement disagree with
    the same statement run without dates."""
    src = inspect.getsource(svc.party_statement)
    assert "opening += to_decimal(e.debit) - to_decimal(e.credit)" in src


def test_a_party_row_names_the_ledger_it_moved_through():
    src = inspect.getsource(svc.party_statement)
    assert "books.get(e.book_id" in src


def test_the_party_list_comes_from_posted_lines():
    """Reading the user list instead would offer accounts with nothing in them.

    And it must go through the motor collection: Beanie's FindMany has no
    .distinct(), so the Beanie form raises at runtime rather than at import.
    """
    src = inspect.getsource(svc.parties)
    assert "get_motor_collection()" in src
    assert 'coll.distinct("particulars"' in src


def test_an_empty_party_code_is_refused():
    src = inspect.getsource(svc.party_statement)
    assert "Pick an account" in src


def test_the_party_statement_renders_with_the_same_builder():
    src = inspect.getsource(svc.party_statement)
    for key in ("opening_balance", "opening_side", "rows", "total_debit",
                "total_credit", "closing_balance", "closing_side", "grand_total"):
        assert '"' + key + '"' in src
