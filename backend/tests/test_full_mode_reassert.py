"""Repair for tokens stuck in Kite's reduced (non-FULL) tick mode.

Subscribing is TWO frames — `subscribe`, then `mode: full` — and only the
second turns on depth. The token is recorded as subscribed before either is
sent, so a dropped mode frame leaves it streaming without a book: `bid`/`ask`
collapse to LTP, the terminal shows a zero spread and 0.00% change on every
affected symbol, and MARKET fills fall back to LTP. It only recovered when a
reconnect happened to replay both frames.
"""

from __future__ import annotations

import inspect

from app.services import zerodha_service as zs
from app.services.zerodha_service import ZerodhaService


def _svc(tokens, ticks, connected=True):
    s = ZerodhaService.__new__(ZerodhaService)
    import threading

    s._ticker_lock = threading.RLock()
    s._tickers = [{"connected": connected, "tokens": set(tokens), "ws": object()}]
    s.ticks_by_token = ticks
    s.sent = []
    s._schedule_ws_send = lambda entry, payload: s.sent.append(payload)
    return s


def test_token_without_depth_is_renudged():
    s = _svc([101], {101: {"has_depth": False}})
    assert s.reassert_full_mode() == 1
    assert s.sent == [{"a": "mode", "v": ["full", [101]]}]


def test_token_with_depth_is_left_alone():
    s = _svc([101], {101: {"has_depth": True}})
    assert s.reassert_full_mode() == 0
    assert s.sent == []


def test_token_that_never_ticked_is_left_alone():
    """No tick = illiquid, not a mode problem. Re-sending every 30 s would
    be pure noise."""
    s = _svc([101], {})
    assert s.reassert_full_mode() == 0


def test_tick_without_the_flag_is_left_alone():
    """Predates the flag — unknown, not broken. The next tick classifies it."""
    s = _svc([101], {101: {"ltp": 5}})
    assert s.reassert_full_mode() == 0


def test_only_the_broken_tokens_are_sent():
    s = _svc([1, 2, 3], {1: {"has_depth": True}, 2: {"has_depth": False}, 3: {"has_depth": False}})
    assert s.reassert_full_mode() == 2
    assert sorted(s.sent[0]["v"][1]) == [2, 3]


def test_disconnected_socket_is_skipped():
    s = _svc([101], {101: {"has_depth": False}}, connected=False)
    assert s.reassert_full_mode() == 0
    assert s.sent == []


def test_batch_is_capped():
    toks = list(range(1, 1001))
    s = _svc(toks, {t: {"has_depth": False} for t in toks})
    assert s.reassert_full_mode(max_per_pass=400) == 400


def test_never_raises_on_bad_state():
    s = ZerodhaService.__new__(ZerodhaService)
    import threading

    s._ticker_lock = threading.RLock()
    s._tickers = [{"connected": True, "tokens": None}]
    s.ticks_by_token = {}
    s._schedule_ws_send = lambda *a: None
    assert s.reassert_full_mode() == 0  # swallowed, loop keeps running


def test_repair_runs_from_the_self_heal_loop():
    """A method nobody calls fixes nothing."""
    src = inspect.getsource(zs.ZerodhaService.ws_self_heal_loop)
    assert "reassert_full_mode()" in src


def test_ticks_carry_the_depth_flag():
    """Detection depends on it being written on every WS tick."""
    src = inspect.getsource(zs.ZerodhaService)
    assert '"has_depth": bool(bids and asks)' in src
