"""BUY stayed locked after the upper circuit had already lifted.

Operator's spec: lock BUY when the price is AT the upper circuit, and the
moment the price moves off it — "9462 se 9463" — unlock BUY immediately.

It never unlocked on the way UP, and the reason was the band, not the check.
MCX relaxes a circuit intraday: once a contract has sat on its limit through
the cooling-off, the exchange widens the band and trading resumes past the
old level. The band was cached for 12 hours, and every caller asks "is the
price at or past the upper limit":

    CRUDEOIL hits 9462 (uc)   ->  BUY locked           correct
    MCX widens the band       ->  price trades 9463
    cache still says 9462     ->  9463 >= 9462 -> BUY locked, for hours

Measured on the live box, today's CRUDEOIL band is 9334-10110 — 9462 was a
limit the exchange had already moved on from.

Fix: callers pass the price they are judging. Inside the cached band the
cache stands (no network). On or past its edge the band is re-read from Kite,
at most once per window per token, and the fresh band decides.
"""

from __future__ import annotations

import asyncio
import inspect

import pytest

from app.services import order_validator as ov
from app.utils.decimal_utils import to_decimal


class _Inst:
    exchange = "MCX"
    token = "t-crude"
    symbol = "CRUDEOIL26SEPFUT"


@pytest.fixture
def world(monkeypatch):
    """In-memory Redis + a scripted Kite quote, and a counter of Kite calls."""
    import app.core.redis_client as rc
    from app.services.zerodha_service import zerodha

    store: dict = {}
    calls = {"kite": 0}
    live = {"lc": "9000", "uc": "9462"}

    async def cache_get(k):
        return store.get(k)

    async def cache_set(k, v, ttl_sec=None):
        store[k] = v

    async def get_quote(keys):
        calls["kite"] += 1
        if live.get("fail"):
            raise RuntimeError("kite down")
        return {
            keys[0]: {
                "lower_circuit_limit": float(live["lc"]),
                "upper_circuit_limit": float(live["uc"]),
            }
        }

    monkeypatch.setattr(rc, "cache_get", cache_get)
    monkeypatch.setattr(rc, "cache_set", cache_set)
    monkeypatch.setattr(zerodha, "get_quote", get_quote)
    return store, calls, live


def _band(price=None):
    return asyncio.run(ov._circuit_limits(_Inst(), price=price))


def test_the_reported_case_unlocks_once_mcx_relaxes_the_band(world):
    store, calls, live = world
    # Morning: the band is 9000-9462 and gets cached.
    assert _band(9300) == (to_decimal("9000"), to_decimal("9462"))
    # MCX relaxes the band after the lock. The cache still holds 9462.
    live["uc"] = "10110"
    # Price trades 9463 — on/past the CACHED edge, so the band is re-read.
    lc, uc = _band(9463)
    assert uc == to_decimal("10110")
    assert not (to_decimal("9463") >= uc), "BUY must be unlocked at 9463"


def test_a_price_inside_the_band_never_touches_kite(world):
    store, calls, live = world
    _band(9300)                # first read populates the cache
    before = calls["kite"]
    for p in (9100, 9300, 9461):
        _band(p)
    assert calls["kite"] == before


def test_a_price_on_the_limit_is_still_locked_when_nothing_changed(world):
    # The lock itself must keep working: if MCX has NOT relaxed, the fresh
    # band is the same and 9462 is still at the limit.
    store, calls, live = world
    _band(9300)
    lc, uc = _band(9462)
    assert uc == to_decimal("9462")
    assert to_decimal("9462") >= uc


def test_a_pinned_stock_is_refreshed_at_most_once_per_window(world):
    # The order panel polls 3x a second; a stock sitting on its limit must not
    # become a Kite REST call per poll.
    store, calls, live = world
    _band(9300)
    base = calls["kite"]
    for _ in range(20):
        _band(9462)
    assert calls["kite"] == base + 1


def test_a_failed_refresh_keeps_the_band_it_had(world):
    # A Kite blip must not unlock a market that is still locked.
    store, calls, live = world
    _band(9300)
    live["fail"] = True
    assert _band(9462) == (to_decimal("9000"), to_decimal("9462"))


def test_an_empty_fresh_answer_does_not_overwrite_the_band(world):
    store, calls, live = world
    _band(9300)
    live["lc"], live["uc"] = "0", "0"
    assert _band(9462) == (to_decimal("9000"), to_decimal("9462"))


def test_no_price_behaves_exactly_as_before(world):
    # Callers that have no price keep the old cache-only behaviour.
    store, calls, live = world
    _band()
    base = calls["kite"]
    _band()
    assert calls["kite"] == base


def test_every_caller_passes_the_price_it_judges():
    import app.api.v1.user.segment_settings as seg
    from app.services import risk_enforcer as re

    assert "_circuit_limits(instrument, price=cur)" in inspect.getsource(ov)
    assert "_circuit_limits(instrument, price=px)" in inspect.getsource(re._at_circuit)
    assert "_circuit_limits(instrument, price=_circ_px)" in inspect.getsource(seg)


def test_the_gate_computes_the_price_before_reading_the_band():
    src = inspect.getsource(ov)
    i = src.index("_circuit_limits(instrument, price=cur)")
    assert src.rindex("cur = ltp if (ltp and ltp > 0) else ref_price", 0, i) < i
