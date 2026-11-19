"""Resting orders follow the super-admin's Market Control window, not the
calendar's fixed 15:30.

19 Nov: NIFTY26NOVFUT SELL LIMIT 25549.9 rested from 15:06. Market Control
keeps NSE index futures open until 15:40 and the LTP printed 25550.2 at
15:37:12, but the poller treated NSE as shut from 15:30 and the order sat
until the user cancelled it at 16:07."""

import asyncio
import types
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from app.core import redis_client
from app.models.order import OrderAction, OrderType
from app.services import holiday_service, market_control_service, market_data_service, matching_engine
from app.utils import time_utils

IST = timezone(timedelta(hours=5, minutes=30))


def _run(monkeypatch, hh, mm, mc_open):
    order = types.SimpleNamespace(
        id="o1",
        instrument=types.SimpleNamespace(token="15736578", symbol="NIFTY26NOVFUT", segment="NSE_INDEX_FUTURE"),
        order_type=OrderType.LIMIT, action=OrderAction.SELL,
        price=Decimal("25549.9"), trigger_price=Decimal("0"),
        range_ref_high=None, range_ref_low=None,
    )

    class _Q:
        async def to_list(self):
            return [order]

    fired = []

    async def execute(o, **kw):
        fired.append(kw.get("expected_price"))

    async def no(*_a, **_kw):
        return False

    async def none(*_a, **_kw):
        return None

    async def mc(_row):
        return mc_open

    async def claim(*_a, **_kw):
        return True

    monkeypatch.setattr(matching_engine.Order, "find", lambda *_a, **_kw: _Q())
    monkeypatch.setattr(matching_engine, "execute_market_order", execute)
    monkeypatch.setattr(market_data_service, "get_ltp_live", lambda _t: Decimal("25550.2"))
    monkeypatch.setattr(market_data_service, "get_quote_instant", lambda _t: {"high": 25561.6, "low": 25400})
    monkeypatch.setattr(holiday_service, "is_market_holiday", no)
    monkeypatch.setattr(holiday_service, "special_session", none)
    monkeypatch.setattr(market_control_service, "market_control_open", mc)
    monkeypatch.setattr(redis_client, "idempotency_check_and_set", claim)
    monkeypatch.setattr(time_utils, "now_ist", lambda: datetime(2026, 11, 19, hh, mm, tzinfo=IST))
    asyncio.run(matching_engine.trigger_pending_orders())
    return fired


def test_fills_at_1537_when_market_control_keeps_nse_open_till_1540(monkeypatch):
    assert _run(monkeypatch, 15, 37, mc_open=True) == [Decimal("25549.9")]


def test_market_control_shut_means_nothing_fires(monkeypatch):
    assert _run(monkeypatch, 15, 37, mc_open=False) == []
    assert _run(monkeypatch, 11, 0, mc_open=False) == []


def test_without_market_control_the_calendar_still_decides(monkeypatch):
    assert _run(monkeypatch, 15, 37, mc_open=None) == []  # past the 15:30 bell
    assert _run(monkeypatch, 11, 0, mc_open=None) == [Decimal("25549.9")]
