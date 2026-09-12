"""The super admin's P&L share draws down the admin's collateral.

Operator: "admin ke is wale ledger me pnl sharing me jitna paisa super admin ko
aata hai wo cut ho aur wahi entry dikhe, isse balance kam hota chale."

It used to move only between the two wallets, so nothing showed in the admin's
Security ledger. It now follows the rule the SA's brokerage already follows:
charge the collateral when the admin has lodged any, fall back to the wallet
when they have not.
"""

from __future__ import annotations

import asyncio
import inspect
from decimal import Decimal

import pytest

from app.models.admin_security import SecurityEntryType
from app.services import admin_book_service, admin_security_service as sec


ADMIN_ID = "6a7adfaa509a90c4e42cb0f6"  # a real-shaped id: the service casts it


@pytest.fixture
def collateral(monkeypatch):
    """Fake the security row + capture what _apply is asked to do."""
    state = {"has_row": True, "applied": []}

    async def find_one(_q):
        return object() if state["has_row"] else None

    async def _apply(admin_id, **kw):
        state["applied"].append(kw)
        return object()

    monkeypatch.setattr(sec.AdminSecurity, "find_one", staticmethod(find_one))
    monkeypatch.setattr(sec, "_apply", _apply)
    return state


def _charge(amount):
    return asyncio.run(
        sec.charge_pnl_share(ADMIN_ID, amount, narration="SA P&L share 20% — CL1 (NSE_FUT)", trade_id="t1", user_id=None)
    )


def test_the_share_the_sa_earns_comes_out_of_the_collateral(collateral):
    assert _charge("2000") is True
    (kw,) = collateral["applied"]
    assert kw["entry_type"] == SecurityEntryType.PNL_SHARE
    assert Decimal(str(kw["security_delta"])) == Decimal("-2000")  # drawn down
    assert "SA P&L share" in kw["narration"]
    assert kw["trade_id"] == "t1"


def test_a_user_profit_puts_it_back(collateral):
    # A user PROFIT makes the SA's share negative — the SA pays, collateral up.
    assert _charge("-1500") is True
    (kw,) = collateral["applied"]
    assert Decimal(str(kw["security_delta"])) == Decimal("1500")


def test_an_admin_without_collateral_falls_back_to_the_wallet(collateral):
    collateral["has_row"] = False
    assert _charge("2000") is False
    assert collateral["applied"] == []


def test_zero_is_not_a_line(collateral):
    assert _charge("0") is False
    assert collateral["applied"] == []


def test_the_trade_close_charges_the_collateral_first_then_the_wallet():
    src = inspect.getsource(admin_book_service.distribute_on_close)
    i = src.index("charge_pnl_share(")
    j = src.index("if not _pnl_charged:", i)
    k = src.index("transaction_type=TransactionType.SA_PNL_SHARE", j)
    assert i < j < k, "collateral first, wallet only as the fallback"
    # The SA's own credit must stay — only where the admin pays FROM changed.
    assert src.count("TransactionType.SA_PNL_SHARE") >= 2


def test_the_statement_names_it_and_groups_it_by_day():
    assert sec._ENTRY_LABEL[SecurityEntryType.PNL_SHARE] == "SA P&L share"
    assert sec._TYPE_FIXED[SecurityEntryType.PNL_SHARE] == "P&L share"
    # `is_auto` is what the ledger groups per day and hides the delete on.
    src = inspect.getsource(sec.statement)
    block = src[src.index('"is_auto"') : src.index('"is_auto"') + 260]
    assert "SecurityEntryType.PNL_SHARE" in block
