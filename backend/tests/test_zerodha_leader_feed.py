"""Zerodha sockets live on the feed leader, and lost tokens come back.

20 Nov: the 08:30 / 09:25 IST logins landed on a worker that was not the feed
leader, so Account A connected where nothing read its ticks. Account B's
reconnect at 08:31 dropped the ~990 failed-over tokens it carried and left
stale `_token_to_ws` pointers, so they were never resubscribed. Most prices
froze at the previous close (bid = ask) while the Feed Routing card still
called Account B HEALTHY."""

import asyncio
import types

from app.core import redis_client
from app.services import market_data_service
from app.services.zerodha_service import FAILOVER_CMD_CHANNEL, ZerodhaService


def _entry(api_key, tokens=(), connected=True, token="tok"):
    return {
        "api_key": api_key,
        "access_token": token,
        "tokens": set(tokens),
        "connected": connected,
        "connecting": False,
        "task": None,
        "ws": None,
        "label": api_key,
    }


def _service(entries):
    z = ZerodhaService()
    z._account_api_key = {0: "A", 1: "B"}
    z._routing_map = {"NFO": 0, "MCX": 1}
    z._effective_route = {"NFO": 0, "MCX": 1}
    z._tickers = entries
    with z._ticker_lock:
        z._reindex_token_map_locked()
    z._schedule_ws_send = lambda *_a, **_kw: None  # no live socket in tests
    return z


def _published(monkeypatch, leader):
    sent = []

    async def publish(channel, payload):
        sent.append((channel, payload))

    monkeypatch.setattr(market_data_service, "is_feed_leader", lambda: leader)
    monkeypatch.setattr(redis_client, "publish", publish)
    return sent


def test_non_leader_hands_connects_to_the_leader(monkeypatch):
    sent = _published(monkeypatch, leader=False)
    z = _service([])

    async def must_not_run(**_kw):
        raise AssertionError("a non-leader opened a Kite socket")

    z._connect_ws_locked = must_not_run

    async def go():
        await z.connect_ws(force=True)
        await z._login_auto_connect()
        await z._account_b_ws_connect("B", "secret-token")
        await z.force_reconnect_ws()

    asyncio.run(go())

    assert [p for _, p in sent] == [
        {"action": "connect", "force": True},
        {"action": "login"},
        {"action": "account_connect", "account": 1},
        {"action": "force_reconnect"},
    ]
    assert all(ch == FAILOVER_CMD_CHANNEL for ch, _ in sent)
    assert "secret-token" not in repr(sent)  # the leader reads tokens from the DB
    assert z._tickers == []


def test_leader_still_connects_itself(monkeypatch):
    sent = _published(monkeypatch, leader=True)
    z = _service([])
    calls = []

    async def connect_locked(*, force):
        calls.append(force)

    z._connect_ws_locked = connect_locked
    asyncio.run(z.connect_ws(force=True))
    assert calls == [True]
    assert sent == []


def test_account_reconnect_rehomes_tokens_instead_of_dropping_them(monkeypatch):
    _published(monkeypatch, leader=True)
    a = _entry("A")
    b_old = _entry("B", tokens={101, 102, 103}, token="old")
    z = _service([a, b_old])
    for t in (101, 102, 103):
        z._symbol_by_token[t] = {"symbol": f"S{t}", "exchange": "NFO"}

    async def spawn(api_key, access_token):
        z._tickers.append(_entry(api_key, connected=False, token=access_token) | {"connecting": True})
        return len(z._tickers) - 1

    z._spawn_ws_connection = spawn
    asyncio.run(z._reconnect_account_ws(1, "B", "new", reason="test"))

    assert b_old not in z._tickers
    # NFO routes to A, which is up, so A carries them until B ticks.
    assert a["tokens"] == {101, 102, 103}
    assert {z._token_to_ws[t] for t in (101, 102, 103)} == {z._tickers.index(a)}


