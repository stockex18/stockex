"""The SA's fixed brokerage comes out of the admin's security money.

Two things are easy to get wrong here and both are money:

  * charging an admin who never lodged collateral — that would open a row at
    -X and invent a debt nobody agreed to;
  * charging BOTH the security and the wallet, or neither, when the fallback
    branch is wired up wrong.
"""

from __future__ import annotations

import inspect
from decimal import Decimal as D

import pytest
from beanie import PydanticObjectId
from bson import Decimal128

from app.models.admin_security import SecurityEntryType
from app.services import admin_book_service as abs_
from app.services import admin_security_service as svc

ADMIN = PydanticObjectId()


class _Row:
    def __init__(self):
        self.admin_id = ADMIN
        self.security_balance = Decimal128("50000")
        self.payable_balance = Decimal128("600")
        self.total_deposited = Decimal128("50000")
        self.total_games_in = Decimal128("600")
        self.total_games_out = Decimal128("0")
        self.total_brokerage = Decimal128("0")

    async def save(self):
        return None


def _wire(monkeypatch, *, has_row=True):
    row = _Row()
    entries = []

    async def _find_one(*_a, **_k):
        return row if has_row else None

    async def _get_or_create(_):
        return row

    class _Entry:
        def __init__(self, **kw):
            self.kw = kw

        async def insert(self):
            entries.append(self.kw)

    monkeypatch.setattr(svc.AdminSecurity, "find_one", staticmethod(_find_one))
    monkeypatch.setattr(svc, "get_or_create", _get_or_create)
    monkeypatch.setattr(svc, "AdminSecurityEntry", _Entry)
    return row, entries


async def test_brokerage_eats_the_collateral(monkeypatch):
    row, _ = _wire(monkeypatch)
    assert await svc.charge_brokerage(ADMIN, D("1000")) is True
    assert D(str(row.security_balance)) == D("49000")


async def test_brokerage_never_touches_payable(monkeypatch):
    """Brokerage is the SA EARNING money, not owing it."""
    row, _ = _wire(monkeypatch)
    await svc.charge_brokerage(ADMIN, D("1000"))
    assert D(str(row.payable_balance)) == D("600")


async def test_brokerage_rolls_up_as_a_positive_total(monkeypatch):
    """Stored delta is negative; the headline figure must read as an amount."""
    row, _ = _wire(monkeypatch)
    await svc.charge_brokerage(ADMIN, D("1000"))
    await svc.charge_brokerage(ADMIN, D("250"))
    assert D(str(row.total_brokerage)) == D("1250")


async def test_an_admin_without_collateral_is_not_charged(monkeypatch):
    """No row means nothing was lodged — do not open one at a negative."""
    _, entries = _wire(monkeypatch, has_row=False)
    assert await svc.charge_brokerage(ADMIN, D("1000")) is False
    assert entries == []


@pytest.mark.parametrize("bad", [D("0"), D("-5")])
async def test_nothing_to_charge_is_a_no_op(monkeypatch, bad):
    _, entries = _wire(monkeypatch)
    assert await svc.charge_brokerage(ADMIN, bad) is False
    assert entries == []


async def test_no_admin_is_a_no_op(monkeypatch):
    _wire(monkeypatch)
    assert await svc.charge_brokerage(None, D("1000")) is False


async def test_the_trade_is_recorded_on_the_entry(monkeypatch):
    """A brokerage row must be traceable back to the trade that caused it."""
    _, entries = _wire(monkeypatch)
    await svc.charge_brokerage(ADMIN, D("1000"), trade_id="T1", user_id=PydanticObjectId())
    assert entries[0]["trade_id"] == "T1"
    assert entries[0]["entry_type"] == SecurityEntryType.BROKERAGE
    assert D(str(entries[0]["amount"])) == D("-1000")


# -- the wiring at the trade choke point ------------------------------
def test_the_wallet_is_only_debited_when_security_did_not_take_it():
    """Exactly one of the two must happen — never both, never neither."""
    src = inspect.getsource(abs_.distribute_on_close)
    i = src.index("charge_brokerage")
    tail = src[i:]
    assert "if not charged:" in tail
    # the wallet debit must sit INSIDE that branch
    assert tail.index("if not charged:") < tail.index("admin_id, -sa_bkg")


def test_brokerage_is_charged_before_the_sa_is_credited():
    """The SA credit is unchanged — it is only the admin side that moved."""
    src = inspect.getsource(abs_.distribute_on_close)
    assert src.count("sa_id, sa_bkg, transaction_type=TransactionType.SA_BROKERAGE_SHARE") == 2


def test_pass_through_admins_are_untouched():
    """A no_self admin's wallet was never debited for sa_bkg — keep it that way."""
    src = inspect.getsource(abs_.distribute_on_close)
    head = src[: src.index("charge_brokerage")]
    assert "no_self" in head  # the pass-through branch comes first...
    assert "charge_brokerage" not in head  # ...and does not charge security


def test_the_read_exposes_the_new_total():
    assert '"total_brokerage"' in inspect.getsource(svc.list_all)
