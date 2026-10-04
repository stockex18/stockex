"""A crypto price has to be answerable by any worker, not just the leader.

Reported on a Sunday with Zerodha not connected: "Binance se script ke price
nahi aa rahe." Checked from the server, Binance was sending all six
subscribed pairs — 20 frames in 20 seconds for BTCUSDT down to 10 for
XRPUSDT. The feed was never the problem.

Binance, MetaApi, Infoway and Yahoo all run LEADER-ONLY. Each writes its
ticks into `infoway.ticks` — process memory — and publishes them on
`infoway:tick:{sym}`. The other two gunicorn workers subscribed to that
channel but only ever forwarded it to attached WebSocket clients. Their own
`infoway.ticks` stayed empty for the life of the process, so
`_infoway_overlay` found nothing and a REST quote came back unpriced on
roughly two requests in three, at random, depending which worker answered.

What made it look selective rather than broken: BTCUSD and ETHUSD were held
in open positions, so the tick loop mirrors them to `mdlive:{token}` in
Redis, which every worker can read. SOLUSD, XRPUSD and BNBUSD had nobody
holding them, no mirror, and only the leader's memory to fall back on —
248 of 758 crypto instruments mirrored at the time.

Same shape as the day-range gate reading a mirror that 153 of 179 tokens
were missing from. Leader-only in-memory state is fine; letting a request
land on a worker that cannot see it is not.
"""

from __future__ import annotations

import inspect
from types import SimpleNamespace

import pytest

from app.core.ws_hub import MarketTickHub, _BaseHub, market_tick_hub


@pytest.fixture
def cache(monkeypatch):
    import app.services.infoway_service as inf

    fake = SimpleNamespace(ticks={}, depth={})
    monkeypatch.setattr(inf, "infoway", fake)
    return fake


# ── the cache fills on any worker ─────────────────────────────────────
def test_an_infoway_tick_lands_in_this_workers_cache(cache):
    market_tick_hub._observe("infoway:tick:XRPUSDT", {"symbol": "XRPUSDT", "ltp": 2.41})
    assert cache.ticks["XRPUSDT"]["ltp"] == 2.41


def test_a_zerodha_tick_is_left_alone(cache):
    """`market:tick:*` carries Zerodha tokens and has its own mirror. Writing
    them into the symbol-keyed crypto cache would put a token where a symbol
    belongs."""
    market_tick_hub._observe("market:tick:256265", {"token": "256265", "ltp": 100})
    assert cache.ticks == {}


def test_a_tick_with_no_symbol_is_ignored(cache):
    market_tick_hub._observe("infoway:tick:X", {"ltp": 1.0})
    assert cache.ticks == {}


def test_junk_never_raises(cache):
    for channel, payload in (
        (None, {"symbol": "BTCUSDT"}),
        ("infoway:tick:BTCUSDT", None),
        ("infoway:tick:BTCUSDT", "not a dict"),
    ):
        market_tick_hub._observe(channel, payload)
    assert cache.ticks == {}


# ── it has to run before the hub throws the message away ──────────────
def test_the_hook_runs_before_any_routing_decision():
    """The listener drops a message as soon as nothing is routable or nobody
    is attached. A cache that only fills while a WebSocket happens to be
    watching is no cache at all."""
    src = inspect.getsource(_BaseHub._listen_loop)
    assert "_observe(" in src
    assert src.index("_observe(") < src.index("_route_keys(")


def test_the_hook_cannot_stall_the_fanout():
    """This runs on the hot path for every tick on the platform."""
    src = inspect.getsource(_BaseHub._listen_loop)
    block = src[src.index("_observe(") - 200 : src.index("_route_keys(")]
    assert "try:" in block and "except Exception" in block


def test_the_base_hook_does_nothing_by_default():
    """Only the market hub has a cache to keep. The user and admin hubs must
    not pay for this."""
    assert _BaseHub._observe(None, "chan", {"symbol": "X"}) is None
    assert "return None" in inspect.getsource(_BaseHub._observe)


# ── and every worker is actually listening ────────────────────────────
def test_the_hub_subscribes_to_the_feed_channel():
    assert "infoway:tick:*" in inspect.getsource(MarketTickHub._do_subscribe)


def test_the_hubs_start_outside_the_leader_gate():
    """If hub startup sat behind the leader lock, the two workers that need
    this fix most would never run it."""
    from app import main

    src = inspect.getsource(main)
    assert src.index("start_all_hubs()") < src.index("_leader_only(")