def test_coverage_check_resubscribes_lost_and_stale_tokens(monkeypatch):
    _published(monkeypatch, leader=True)
    z = _service([_entry("A", tokens={1})])
    # A stale pointer: the map says token 2 is on entry 0, but entry 0 lacks it.
    z._token_to_ws[2] = 0

    saved = [
        types.SimpleNamespace(token=t, symbol=f"S{t}", exchange=ex)
        for t, ex in ((1, "NFO"), (2, "NFO"), (3, "MCX"))
    ]

    async def settings(account_index=0):
        return types.SimpleNamespace(subscribedInstruments=saved)

    async def positions():
        return [4], {4: {"symbol": "S4", "exchange": "NFO"}}

    asked = []

    async def subscribe(tokens, symbols=None):
        asked.extend(tokens)
        return len(tokens)

    z._get_settings = settings
    z._open_position_kite_tokens = positions
    z.subscribe_tokens_on_demand = subscribe

    missing = asyncio.run(z._ensure_feed_coverage())

    assert missing == 3
    assert sorted(asked) == [2, 3, 4]
    assert z._coverage_expected_by_acct == {0: 3, 1: 1}


def test_status_flags_an_account_carrying_a_fraction_of_its_tokens(monkeypatch):
    _published(monkeypatch, leader=True)
    z = _service([_entry("A", tokens=range(933)), _entry("B", tokens=range(1000, 1042))])
    z._account_healthy_cache = {0: True, 1: True}
    z._coverage_expected_by_acct = {0: 933, 1: 990}

    accts = z.get_failover_status()["accounts"]

    assert accts["A"]["degraded"] is False
    assert accts["B"]["degraded"] is True
    assert (accts["B"]["subscribed_tokens"], accts["B"]["expected_tokens"]) == (42, 990)


def _self_heal_once(z, settings_by_acct, stop_on):
    """Drive ONE pass of `ws_self_heal_loop`; `stop_on` names the method whose
    call ends the loop. Returns what each patched method was called with."""
    from datetime import datetime, timedelta, timezone

    calls = {}

    async def settings(account_index=0):
        return settings_by_acct[account_index]

    def recorder(name):
        async def _rec(*a, **kw):
            await asyncio.sleep(0)  # let tasks the loop just spawned run
            calls.setdefault(name, []).append((a, kw))
            if name == stop_on:
                z._self_heal_running = False
                z._wake_self_heal()
            return True
        return _rec

    z._get_settings = settings
    z.probe_and_clear_invalid_token = recorder("probe")
    z._reconnect_account_ws = recorder("reconnect")
    z._ensure_feed_coverage = recorder("coverage")
    z.connect_ws = recorder("connect_ws")
    z.reassert_full_mode = lambda *a, **kw: 0
    z._account_b_ws_connect = recorder("b_connect")
    future = datetime.now(timezone.utc) + timedelta(hours=5)
    for s in settings_by_acct.values():
        s.tokenExpiry = future

    async def go():
        await asyncio.wait_for(z.ws_self_heal_loop(interval_sec=0.01), timeout=5)

    asyncio.run(go())
    return calls


def _acct(key, token):
    return types.SimpleNamespace(apiKey=key, accessToken=token, isConnected=True, wsStatus="connected")


def test_self_heal_brings_account_a_back_while_b_carries_the_feed(monkeypatch):
    _published(monkeypatch, leader=True)
    # 20 Nov 07:06: A's socket is gone, B is up and carrying A's exchanges.
    z = _service([_entry("B", tokens={1, 2}, token="b")])
    calls = _self_heal_once(z, {0: _acct("A", "a"), 1: _acct("B", "b")}, stop_on="reconnect")

    (args, kw), = calls["reconnect"]
    assert args[:3] == (0, "A", "a") and kw["reason"] == "self_heal_down"
    assert "connect_ws" not in calls  # a full reconnect would tear B down too
    assert "probe" in calls


def test_self_heal_moves_account_a_onto_a_new_login_token(monkeypatch):
    _published(monkeypatch, leader=True)
    z = _service([_entry("A", tokens={1}, token="yesterday"), _entry("B", token="b")])
    calls = _self_heal_once(z, {0: _acct("A", "today"), 1: _acct("B", "b")}, stop_on="reconnect")

    (args, kw), = calls["reconnect"]
    assert args[:3] == (0, "A", "today") and kw["reason"] == "self_heal_token_changed"


def test_self_heal_on_a_healthy_pool_checks_b_token_and_coverage(monkeypatch):
    _published(monkeypatch, leader=True)
    z = _service([_entry("A", token="a"), _entry("B", token="b-yesterday")])
    calls = _self_heal_once(z, {0: _acct("A", "a"), 1: _acct("B", "b-today")}, stop_on="coverage")

    assert "reconnect" not in calls
    assert "coverage" in calls
    # B's socket is on yesterday's token, so B is reconnected on today's.
    (args, _kw), = calls["b_connect"]
    assert args == ("B", "b-today")
