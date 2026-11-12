"""Orders on the same contract at the same moment share ONE Fyers quote call.

Regression: the rate-limit check used to be awaited between "is a call
already running for this symbol?" and registering the new call. Every order
in a burst awaited it before any had registered, so 15 orders on one contract
made 8 Fyers calls (the rate cap) and 7 orders were recorded NOT_CHECKED.
Found by a read-only burst test on production, 12 Nov 2026.

Fyers and the Redis rate limiter are replaced with fakes; no network.
"""

from __future__ import annotations

import asyncio
from decimal import Decimal
from types import SimpleNamespace as Namespace

import pytest
import pytest_asyncio
import redis.asyncio as aioredis
from beanie import init_beanie
from bson import ObjectId
from mongomock_motor import AsyncMongoMockClient

from app.core.config import settings
from app.models.fyers_price_check import FyersPriceCheck
from app.services import fyers_price_check as fc
from app.services import fyers_service as fs
from app.services import market_data_service

# The real limiter, kept before the autouse fixture swaps it for a fake.
_real_rate_ok = fc._rate_ok


@pytest.fixture(autouse=True)
def fake_fyers(monkeypatch):
    state = {"calls": [], "rate_checks": 0, "rate_ok": True}

    async def fake_get_quote(sym: str) -> fs.FyersQuote:
        state["calls"].append(sym)
        await asyncio.sleep(0.05)  # a real call takes time; others arrive meanwhile
        return fs.FyersQuote(ltp=Decimal("100"), bid=Decimal("99.95"), ask=Decimal("100.05"))

    async def fake_rate_ok() -> bool:
        state["rate_checks"] += 1
        await asyncio.sleep(0)  # the real check awaits Redis
        return state["rate_ok"]

    monkeypatch.setattr(fs, "get_quote", fake_get_quote)
    monkeypatch.setattr(fc, "_rate_ok", fake_rate_ok)
    fc._inflight.clear()
    yield state
    fc._inflight.clear()


async def test_a_burst_on_one_contract_makes_one_call(fake_fyers):
    quotes = await asyncio.gather(*(fc._shared_quote("NSE:NIFTY26NOVFUT") for _ in range(15)))
    assert fake_fyers["calls"] == ["NSE:NIFTY26NOVFUT"]
    assert fake_fyers["rate_checks"] == 1
    assert all(q.ask == Decimal("100.05") for q in quotes)


async def test_different_contracts_each_get_their_own_call(fake_fyers):
    syms = [f"NSE:S{i}-EQ" for i in range(15)]
    await asyncio.gather(*(fc._shared_quote(s) for s in syms))
    assert sorted(fake_fyers["calls"]) == sorted(syms)


async def test_over_the_rate_cap_everyone_sharing_gets_the_same_skip(fake_fyers):
    fake_fyers["rate_ok"] = False
    results = await asyncio.gather(
        *(fc._shared_quote("NSE:NIFTY26NOVFUT") for _ in range(10)), return_exceptions=True
    )
    assert fake_fyers["calls"] == []
    assert fake_fyers["rate_checks"] == 1
    assert all(isinstance(r, fs.FyersUnavailableError) for r in results)


async def test_after_the_share_window_a_fresh_call_is_made(fake_fyers, monkeypatch):
    monkeypatch.setattr(fc, "_SHARE_WINDOW_SEC", 0.01)
    await fc._shared_quote("NSE:SBIN-EQ")
    await asyncio.sleep(0.02)
    await fc._shared_quote("NSE:SBIN-EQ")
    assert fake_fyers["calls"] == ["NSE:SBIN-EQ", "NSE:SBIN-EQ"]


async def test_one_waiter_cancelled_does_not_cancel_the_others(fake_fyers):
    first = asyncio.create_task(fc._shared_quote("NSE:INFY-EQ"))
    await asyncio.sleep(0)  # let it register the shared call
    second = asyncio.create_task(fc._shared_quote("NSE:INFY-EQ"))
    await asyncio.sleep(0)
    first.cancel()
    q = await second
    assert q.ltp == Decimal("100")
    assert fake_fyers["calls"] == ["NSE:INFY-EQ"]


# ── Rate cap: the client's FREE Fyers plan allows 5/second and 50/minute ──
@pytest.fixture
def fake_windows(monkeypatch):
    """In-memory copy of the Redis script's rule, with a fake clock (ms)."""
    clock = {"now": 0}
    sec: list[int] = []
    minute: list[int] = []

    async def fake_reserve_slot(now_ms, request_id):
        now = clock["now"]
        sec[:] = [t for t in sec if t > now - 1000]
        minute[:] = [t for t in minute if t > now - 60000]
        if len(sec) >= fc._RATE_PER_SEC or len(minute) >= fc._RATE_PER_MIN:
            return False
        sec.append(now)
        minute.append(now)
        return True

    monkeypatch.setattr(fc, "_reserve_slot", fake_reserve_slot)
    return clock


def test_the_caps_sit_under_the_free_plan():
    assert fc._RATE_PER_SEC < 5
    assert fc._RATE_PER_MIN < 50


async def test_no_more_than_the_per_second_cap_in_one_second(fake_windows):
    allowed = [await _real_rate_ok() for _ in range(10)]
    assert sum(allowed) == fc._RATE_PER_SEC


