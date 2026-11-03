"""A day still trading must not be judged against half a day of candles.

2 Nov 2026, AXISBANK26NOVFUT. Check Trades was run at about 12:15 and cached
the day's Kite candles as they stood, for 24 hours -- including a 12:15
candle holding one second of trade (1217.9, one lot) and no 12:16. The SELL
LIMIT at 1222.9 that filled at 12:15:41, on its limit and on our quote, then
read "4.70 above the exchange" on every later run. The real 12:15 candle was
1217.8-1222.9.

So: a live day is cached only up to two minutes ago and re-read when a fill
needs a later minute; a fill whose exchange minute is not out yet is "not
checkable yet", never passed and never failed on the exchange side.
"""

from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest
from beanie import PydanticObjectId

import app.core.redis_client as rc
from app.services import trade_audit_service as svc
from app.services import zerodha_service as zs

IST = timezone(timedelta(hours=5, minutes=30))
DAY = date(2026, 11, 3)
KEY = "candles:1:2026-11-03"


class _Clock(datetime):
    NOW: datetime = datetime(2026, 11, 3, 12, 15, 20, tzinfo=IST)

    @classmethod
    def now(cls, tz=None):  # noqa: ARG003
        return cls.NOW


@pytest.fixture
def env(monkeypatch):
    store: dict = {}
    calls: list = []
    state = {"fail": False}

    async def cache_get(k):
        return store.get(k)

    async def cache_set(k, v, ttl_sec=None):  # noqa: ARG001
        store[k] = v

    async def hist(tok, a, b, iv):  # noqa: ARG001
        calls.append(tok)
        if state["fail"]:
            raise RuntimeError("kite down")
        out, t = [], _Clock(2026, 11, 3, 9, 15, tzinfo=IST)
        while t.strftime("%H:%M") <= "15:29":
            out.append({"date": t, "open": 1, "high": 2, "low": 1, "close": 1.5, "volume": 10})
            t += timedelta(minutes=1)
        return out

    monkeypatch.setattr(rc, "cache_get", cache_get)
    monkeypatch.setattr(rc, "cache_set", cache_set)
    monkeypatch.setattr(zs.zerodha, "get_historical", hist)
    monkeypatch.setattr(svc, "_FETCH_SPACING_SEC", 0)
    monkeypatch.setattr(svc, "datetime", _Clock)
    _Clock.NOW = datetime(2026, 11, 3, 12, 15, 20, tzinfo=IST)
    return SimpleNamespace(store=store, calls=calls, state=state)


def _fetch(need, day=DAY):
    return asyncio.run(svc._candles_for_token("1", day, asyncio.Semaphore(3), need))


def test_a_live_day_keeps_only_minutes_that_have_settled(env):
    candles, upto = _fetch("12:14")
    assert upto == "12:13"
    assert max(candles) == "12:13" and "12:15" not in candles


def test_a_copy_that_reaches_far_enough_is_reused(env):
    _fetch("12:10")
    _Clock.NOW += timedelta(minutes=5)
    _fetch("12:10")
    assert len(env.calls) == 1


def test_a_copy_that_stops_short_is_re_read(env):
    _fetch("12:10")
    _Clock.NOW += timedelta(minutes=5)
    _, upto = _fetch("12:19")
    assert len(env.calls) == 2 and upto == "12:18"


def test_kite_is_asked_at_most_every_30_seconds(env):
    _fetch("12:14")
    _Clock.NOW += timedelta(seconds=10)
    _, upto = _fetch("12:16")
    assert len(env.calls) == 1 and upto == "12:13"


def test_a_failed_re_read_keeps_the_old_copy(env):
    _fetch("12:14")
    _Clock.NOW += timedelta(minutes=5)
    env.state["fail"] = True
    candles, upto = _fetch("12:30")
    assert upto == "12:13" and max(candles) == "12:13"


def test_the_next_day_the_copy_becomes_final(env):
    _fetch("12:14")
    _Clock.NOW = datetime(2026, 11, 4, 10, 0, tzinfo=IST)
    candles, upto = _fetch("15:30")
    assert upto is None and max(candles) == "15:29" and env.store[KEY]["complete"]
    n = len(env.calls)
    _fetch("15:30")
    assert len(env.calls) == n


def test_an_old_format_copy_is_not_trusted(env):
    env.store[KEY] = {"12:15": {"o": 1217.9, "h": 1217.9, "l": 1217.9, "c": 1217.9, "v": 625}}
    _fetch("12:00")
    assert len(env.calls) == 1 and env.store[KEY]["v"] == svc._CACHE_VERSION


