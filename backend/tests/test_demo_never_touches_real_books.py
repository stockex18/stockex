"""A demo account's trading never moves real money for anyone above it.

Operator: demo ka sab transaction super admin ke ledger aur admin wallet me
aa raha hai — brokerage aur P&L ki entry — ye sab band karo, demo ka kuch
show mat ho.

Demo trades were booked by the admin book (SA P&L share, SA brokerage share,
broker cascade brokerage) as if they were real. Every money hook a closing
trade runs now turns a demo user away before it books anything.
"""

from __future__ import annotations

import asyncio
import inspect
from types import SimpleNamespace

from app.services import admin_book_service, patti_service, pnl_sharing_service, referral_service


def test_the_admin_book_refuses_a_demo_trade_before_anything_moves(monkeypatch):
    async def enabled():
        return True

    touched = {"resolved": False}

    async def resolve_sa():
        touched["resolved"] = True
        return "sa"

    from app.services import netting_service

    monkeypatch.setattr(admin_book_service, "is_admin_book_enabled", enabled)
    monkeypatch.setattr(netting_service, "_resolve_super_admin_id", resolve_sa)
    demo = SimpleNamespace(is_demo=True, assigned_admin_id="a1", id="u1")
    asyncio.run(admin_book_service.distribute_on_close(demo, "-500", "20", "NSE_FUT", "t1"))
    assert touched["resolved"] is False, "a demo trade got past the guard"


def test_the_guard_sits_before_the_first_booking():
    src = inspect.getsource(admin_book_service.distribute_on_close)
    assert src.index('getattr(user, "is_demo", False)') < src.index("wallet_service.adjust(")
    assert src.index('getattr(user, "is_demo", False)') < src.index("AdminBookEntry(")


def test_patti_never_cascades_a_demo_result():
    demo = SimpleNamespace(is_demo=True)
    # Returns before resolving any chain — would raise on a bare namespace otherwise.
    assert asyncio.run(patti_service.distribute_patti_on_close(demo, "-500", "0", "NSE_FUT", "t1")) is None


def test_a_demo_account_never_earns_a_referral_reward():
    src = inspect.getsource(referral_service.credit_referral_trading_reward)
    assert 'getattr(referred, "is_demo", False)' in src


def test_broker_sharing_leaves_demo_clients_out():
    src = inspect.getsource(pnl_sharing_service._broker_client_ids)
    assert '"is_demo": {"$ne": True}' in src
