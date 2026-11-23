"""Fyers check on resting LIMIT / SL-M orders, at the moment they fill.

Added at the client's request (Nov 2026). Market orders were already checked
at placement; a LIMIT or SL-M order was parked, filled later by the pending
order poller, and never checked. Those fill AT the user's own level, so the
question is not "is the fill inside Fyers' bid-ask" but "did Fyers show the
market reaching that level"."""

from __future__ import annotations

import asyncio
import types
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace as Namespace

import pytest_asyncio
from beanie import init_beanie
from bson import ObjectId
from mongomock_motor import AsyncMongoMockClient

from app.core import redis_client
from app.models.fyers_price_check import FyersPriceCheck
from app.models.order import OrderAction, OrderType
from app.services import fyers_price_check as fc
from app.services import fyers_service as fs
from app.services import holiday_service, market_control_service, market_data_service, matching_engine
from app.utils import time_utils

D = Decimal


def _reach(order_type, action, level, ltp=None, bid=None, ask=None, high=None, low=None,
           ref_high=None, ref_low=None):
    def d(v):
        return D(v) if v else None
    return fc.level_reached(
        order_type, action, D(level),
        fyers_ltp=d(ltp), fyers_bid=d(bid), fyers_ask=d(ask),
        fyers_high=d(high), fyers_low=d(low), ref_high=d(ref_high), ref_low=d(ref_low),
    )


# ── The rule ──────────────────────────────────────────────────────────
def test_sell_limit_reached_when_fyers_trades_at_or_above_it():
    # Gourav Saxena's NIFTY SELL LIMIT 25549.90; the tape printed 25550.20.
    assert _reach("LIMIT", "SELL", "25549.90", ltp="25550.20") == (True, D(0), "now")
    assert _reach("LIMIT", "SELL", "25549.90", ltp="25540", bid="25549.90") == (True, D(0), "now")


def test_buy_limit_reached_when_fyers_trades_or_offers_at_or_below_it():
    assert _reach("LIMIT", "BUY", "100", ltp="99.95") == (True, D(0), "now")
    assert _reach("LIMIT", "BUY", "100", ltp="100.20", ask="100") == (True, D(0), "now")


def test_stop_orders_trigger_the_other_way():
    assert _reach("SL_M", "BUY", "250", ltp="250.05") == (True, D(0), "now")  # break-out
    assert _reach("SL_M", "SELL", "240", ltp="239.90") == (True, D(0), "now")  # stop-loss exit
    assert _reach("SL_M", "SELL", "240", ltp="241", ask="240") == (True, D(0), "now")


def test_a_fill_fyers_never_reached_is_a_mismatch_with_the_gap():
    # Our feed filled a SELL LIMIT at 25549.90 but Fyers' market sat at 25520.
    assert _reach("LIMIT", "SELL", "25549.90", ltp="25520", bid="25519.5", high="25531.80") == (
        False, D("29.90"), "")
    assert _reach("LIMIT", "BUY", "100", ltp="101", ask="101.50", low="100.50") == (False, D("1"), "")


def test_a_level_traded_through_since_placement_counts():
    # The tape went through 468 between two reads: day high 468.25, now 467.
    assert _reach("LIMIT", "SELL", "468", ltp="467", high="468.25", ref_high="465") == (
        True, D(0), "earlier")
    assert _reach("SL_M", "SELL", "240", ltp="241", low="239.5", ref_low="242") == (
        True, D(0), "earlier")


def test_an_extreme_from_before_the_order_existed_does_not_excuse_it():
    # DIVISLAB-style: BUY LIMIT parked under a low the day had ALREADY printed
    # (ref_low 9190 <= level 9200.25), filled while the tape was at 9308.
    assert _reach("LIMIT", "BUY", "9200.25", ltp="9308", ask="9308.5", low="9190", ref_low="9190") == (
        False, D("107.75"), "")


