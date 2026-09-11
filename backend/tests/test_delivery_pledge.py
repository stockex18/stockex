"""Delivery pledge — the operator's worked example, end to end on the arithmetic.

    NSE wallet 2,00,000. Buy 1,50,000 of shares for delivery:
        cash left            50,000
        pledge (50 %)        75,000
        F&O buying power   1,25,000
    Use all 1,25,000 in F&O (75,000 pledge + 50,000 cash). F&O loss −45,000
    = 90 % of the 50,000 cash → stop-out, F&O only; the shares stay.
"""

from __future__ import annotations

import asyncio
import inspect
from decimal import Decimal
from types import SimpleNamespace

from app.services import pledge_service as pl

D = Decimal
H = D("50")


def _pos(*, qty, avg, ltp, margin, pledge=False, pledge_margin=0, unreal=0):
    return SimpleNamespace(
        quantity=qty, avg_price=D(str(avg)), ltp=D(str(ltp)), margin_used=D(str(margin)),
        is_pledge=pledge, pledge_margin=D(str(pledge_margin)), unrealized_pnl=D(str(unreal)),
    )


SHARES = _pos(qty=100, avg=1500, ltp=1500, margin=150_000, pledge=True)
FNO = _pos(qty=50, avg=100, ltp=100, margin=50_000, pledge_margin=75_000, unreal=-45_000)


def test_buy_gives_half_its_value_as_pledge():
    st = pl.compute_state([SHARES], [], H)
    assert (st.holdings_value, st.limit, st.available) == (D("150000"), D("75000"), D("75000"))


def test_fno_margin_takes_pledge_first_then_cash():
    assert pl.split_margin(D("125000"), D("75000")) == D("75000")  # rest 50,000 from cash
    assert pl.split_margin(D("10000"), D("75000")) == D("10000")  # all from pledge
    assert pl.split_margin(D("10000"), D("0")) == D("0")


def test_pending_orders_hold_their_pledge():
    st = pl.compute_state([SHARES], [SimpleNamespace(margin_pledge=D("30000"))], H)
    assert st.used == D("30000") and st.available == D("45000")


def test_stop_out_is_90_pct_of_cash_and_spares_the_shares():
    # Wallet after the trades: available 0, used 1,50,000 (shares) + 50,000 (F&O cash).
    available, used, credit = D("0"), D("200000"), D("0")
    v = pl.risk_view([SHARES, FNO], H)
    balance = available + used + credit - v.delivery_locked
    loss = -(FNO.unrealized_pnl + SHARES.unrealized_pnl - v.delivery_unrealised - v.deficit)
    assert balance == D("50000")
    assert loss / balance * 100 == D("90")
    assert v.others == [FNO]  # stop-out closes F&O only


def test_a_falling_share_price_shrinks_the_pledge_and_the_gap_is_loss():
    fell = _pos(qty=100, avg=1500, ltp=1200, margin=150_000, pledge=True, unreal=-30_000)
    st = pl.compute_state([fell, FNO], [], H)
    assert st.limit == D("60000") and st.deficit == D("15000") and st.available == 0
    v = pl.risk_view([fell, FNO], H)
    # The 30,000 fall on the shares is NOT cash loss; only the 15,000 gap is.
    assert v.delivery_unrealised == D("-30000") and v.deficit == D("15000")


def test_selling_pledged_shares_needs_the_pledge_free():
    st = pl.compute_state([SHARES, FNO], [], H)
    assert not pl.sale_keeps_cover(st, D("1500"), H)  # any sale breaks the 75,000 in use
    idle = pl.compute_state([SHARES], [], H)
    assert pl.sale_keeps_cover(idle, D("150000"), H)


def test_only_indian_fno_takes_pledge():
    for s in ("NSE_FUTURE", "NSE_INDEX_FUTURE", "NSE_STOCK_OPTION_BUY", "NSE_INDEX_OPTION_SELL", "BSE_INDEX_OPTION_BUY"):
        assert pl.is_fno(s), s
    for s in ("NSE_EQUITY", "BSE_EQUITY", "MCX_FUTURE", "CRYPTO_OPTION_BUY", "CRYPTO_SPOT", ""):
        assert not pl.is_fno(s), s


def test_switch_and_user_list(monkeypatch):
    vals = {pl.ENABLED_KEY: False, pl.USERS_KEY: ""}

    async def fake_read(key, default):
        return vals.get(key, default)

    monkeypatch.setattr(pl, "_read", fake_read)
    u = SimpleNamespace(user_code="CL1")
    run = lambda: asyncio.run(pl.enabled_for(u))  # noqa: E731
    assert run() is False  # off by default
    vals[pl.ENABLED_KEY] = "true"
    assert run() is True  # on, no list = everyone
    vals[pl.USERS_KEY] = "CL9, CL2"
    assert run() is False  # on, but not on the list
    vals[pl.USERS_KEY] = "cl1"
    assert run() is True


def test_an_existing_position_keeps_its_mode(monkeypatch):
    async def on(_u):
        return True

    monkeypatch.setattr(pl, "enabled_for", on)
    old_cnc = SimpleNamespace(is_pledge=False)
    run = lambda pos: asyncio.run(pl.pledge_mode(None, "NSE_EQUITY", "CNC", pos))  # noqa: E731
    assert run(old_cnc) is False  # adding to an old leveraged row stays leveraged
    assert run(None) is True  # a new row takes the switch
    assert asyncio.run(pl.pledge_mode(None, "NSE_EQUITY", "MIS", None)) is False


def test_the_hooks_are_wired():
    from app.services import order_validator, risk_enforcer, segment_wallet_service, weekly_settlement_service

    assert "_pl.pledge_mode(" in inspect.getsource(order_validator.validate)
    assert "_pl.risk_view(" in inspect.getsource(risk_enforcer._enforce_for_user)
    assert '"is_pledge": {"$ne": True}' in inspect.getsource(segment_wallet_service.segment_float_pnl)
    assert "is_pledge" in inspect.getsource(weekly_settlement_service._settle_one_position)
