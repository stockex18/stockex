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
from app.models.ledger_book import FED_KINDS, LedgerKind, VoucherType
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
        self.kind = LedgerKind.CASH
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

    async def _ensure(_):
        return None

    async def _find_one(_q):
        return _Book()

    monkeypatch.setattr(svc, "ensure_default_books", _ensure)
    monkeypatch.setattr(svc.LedgerBook, "find_one", staticmethod(_find_one))
    monkeypatch.setattr(svc, "LedgerBookEntry", _Entry)
    return posted


# -- the running balance ----------------------------------------------
async def test_running_balance_walks_the_rows(monkeypatch):
    _wire(monkeypatch, [_E(1, dr="1000"), _E(2, cr="400"), _E(3, dr="150")])
    st = await svc.statement(OWNER, BOOK)
    assert [r["balance"] for r in st["rows"]] == ["1000.00", "600.00", "750.00"]
    assert st["closing_balance"] == "750.00"
    assert st["closing_side"] == "Dr"


async def test_going_past_zero_flips_the_side(monkeypatch):
    """More paid out than came in — that is a Cr balance, not a negative Dr."""
    _wire(monkeypatch, [_E(1, dr="100"), _E(2, cr="450")])
    st = await svc.statement(OWNER, BOOK)
    assert st["closing_balance"] == "350.00"
    assert st["closing_side"] == "Cr"
    assert st["rows"][-1]["balance_side"] == "Cr"


async def test_opening_balance_is_the_starting_point(monkeypatch):
    _wire(monkeypatch, [_E(1, cr="150000")], opening="2311735")
    st = await svc.statement(OWNER, BOOK)
    assert st["opening_balance"] == "2311735.00"
    assert st["rows"][0]["balance"] == "2161735.00"


async def test_earlier_rows_are_folded_into_the_opening(monkeypatch):
    """Narrowing the window must SHOW less, not RESTATE the balance."""
    _wire(monkeypatch, [_E(9, cr="100")], opening="500", before=[_E(1, dr="1000")])
    st = await svc.statement(OWNER, BOOK, start=T0 + timedelta(days=5))
    assert st["opening_balance"] == "1500.00"   # 500 carried + 1000 before the window
    assert st["rows"][0]["balance"] == "1400.00"


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


async def test_an_unknown_mode_lands_in_others(monkeypatch):
    """Never drop a real movement on the floor because of a new mode string."""
    posted = _post_wire(monkeypatch)
    assert await svc.post(OWNER, "NEFT", amount=D("5"), is_inflow=True,
                          source_type="X", source_id="9") is True
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
    async def _boom(_):
        raise RuntimeError("db down")

    monkeypatch.setattr(svc, "ensure_default_books", _boom)
    assert await svc.post(OWNER, "CASH", amount=D("1"), is_inflow=True,
                          source_type="X", source_id="5") is False


# -- wiring + guards ---------------------------------------------------
def test_both_directions_of_the_wallet_flow_are_hooked():
    from app.services import admin_fund_service as afs

    for fn in (afs.add_funds, afs.deduct_funds):
        src = inspect.getsource(fn)
        assert "ledger_book_service.post" in src
        assert "source_id=" in src  # the unique index is what stops double-posting


def test_security_money_movements_are_hooked():
    from app.services import admin_security_service as ass

    for fn in (ass.record_deposit, ass.record_withdraw):
        assert "_to_ledger" in inspect.getsource(fn)


def test_fed_books_cannot_be_deleted():
    assert "FED_KINDS" in inspect.getsource(svc.delete_book)


def test_auto_lines_cannot_be_hand_deleted():
    assert "is_auto" in inspect.getsource(svc.delete_entry)


def test_the_five_payment_modes_all_have_a_book():
    assert {k.value for k in FED_KINDS} == {"CASH", "CHEQUE", "BANKING", "UPI", "OTHERS"}
    assert {k for _n, k in svc.DEFAULT_BOOKS} == set(FED_KINDS)


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
