"""Once the bell goes, the price stops moving.

Operator: "market band ho gaya fir LTP ya ask bid nahi hilna chahiye — P&L
hilta hua dikhta hai market band hone ke baad bhi."

Measured on the tick store: NIFTY26SEPFUT kept printing until 15:41:57 (NSE's
closing session runs past the 15:30 bell), and CRUDEOIL jumped the moment MCX
shut — last traded 10216 / 10214 / 10215 swapped for 10215 with the admin
spread laid around Kite's official close (10210 / 10220). Nobody can trade on
either, but both move the screen and the floating P&L.

The super-admin's market-control freeze already holds a segment still. The
bell, the weekend and the holiday calendar now do the same.
"""

from __future__ import annotations

import asyncio
import inspect
from datetime import datetime, timedelta, timezone

import pytest

from app.services import market_data_service as mds
from app.utils import time_utils

IST = timezone(timedelta(hours=5, minutes=30))


@pytest.fixture
def clock(monkeypatch):
    """Pin the segment a token belongs to, and what time it is."""
    state = {"segment": "NSE_INDEX_FUTURE"}

    async def seg(_token):
        return (state["segment"], "SYM")

    async def no_holiday(_seg, _d=None):
        return False

    from app.services import holiday_service

    monkeypatch.setattr(mds, "_segment_for_token", seg)
    monkeypatch.setattr(holiday_service, "is_segment_holiday", no_holiday)

    def at(y, m, d, hh, mm):
        monkeypatch.setattr(time_utils, "now_ist", lambda: datetime(y, m, d, hh, mm, tzinfo=IST))

    return state, at


def _over():
    return asyncio.run(mds._session_over("1"))


def test_during_the_session_nothing_is_frozen(clock):
    _, at = clock
    at(2026, 9, 15, 11, 0)  # Tuesday, NSE open
    assert _over() is False


def test_after_the_bell_the_price_is_held(clock):
    _, at = clock
    at(2026, 9, 15, 15, 45)  # past 15:30, inside NSE's closing session
    assert _over() is True


def test_before_the_open_it_is_still_held(clock):
    _, at = clock
    at(2026, 9, 15, 8, 30)
    assert _over() is True


def test_mcx_keeps_its_own_later_bell(clock):
    state, at = clock
    state["segment"] = "MCX_FUTURE"
    at(2026, 9, 15, 22, 0)  # MCX trades till 23:30
    assert _over() is False
    at(2026, 9, 15, 23, 45)
    assert _over() is True


def test_the_weekend_is_held_all_day(clock):
    _, at = clock
    at(2026, 9, 19, 11, 0)  # Saturday
    assert _over() is True


def test_a_holiday_is_held_all_day(clock, monkeypatch):
    _, at = clock
    at(2026, 9, 15, 11, 0)  # a normal session hour

    async def holiday(_seg, _d=None):
        return True

    from app.services import holiday_service

    monkeypatch.setattr(holiday_service, "is_segment_holiday", holiday)
    assert _over() is True


def test_crypto_and_forex_have_no_bell(clock):
    state, at = clock
    at(2026, 9, 15, 3, 0)
    for seg in ("CRYPTO_SPOT", "CRYPTO_PERPETUAL", "FOREX", "CDS_FUTURE"):
        state["segment"] = seg
        assert _over() is False, seg


def test_an_unknown_token_is_never_frozen(monkeypatch):
    async def none(_token):
        return None

    monkeypatch.setattr(mds, "_segment_for_token", none)
    assert _over() is False


def test_the_tick_loop_keeps_mirroring_after_the_bell():
    """It must NOT hold at the bell.

    With the REST fetch gone, the leader's state only moves when a real tick
    lands — so the loop can keep running, and it has to: the mirror it writes
    is what every other worker answers from. Holding it meant a cold worker
    fell back to a different number and the two alternated on screen.
    """
    src = inspect.getsource(mds.tick_loop)
    assert "_session_over(token)" not in src
    # The super-admin's market-control freeze is untouched.
    assert "_closed_segs" in src and "mdlive_items.append((token, _held))" in src