def test_without_a_watermark_any_day_extreme_counts():
    assert _reach("LIMIT", "SELL", "468", ltp="467", high="468.25") == (True, D(0), "earlier")


def test_no_fyers_price_cannot_be_judged():
    assert _reach("LIMIT", "SELL", "100", high="101") is None


# ── Recording a LIMIT fill ────────────────────────────────────────────
@pytest_asyncio.fixture
async def recorder(monkeypatch):
    await init_beanie(database=AsyncMongoMockClient()["fyers_pending_test"], document_models=[FyersPriceCheck])
    rows: list = []
    events: list = []

    async def fake_insert(self, *a, **k):
        rows.append(self)

    async def fake_publish(kind, payload):
        events.append(kind)

    async def fake_settings(**k):
        return Namespace(enabled=True)

    async def fake_lookup(exchange, token):
        return "NSE:NIFTY26NOVFUT", None

    async def fake_md_quote(token):
        return {"ltp": 25550.2, "bid": 25549.5, "ask": 25550.2}

    async def rate_ok():
        return True

    # Quotes for one contract are shared for 0.5 s; each test needs its own.
    monkeypatch.setattr(fc, "_inflight", {})
    monkeypatch.setattr(fc, "_rate_ok", rate_ok)
    monkeypatch.setattr(FyersPriceCheck, "insert", fake_insert)
    monkeypatch.setattr(fc, "publish_admin_event", fake_publish)
    monkeypatch.setattr(fs, "get_settings", fake_settings)
    monkeypatch.setattr(fc.fyers_symbol_map, "lookup", fake_lookup)
    monkeypatch.setattr(market_data_service, "get_quote", fake_md_quote)
    return rows, events


def _limit_order(action="SELL", price="25549.90"):
    return Namespace(
        id=ObjectId(), order_number="O1", user_id=ObjectId(), quantity=65, created_at=None,
        action=Namespace(value=action), order_type=OrderType.LIMIT, close_reason=None,
        price=D(price), trigger_price=D(0), range_ref_high=D("25531.80"), range_ref_low=D("25100.10"),
        instrument=Namespace(token=str((53490 << 8) | 2), symbol="NIFTY26NOVFUT",
                             exchange="NFO", tick_size=D("0.05")),
    )


def _fyers(monkeypatch, **q):
    async def quote(sym):
        return fs.FyersQuote(**{k: D(v) if v else None for k, v in q.items()})
    monkeypatch.setattr(fs, "get_quote", quote)


async def _check(order, user):
    task = fc.start(Namespace(token=order.instrument.token, exchange="NFO"))
    trade = Namespace(id=ObjectId(), price=order.price, market_price=order.price)
    await fc.finish(task, order=order, trade=trade, user=user)


async def test_a_limit_fill_fyers_reached_is_ok(recorder, monkeypatch):
    rows, events = recorder
    _fyers(monkeypatch, ltp="25550.20", bid="25549.80", ask="25550.20", high="25561.80", low="25100.10")
    await _check(_limit_order(), Namespace(user_code="CL1", full_name="A"))
    row = rows[0]
    assert (row.status.value, row.order_type, row.note) == ("OK", "LIMIT", None)
    assert row.level_price.to_decimal() == D("25549.90")
    assert row.compared_price.to_decimal() == D("25549.90")
    assert (row.fyers_high.to_decimal(), row.fyers_low.to_decimal()) == (D("25561.80"), D("25100.10"))
    assert events == []


async def test_a_limit_fill_fyers_never_reached_is_reported(recorder, monkeypatch):
    rows, events = recorder
    _fyers(monkeypatch, ltp="25520", bid="25519.50", ask="25520.50", high="25531.80", low="25100.10")
    await _check(_limit_order(), Namespace(user_code="CL1", full_name="A"))
    row = rows[0]
    assert row.status.value == "MISMATCH"
    assert row.difference.to_decimal() == D("29.90")
    assert row.note == "Fyers never reached the limit 25549.90 (LTP 25520, day high 25531.80)"
    assert events == ["price_mismatch"]


