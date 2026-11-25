"""Weekly settlement books P&L into the position's OWN trading wallet.

Bug (found 25 Nov 2026): the weekly mark-to-market used the MAIN wallet
(`wallet_service.adjust`) while trades keep their money in SEGMENT wallets
(`wallet_router`). With main at ~0, every weekly loss booked in full to
settlement_outstanding although the client had the money in NSE_BSE / MCX
(Gourav Saxena CL22471117: 🪙37,736.87 outstanding), and weekly profits went
to main instead of the trading wallet.
"""

from __future__ import annotations

import asyncio
import inspect
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.services import weekly_settlement_service as wss


class _Doc:
    """Stand-in for a Beanie document: accepts any fields, insert/save no-op."""

    def __init__(self, **kw):
        self.__dict__.update(kw)
        self.id = "rec1"

    async def insert(self):
        return self

    async def save(self):
        return self


def _pos(segment="MCX_FUTURE", segment_type="MCX_FUT", qty=1.0, avg="1000"):
    p = SimpleNamespace(
        id="p1",
        user_id="u1",
        quantity=qty,
        avg_price=avg,
        instrument=SimpleNamespace(token="t1", symbol="SILVERMIC26NOVFUT", segment=segment),
        segment_type=segment_type,
        product_type="NRML",
        opened_side=None,
        is_pledge=False,
        is_demo=False,
        margin_used="0",
        pledge_margin=None,
        realized_pnl="0",
        stop_loss=None,
        target=None,
        open_usd_inr_rate=None,
        close_usd_inr_rate=None,
        close_stop_loss=None,
        close_target=None,
    )

    async def save():
        return p

    p.save = save
    return p


@pytest.fixture
def run(monkeypatch):
    calls: list = []

    async def ltp(_tok):
        return run.ltp

    async def adjust(user_id, segment, amount, **kw):
        calls.append(("adjust", user_id, segment, Decimal(str(amount)), kw["transaction_type"].value))
        if run.raise_insufficient:
            from app.core.exceptions import InsufficientFundsError

            raise InsufficientFundsError("no funds")

    async def force_debit(user_id, segment, amount, **kw):
        calls.append(("force_debit", user_id, segment, Decimal(str(amount)), kw["transaction_type"].value))

    async def nothing(**_kw):
        return None

    monkeypatch.setattr(wss.market_data_service, "get_ltp", ltp)
    monkeypatch.setattr(wss.market_data_service, "is_usd_quoted_segment", lambda _s: False)
    monkeypatch.setattr(wss.wallet_router, "adjust", adjust)
    monkeypatch.setattr(wss.wallet_router, "force_debit", force_debit)
    monkeypatch.setattr(wss, "PositionSettlement", _Doc)
    monkeypatch.setattr(wss, "Position", _Doc)
    monkeypatch.setattr(wss.position_service, "_recompute_tracker", nothing)
    run.ltp = Decimal("900")
    run.raise_insufficient = False
    run.calls = calls
    return run


def _settle(pos):
    batch = SimpleNamespace(id="b1", week_key="2026-W48", scope_admin_id=None)
    return asyncio.run(wss._settle_one_position(pos, batch=batch, fx_rate=Decimal("1")))


def test_loss_goes_to_the_positions_segment_wallet(run):
    assert _settle(_pos()) == "settled"
    assert run.calls == [("adjust", "u1", "MCX_FUTURE", Decimal("-100.00"), "PNL")]


def test_profit_goes_to_the_positions_segment_wallet(run):
    run.ltp = Decimal("1250")
    assert _settle(_pos(segment="NSE_FUTURE", segment_type="NSE_IDX_FUT")) == "settled"
    assert run.calls == [("adjust", "u1", "NSE_FUTURE", Decimal("250.00"), "PNL")]


def test_falls_back_to_segment_type_when_instrument_has_no_segment(run):
    _settle(_pos(segment=None, segment_type="MCX_FUT"))
    assert run.calls[0][2] == "MCX_FUT"


def test_single_wallet_mode_shortfall_still_goes_through_the_router(run):
    """MULTI_WALLET off: the router's main-wallet adjust can still raise; the
    overflow must go through the router's force_debit, same segment."""
    run.raise_insufficient = True
    assert _settle(_pos()) == "settled"
    assert [c[0] for c in run.calls] == ["adjust", "force_debit"]
    assert run.calls[1][2:4] == ("MCX_FUTURE", Decimal("100.00"))


def test_no_main_wallet_calls_left():
    src = inspect.getsource(wss._settle_one_position)
    assert "await wallet_service." not in src
    assert "wallet_router.adjust(" in src and "wallet_router.force_debit(" in src