def test_the_segment_lookup_is_memoised(monkeypatch):
    """The freeze check runs per token per second — it must not add a Redis
    round-trip to every one of them."""
    calls = {"n": 0}

    async def cache_get(_key):
        calls["n"] += 1
        return {"seg": "NSE_EQUITY", "sym": "RELIANCE"}

    async def cache_set(*_a, **_k):
        return None

    import app.core.redis_client as rc

    monkeypatch.setattr(rc, "cache_get", cache_get)
    monkeypatch.setattr(rc, "cache_set", cache_set)
    mds._seg_memo.clear()

    async def twice():
        return [await mds._segment_for_token("999"), await mds._segment_for_token("999")]

    out = asyncio.run(twice())
    assert out[0] == out[1] == ("NSE_EQUITY", "RELIANCE")
    assert calls["n"] == 1, "second lookup should come from the process memo"


def test_after_the_bell_a_tick_that_arrived_still_counts(monkeypatch):
    """NSE's closing session prints to ~15:41 and those are real trades.

    The operator's own broker app showed BANKNIFTY 56500 CE trading to 546.05
    after 15:30, while our 15:41 carry-forward sweep booked against the 15:30
    price — because the quote had been frozen at the bell. A tick the feed
    actually pushed has to come through.
    """
    async def over(_token):
        return True

    async def zerodha(_token, _base, *, allow_rest=True):
        assert allow_rest is False, "it went out to Kite REST with the market shut"
        return {"token": "1", "ltp": 546.05, "bid": 545.4, "ask": 550.0}

    async def spread(_token, q):
        return q

    async def infoway(_token, _base):
        raise AssertionError("Infoway has no bell to observe here")

    monkeypatch.setattr(mds, "_session_over", over)
    monkeypatch.setattr(mds, "_zerodha_overlay", zerodha)
    monkeypatch.setattr(mds, "_apply_admin_spread", spread)
    monkeypatch.setattr(mds, "_infoway_overlay", infoway)

    out = asyncio.run(mds._overlay_all("1", {"token": "1", "ltp": 549.2}))
    assert out["ltp"] == 546.05


def test_after_the_bell_nothing_is_fetched(monkeypatch):
    """No tick in the cache → whatever we hold, and no round trip upstream."""
    async def over(_token):
        return True

    async def zerodha(_token, base, *, allow_rest=True):
        assert allow_rest is False
        return base

    async def spread(_token, q):
        return q

    monkeypatch.setattr(mds, "_session_over", over)
    monkeypatch.setattr(mds, "_zerodha_overlay", zerodha)
    monkeypatch.setattr(mds, "_apply_admin_spread", spread)

    held = {"token": "1", "ltp": 549.2, "bid": 549.7, "ask": 551.4}
    assert asyncio.run(mds._overlay_all("1", held)) == held


def test_an_open_session_still_overlays(monkeypatch):
    async def not_over(_token):
        return False

    async def infoway(_token, base):
        return dict(base)

    async def zerodha(_token, _base, **_kw):
        return {"token": "1", "ltp": 101.0, "source": "zerodha"}

    async def spread(_token, q):
        return q

    monkeypatch.setattr(mds, "_session_over", not_over)
    monkeypatch.setattr(mds, "_infoway_overlay", infoway)
    monkeypatch.setattr(mds, "_zerodha_overlay", zerodha)
    monkeypatch.setattr(mds, "_apply_admin_spread", spread)

    out = asyncio.run(mds._overlay_all("1", {"token": "1", "ltp": 0}))
    assert out["ltp"] == 101.0


def test_the_bell_is_checked_before_any_overlay():
    src = inspect.getsource(mds._overlay_all)
    assert src.index("_session_over(token)") < src.index("_infoway_overlay(")
    assert src.index("_session_over(token)") < src.index("_zerodha_overlay(")