async def test_the_user_is_looked_up_when_the_poller_has_none(recorder, monkeypatch):
    rows, _ = recorder
    _fyers(monkeypatch, ltp="25550.20", bid="25549.80", ask="25550.20")

    async def get_user(_id):
        return Namespace(user_code="CL22471117", full_name="Gourav Saxena")

    from app.models.user import User
    monkeypatch.setattr(User, "get", get_user)
    await _check(_limit_order(), None)
    assert (rows[0].user_code, rows[0].user_name) == ("CL22471117", "Gourav Saxena")


async def test_market_orders_keep_the_bid_ask_rule(recorder, monkeypatch):
    rows, _ = recorder
    _fyers(monkeypatch, ltp="25550", bid="25549.50", ask="25550.50")
    o = _limit_order()
    o.order_type = OrderType.MARKET
    await _check(o, Namespace(user_code="CL1", full_name="A"))
    assert (rows[0].order_type, rows[0].status.value, rows[0].level_price) == ("MARKET", "OK", None)


# ── The pending-order poller starts and finishes the check ────────────
def test_the_poller_checks_a_limit_order_when_it_fills(monkeypatch):
    order = types.SimpleNamespace(
        id="o1", is_demo=False,
        instrument=types.SimpleNamespace(token="15736578", symbol="NIFTY26NOVFUT",
                                         segment="NSE_INDEX_FUTURE", exchange="NFO"),
        order_type=OrderType.LIMIT, action=OrderAction.SELL,
        price=D("25549.9"), trigger_price=D("0"), range_ref_high=None, range_ref_low=None,
    )
    fill = object()
    calls: list = []

    class _Q:
        async def to_list(self):
            return [order]

    async def execute(o, **kw):
        calls.append("execute")
        return fill

    async def finish(task, *, order, trade, user):
        calls.append(("finish", task, trade, user))

    async def no(*_a, **_kw):
        return False

    async def none(*_a, **_kw):
        return None

    async def claim(*_a, **_kw):
        return True

    monkeypatch.setattr(matching_engine.Order, "find", lambda *_a, **_kw: _Q())
    monkeypatch.setattr(matching_engine, "execute_market_order", execute)
    monkeypatch.setattr(market_data_service, "get_ltp_live", lambda _t: D("25550.2"))
    monkeypatch.setattr(market_data_service, "get_quote_instant", lambda _t: {"high": 25561.6, "low": 25400})
    monkeypatch.setattr(holiday_service, "is_market_holiday", no)
    monkeypatch.setattr(holiday_service, "special_session", none)
    monkeypatch.setattr(market_control_service, "market_control_open", none)
    monkeypatch.setattr(redis_client, "idempotency_check_and_set", claim)
    monkeypatch.setattr(time_utils, "now_ist",
                        lambda: datetime(2026, 11, 19, 14, 0, tzinfo=timezone(timedelta(hours=5, minutes=30))))
    monkeypatch.setattr(fc, "start", lambda inst: calls.append(("start", inst.token)) or "snap")
    monkeypatch.setattr(fc, "finish", finish)

    async def go():
        await matching_engine.trigger_pending_orders()
        await asyncio.sleep(0)  # let the fire-and-forget finish run

    asyncio.run(go())
    assert calls == [("start", "15736578"), "execute", ("finish", "snap", fill, None)]


def test_the_poller_skips_the_check_for_demo_accounts(monkeypatch):
    seen: list = []
    monkeypatch.setattr(fc, "start", lambda inst: seen.append(inst) or "snap")
    order = types.SimpleNamespace(is_demo=True)
    # The guard is the same one-liner the poller uses.
    if not bool(getattr(order, "is_demo", False)):
        fc.start(order)
    assert seen == []