async def test_a_burst_every_second_still_gets_the_whole_minute(fake_windows):
    # Ten tries every second for a minute: refused tries must not use up the
    # minute, so exactly the minute cap gets through.
    allowed = 0
    for second in range(60):
        fake_windows["now"] = second * 1000
        for _ in range(10):
            allowed += await _real_rate_ok()
    assert allowed == fc._RATE_PER_MIN


async def test_the_minute_cap_frees_up_after_a_minute(fake_windows):
    for second in range(60):
        fake_windows["now"] = second * 1000
        for _ in range(fc._RATE_PER_SEC):
            await _real_rate_ok()
    assert await _real_rate_ok() is False
    fake_windows["now"] = 61_000
    assert await _real_rate_ok() is True


async def test_redis_trouble_does_not_switch_the_check_off(monkeypatch):
    async def broken(*a, **k):
        raise ConnectionError("redis down")

    monkeypatch.setattr(fc, "_reserve_slot", broken)
    assert await _real_rate_ok() is True


async def test_the_real_script_on_redis(monkeypatch):
    """Runs the actual Lua against a real Redis; skipped when none is up."""
    r = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
    try:
        await r.ping()
    except Exception:  # noqa: BLE001
        pytest.skip("no Redis available")
    monkeypatch.setattr(fc, "get_redis", lambda: r)
    monkeypatch.setattr(fc, "_RATE_KEY_SEC", "test:fyers:rate_sec")
    monkeypatch.setattr(fc, "_RATE_KEY_MIN", "test:fyers:rate_min")
    await r.delete("test:fyers:rate_sec", "test:fyers:rate_min")
    try:
        # Ten requests in the SAME millisecond are ten requests, not one.
        same_ms = [await fc._reserve_slot(1_000_000, f"id{i}") for i in range(10)]
        assert sum(same_ms) == fc._RATE_PER_SEC
        # Refused tries don't use up the minute.
        total = sum(same_ms)
        for second in range(1, 60):
            for i in range(10):
                total += await fc._reserve_slot(1_000_000 + second * 1000, f"s{second}-{i}")
        assert total == fc._RATE_PER_MIN
    finally:
        await r.delete("test:fyers:rate_sec", "test:fyers:rate_min")
        await r.aclose()


# ── An unexpected error still leaves a NOT_CHECKED row ────────────────
# Before: anything other than a FyersUnavailableError (a bug, a Redis hiccup
# in the symbol lookup) escaped the background task, which only logged it —
# the order got no row at all. Found by a read-only production test.
@pytest_asyncio.fixture
async def recorder(monkeypatch):
    await init_beanie(database=AsyncMongoMockClient()["fyers_test"], document_models=[FyersPriceCheck])
    rows: list = []

    async def fake_insert(self, *a, **k):
        rows.append(self)

    async def fake_publish(*a, **k):
        return None

    async def fake_settings(**k):
        return Namespace(enabled=True)

    async def fake_lookup(exchange, token):
        return "NSE:BANKNIFTY26NOVFUT", None

    async def fake_md_quote(token):
        return {"ltp": 100, "bid": 99.95, "ask": 100.05}

    monkeypatch.setattr(FyersPriceCheck, "insert", fake_insert)
    monkeypatch.setattr(fc, "publish_admin_event", fake_publish)
    monkeypatch.setattr(fs, "get_settings", fake_settings)
    monkeypatch.setattr(fc.fyers_symbol_map, "lookup", fake_lookup)
    monkeypatch.setattr(market_data_service, "get_quote", fake_md_quote)
    return rows


def _order():
    return Namespace(
        id=ObjectId(), order_number="T1", user_id=ObjectId(), quantity=1, created_at=None,
        action=Namespace(value="BUY"),
        instrument=Namespace(token=str((61466 << 8) | 2), symbol="BANKNIFTY26NOVFUT",
                             exchange="NFO", tick_size=Decimal("0.2")),
    )


_USER = Namespace(user_code="U1", full_name="User")


async def _run(order):
    task = fc.start(Namespace(token=order.instrument.token, exchange="NFO"))
    await fc.finish(task, order=order, trade=None, user=_USER)


async def test_an_unexpected_quote_error_is_recorded_not_checked(recorder, monkeypatch):
    async def crash(sym):
        raise RuntimeError("boom")

    monkeypatch.setattr(fs, "get_quote", crash)
    await _run(_order())
    assert [r.status.value for r in recorder] == ["NOT_CHECKED"]
    assert recorder[0].note == "Check error: RuntimeError"


async def test_a_symbol_lookup_failure_is_recorded_not_checked(recorder, monkeypatch):
    async def lookup_down(exchange, token):
        raise ConnectionError("redis down")

    monkeypatch.setattr(fc.fyers_symbol_map, "lookup", lookup_down)
    await _run(_order())
    assert [r.status.value for r in recorder] == ["NOT_CHECKED"]
    assert recorder[0].note == "Symbol lookup failed: ConnectionError"


async def test_a_crashed_snapshot_is_still_recorded(recorder):
    async def crashed():
        raise RuntimeError("boom")

    task = asyncio.ensure_future(crashed())
    await fc.finish(task, order=_order(), trade=None, user=_USER)
    assert [r.status.value for r in recorder] == ["NOT_CHECKED"]
    assert recorder[0].note == "Check failed: RuntimeError"


async def test_a_normal_check_still_works(recorder):
    await _run(_order())
    assert [r.status.value for r in recorder] == ["OK"]
    assert recorder[0].note is None
