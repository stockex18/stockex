"""The admin's account carries their P&L share; brokerage and games do not.

Operator: "pnl main ledger se kaam hoga, security money se brokerage aur
game". JKM (23 Nov): given 50,000 (a line naming their code), and the super
admin's 90% of a user's 17,100 profit (15,390) posted to their party book
against "P&L Share Income". The account showed only the 50,000.
"""

import asyncio
import types
from datetime import datetime, timezone
from decimal import Decimal

from bson import Decimal128, ObjectId

from app.services import ledger_book_service as svc

OWNER, ADMIN_UID = ObjectId(), ObjectId()
CASH, PARTY, INCOME = ObjectId(), ObjectId(), ObjectId()


def _e(book, particulars, dr, cr, hh, narration=""):
    return types.SimpleNamespace(
        id=ObjectId(), owner_id=OWNER, book_id=book, particulars=particulars,
        debit=Decimal128(dr), credit=Decimal128(cr), narration=narration,
        entry_date=datetime(2026, 11, 23, hh, tzinfo=timezone.utc), created_at=None,
        voucher_no="", is_auto=particulars != "ADM59017928",
    )


ROWS = [
    _e(CASH, "ADM59017928", "50000", "0", 12, "lager"),
    _e(PARTY, "Brokerage Income", "224.53", "0", 13, "SA brokerage (90.00%)"),
    _e(PARTY, "P&L Share Income", "0", "15390", 15, "SA P&L share 90.00% — CL97486914"),
    _e(INCOME, "JKM · ADM59017928", "15390", "0", 15, "SA P&L share 90.00% — CL97486914"),
]


def _matches(e, q):
    for k, v in q.items():
        if k == "$or":
            if not any(_matches(e, sub) for sub in v):
                return False
        elif isinstance(v, dict):
            val = getattr(e, k)
            if "$lt" in v and not val < v["$lt"]:
                return False
            if "$gte" in v and not val >= v["$gte"]:
                return False
            if "$lte" in v and not val <= v["$lte"]:
                return False
        elif getattr(e, k) != v:
            return False
    return True


class _Q:
    def __init__(self, data):
        self.data = data

    def sort(self, *_a):
        self.data = sorted(self.data, key=lambda e: e.entry_date)
        return self

    async def to_list(self):
        return self.data


def _wire(monkeypatch):
    books = [types.SimpleNamespace(id=CASH, name="Cash"),
             types.SimpleNamespace(id=PARTY, name="JKM · ADM59017928", party_user_id=ADMIN_UID),
             types.SimpleNamespace(id=INCOME, name="P&L Share Income")]

    async def book_find_one(q):
        return books[1] if q.get("party_user_id") == ADMIN_UID else None

    async def user_find_one(q):
        if q.get("user_code") == "ADM59017928":
            return types.SimpleNamespace(id=ADMIN_UID, user_code="ADM59017928", full_name="JKM")
        return None

    monkeypatch.setattr(svc, "LedgerBook", types.SimpleNamespace(
        find=lambda *_a, **_k: _Q(books), find_one=book_find_one))
    monkeypatch.setattr(svc, "LedgerBookEntry", types.SimpleNamespace(
        find=lambda q: _Q([e for e in ROWS if _matches(e, q)])))
    monkeypatch.setattr(svc, "User", types.SimpleNamespace(find_one=user_find_one))


def test_the_pnl_share_sits_beside_the_money_given(monkeypatch):
    _wire(monkeypatch)
    st = asyncio.run(svc.party_statement(OWNER, "ADM59017928"))
    rows = [(r["voucher_type"], r["debit"], r["credit"]) for r in st["rows"]]
    assert rows == [("Cash", "50000.00", "0.00"), ("P&L share", "0.00", "15390.00")]
    # 50,000 given, less the super admin's 90% of the loss it carries.
    assert (st["closing_balance"], st["closing_side"]) == ("34610.00", "Dr")


def test_brokerage_stays_on_the_security_book(monkeypatch):
    _wire(monkeypatch)
    st = asyncio.run(svc.party_statement(OWNER, "ADM59017928"))
    assert all("brokerage" not in r["particulars"].lower() for r in st["rows"])


def test_a_dated_statement_opens_on_the_same_lines(monkeypatch):
    _wire(monkeypatch)
    st = asyncio.run(svc.party_statement(
        OWNER, "ADM59017928", start=datetime(2026, 11, 23, 14, tzinfo=timezone.utc)))
    assert (st["opening_balance"], st["opening_side"]) == ("50000.00", "Dr")
    assert (st["closing_balance"], st["closing_side"]) == ("34610.00", "Dr")
    assert Decimal(st["total_credit"]) == Decimal("15390")