def test_no_copy_and_kite_down_answers_nothing(env):
    env.state["fail"] = True
    assert _fetch("12:00") == ({}, None)


def test_the_minute_after_2359_does_not_wrap():
    assert svc._next_minute(datetime(2026, 11, 3, 23, 59)) == "23:59"
    assert svc._next_minute(datetime(2026, 11, 3, 12, 15)) == "12:16"


# ---- the audit itself, on the AXISBANK shape ----------------------------

_USER = PydanticObjectId()
_TOKEN = "15745026"
_AT = datetime(2026, 11, 2, 6, 45, 41, 399000, tzinfo=timezone.utc)  # 12:15:41 IST
_SNAP = SimpleNamespace(
    token=_TOKEN, timestamp=datetime(2026, 11, 2, 6, 45),
    low=1217.8, high=1222.9, bid_low=1216.9, bid_high=1222.6, ask_low=1217.7, ask_high=1223.0,
)
_PARTIAL = {  # as the 12:15 run cached it
    "12:14": {"o": 1217.5, "h": 1218.2, "l": 1216.6, "c": 1217.9, "v": 10625.0},
    "12:15": {"o": 1217.9, "h": 1217.9, "l": 1217.9, "c": 1217.9, "v": 625.0},
}
_FULL = {**_PARTIAL,
         "12:15": {"o": 1217.9, "h": 1222.9, "l": 1217.8, "c": 1222.6, "v": 50000.0},
         "12:16": {"o": 1222.6, "h": 1222.6, "l": 1221.1, "c": 1221.4, "v": 20000.0}}


class _Q:
    def __init__(self, rows):
        self._rows = rows

    def sort(self, *_):
        return self

    def limit(self, *_):
        return self

    async def to_list(self, *_a, **_k):
        return self._rows


def _audit(monkeypatch, price, candles, upto, at_second):
    trade = SimpleNamespace(
        id=PydanticObjectId(), trade_number="T1", user_id=_USER, order_id=None,
        instrument=SimpleNamespace(token=_TOKEN, symbol="AXISBANK26NOVFUT", exchange="NFO"),
        action=SimpleNamespace(value="SELL"), quantity=625.0, price=Decimal(price),
        product_type=SimpleNamespace(value="MIS"), pnl_inr=None, executed_at=_AT,
    )

    async def fake_candles(tok, day, sem, need_upto):  # noqa: ARG001
        return candles, upto

    async def quotes(pairs):  # noqa: ARG001
        return {(_TOKEN, datetime(2026, 11, 2, 6, 45)): _SNAP}

    async def ticks(trades):  # noqa: ARG001
        return {str(trade.id): at_second}

    async def no_fix_targets(bad, by_id):  # noqa: ARG001
        return None

    monkeypatch.setattr(svc, "_candles_for_token", fake_candles)
    monkeypatch.setattr(svc, "_our_quotes", quotes)
    monkeypatch.setattr(svc, "_our_ticks", ticks)
    monkeypatch.setattr(svc, "_attach_fix_targets", no_fix_targets)
    monkeypatch.setattr(svc.Trade, "find", lambda *a, **k: _Q([trade]))
    monkeypatch.setattr(
        svc.User, "find", lambda *a, **k: _Q([SimpleNamespace(id=_USER, user_code="CL22471117")])
    )
    return asyncio.run(svc.audit(
        start=datetime(2026, 11, 2), end=datetime(2026, 11, 3), user_id=str(_USER),
    ))


def test_a_fill_past_the_published_minutes_is_not_checkable_yet(monkeypatch):
    res = _audit(monkeypatch, "1222.9", _PARTIAL, "12:14", (Decimal("1222.0"), Decimal("1223.0")))
    assert res["rows"] == []
    assert res["summary"]["feed_off"] == 0
    assert "not out yet" in res["skipped"][0]["reason"]


def test_once_the_minutes_are_out_the_axisbank_fill_passes(monkeypatch):
    res = _audit(monkeypatch, "1222.9", _FULL, None, (Decimal("1222.0"), Decimal("1223.0")))
    assert res["rows"][0]["verdict"] == "OK", res["rows"][0]


def test_a_fill_wrong_on_our_own_quote_is_reported_without_waiting(monkeypatch):
    res = _audit(monkeypatch, "1230", _PARTIAL, "12:14", (Decimal("1222.0"), Decimal("1223.0")))
    assert res["rows"][0]["verdict"] == "FILL_OFF"
