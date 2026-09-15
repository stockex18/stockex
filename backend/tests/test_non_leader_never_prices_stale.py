"""A worker that is not the feed leader never prices off its own memory.

15 Sep: CRUDEOIL26SEPFUT filled at 9717 (last night's close) at 10:00 IST
while the market traded 9890 — four orders, all on worker 1027517, which had
led the feed at 00:19 and lost it at 06:32. It kept its frozen `_state`, and
`get_quote` only consulted the leader's live mirror when local state was
EMPTY, so a stale non-zero price looked live.
"""

from __future__ import annotations

import asyncio

import pytest

from app.services import market_data_service as mds

TOKEN = "144870151"
STALE = {"token": TOKEN, "ltp": 9717.0, "bid": 9717.0, "ask": 9717.0}
LIVE = {"token": TOKEN, "ltp": 9890.0, "bid": 9889.0, "ask": 9890.0}


@pytest.fixture
def worker(monkeypatch):
    """A worker holding a stale in-memory price, with a controllable mirror."""
    mirror = {"value": None}

    async def read_mdlive(_tok):
        return dict(mirror["value"]) if mirror["value"] else None

    async def attach_last(_tok, q):
        return {**q, "last_ltp": 9717.0}

    monkeypatch.setattr(mds, "_read_mdlive", read_mdlive)
    monkeypatch.setattr(mds, "_attach_last_quote", attach_last)
    monkeypatch.setattr(mds, "_mark_freshness", lambda q: q)
    mds._quote_cache.clear()
    mds._state.clear()
    mds._state[TOKEN] = dict(STALE)
    yield mirror
    mds._state.clear()
    mds._quote_cache.clear()
    mds._is_feed_leader = False


def _quote():
    mds._quote_cache.clear()
    return asyncio.run(mds.get_quote(TOKEN))


def test_a_non_leader_serves_the_leaders_live_price_not_its_memory(worker):
    mds._is_feed_leader = False
    worker["value"] = LIVE
    assert _quote()["ltp"] == 9890.0


def test_a_non_leader_with_no_mirror_has_no_live_price(worker):
    mds._is_feed_leader = False
    worker["value"] = None
    q = _quote()
    assert float(q.get("ltp") or 0) == 0.0  # nothing tradable - never 9717


def test_losing_leadership_wipes_the_frozen_prices(worker):
    mds._is_feed_leader = True
    mds._quote_cache[TOKEN] = (0, dict(STALE))
    mds.set_feed_leader(False)
    assert mds._state == {} and mds._quote_cache == {}


def test_keeping_leadership_keeps_the_prices(worker):
    mds._is_feed_leader = True
    mds.set_feed_leader(True)
    assert mds._state.get(TOKEN) == STALE


def test_the_batch_path_follows_the_same_rule(worker, monkeypatch):
    mds._is_feed_leader = False

    async def empty_mirror(_tokens):
        return {}

    monkeypatch.setattr(mds, "get_quote_batch_mdlive", empty_mirror)
    (q,) = asyncio.run(mds.get_quotes([TOKEN]))
    assert float(q.get("ltp") or 0) == 0.0
