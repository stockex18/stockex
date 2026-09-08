"""Dual-account feed failover — the fix for a feed with nothing behind it.

One Kite account is a scheduled single point of failure: the access token dies
every morning around 07:00 IST, and a half-open socket can go silent
mid-session while still reporting `connected`. Either way the price stops and
there is no second source.

Two accounts, tokens routed per exchange, each exchange failing over to the
survivor. The two things that must be right:

  * health is TICK-based, because `connected` is exactly the flag that lies in
    the failure we are guarding against
  * the route is DEBOUNCED, because thrashing re-subscriptions is its own
    outage
"""

from __future__ import annotations

import inspect
import time

import pytest

from app.models.zerodha_feed_routing import (
    DEFAULT_EXCHANGE_ACCOUNT_MAP,
    ZerodhaFeedRouting,
)
from app.services.zerodha_service import ZerodhaService

KEY_A, KEY_B = "keyA", "keyB"


@pytest.fixture
def z():
    """A service with two configured accounts and no real sockets."""
    s = ZerodhaService()
    s._account_api_key = {0: KEY_A, 1: KEY_B}
    s._routing_map = dict(DEFAULT_EXCHANGE_ACCOUNT_MAP)
    s._health_stale_sec = 15.0
    return s


def _entry(key, connected=True, tokens=None):
    return {
        "api_key": key,
        "connected": connected,
        "connecting": False,
        "tokens": set(tokens or []),
        "task": None,
        "label": key,
    }


# ── routing defaults ──────────────────────────────────────────────────
def test_mcx_sits_on_its_own_account():
    """The whole point of the second account: MCX must not compete with NSE
    for slots on one 3000-token socket."""
    assert DEFAULT_EXCHANGE_ACCOUNT_MAP["MCX"] == 1
    assert {DEFAULT_EXCHANGE_ACCOUNT_MAP[e] for e in ("NSE", "BSE", "NFO", "BFO")} == {0}


def test_the_kill_switch_collapses_everything_onto_account_a(z):
    """One flag has to restore the old single-account behaviour exactly."""
    z._failover_enabled_cache = False
    z._effective_route = {"MCX": 1}
    assert z.resolve_target_account("MCX") == 0


def test_the_effective_route_wins_over_the_desired_one(z):
    z._effective_route = {"MCX": 0}
    assert z.resolve_target_account("MCX") == 0


def test_an_unrouted_exchange_falls_back_to_a(z):
    assert z.resolve_target_account("SOMETHING_NEW") == 0


# ── tick-based health ─────────────────────────────────────────────────
def test_an_unconfigured_account_is_never_healthy(z):
    z._account_api_key[1] = ""
    assert z.account_healthy(1) is False


def test_a_disconnected_socket_is_unhealthy(z):
    z._tickers = [_entry(KEY_A, connected=False)]
    assert z.account_healthy(0) is False


def test_a_silent_socket_is_unhealthy_while_the_other_ticks(z, monkeypatch):
    """THE case the `connected` flag cannot see: Kite half-open / token
    throttled. The socket is up, it HAS instruments, and no data comes.

    The tokens matter: a socket with nothing subscribed is silent because there
    is nothing to listen to, and that is a different thing entirely (below).
    """
    monkeypatch.setattr(ZerodhaService, "_feed_expected_now", staticmethod(lambda: True))
    z._tickers = [_entry(KEY_A, tokens=[1, 2, 3]), _entry(KEY_B, tokens=[4, 5])]
    now = time.monotonic()
    z._last_tick_at_by_api_key = {KEY_A: now - 60, KEY_B: now}
    assert z.account_healthy(0) is False
    assert z.account_healthy(1) is True


def test_a_socket_with_nothing_subscribed_is_not_called_broken(z, monkeypatch):
    """Account B, freshly logged in: connected, zero tokens, and therefore
    silent. Judging it down was a trap that closed on itself - a down account
    never receives its exchange, so it could never start ticking and never get
    back up. It stayed UNHEALTHY with MCX permanently failed over to A."""
    monkeypatch.setattr(ZerodhaService, "_feed_expected_now", staticmethod(lambda: True))
    z._tickers = [_entry(KEY_A, tokens=[1, 2, 3]), _entry(KEY_B)]
    now = time.monotonic()
    z._last_tick_at_by_api_key = {KEY_A: now}
    assert z.account_healthy(1) is True


def test_an_empty_socket_that_is_disconnected_is_still_broken(z, monkeypatch):
    """The exemption is about silence, not about being down."""
    monkeypatch.setattr(ZerodhaService, "_feed_expected_now", staticmethod(lambda: True))
    z._tickers = [_entry(KEY_A, tokens=[1]), _entry(KEY_B, connected=False)]
    z._last_tick_at_by_api_key = {KEY_A: time.monotonic()}
    assert z.account_healthy(1) is False


def test_quiet_everywhere_is_not_a_failure(z, monkeypatch):
    """Pre-open, a halt, a quiet minute. Failing over here would thrash both
    accounts for no reason."""
    monkeypatch.setattr(ZerodhaService, "_feed_expected_now", staticmethod(lambda: True))
    z._tickers = [_entry(KEY_A), _entry(KEY_B)]
    z._last_tick_at_by_api_key = {KEY_A: time.monotonic() - 600}
    assert z.account_healthy(0) is True


def test_outside_the_trading_window_silence_is_normal(z, monkeypatch):
    """Overnight and weekends a connected socket is silent BY DESIGN — this is
    what stops a needless failover every single night."""
    monkeypatch.setattr(ZerodhaService, "_feed_expected_now", staticmethod(lambda: False))
    z._tickers = [_entry(KEY_A), _entry(KEY_B)]
    z._last_tick_at_by_api_key = {KEY_B: time.monotonic()}
    assert z.account_healthy(0) is True


def test_the_window_check_fails_safe():
    """If the clock helper throws, keep the tick check ACTIVE rather than
    declaring everything healthy."""
    src = inspect.getsource(ZerodhaService._feed_expected_now)
    assert "return True" in src.split("except Exception:")[1]


# ── entry selection ───────────────────────────────────────────────────
def test_a_token_goes_to_its_own_accounts_socket(z):
    z._tickers = [_entry(KEY_A), _entry(KEY_B)]
    assert z._find_account_entry_idx_locked(1) == 1


def test_a_full_socket_is_not_offered(z):
    z._tickers = [_entry(KEY_A, tokens=range(ZerodhaService.MAX_TOKENS_PER_WS))]
    assert z._find_account_entry_idx_locked(0) == -1


def test_the_subscribe_path_tries_the_other_account_when_its_own_has_none():
    """That IS the failover, seen from the subscribe side."""
    src = inspect.getsource(ZerodhaService._ws_subscribe)
    assert "self.resolve_target_account(ex)" in src
    assert "self._find_account_entry_idx_locked(1 - target_acct)" in src


def test_least_loaded_still_governs_when_there_is_one_account():
    """No second account configured must behave exactly as before."""
    src = inspect.getsource(ZerodhaService._ws_subscribe)
    assert "if ex and self._account_api_key:" in src
    assert "Least-loaded connected WS with capacity" in src


# ── debounce ──────────────────────────────────────────────────────────
def test_the_debounce_windows_are_asymmetric():
    """Fail over fast, fail back slow — coming back is where the flapping is,
    and a re-subscribe storm is its own outage."""
    f = ZerodhaFeedRouting.model_fields
    down = f["failover_confirm_down_sec"].default
    up = f["failback_confirm_up_sec"].default
    assert down < up, (down, up)


def test_it_never_fails_over_to_an_account_that_is_also_down():
    """Moving tokens onto a dead socket loses the feed instead of saving it."""
    src = inspect.getsource(ZerodhaService.feed_failover_loop)
    assert "and other_healthy" in src


def test_it_snaps_back_immediately_when_the_survivor_dies():
    """Data beats flap-avoidance: if the one we failed onto dies and the
    original is alive, go back now, not in 25 seconds."""
    src = inspect.getsource(ZerodhaService.feed_failover_loop)
    assert "elif not other_healthy and desired_healthy:" in src


# ── moving live tokens ────────────────────────────────────────────────
def test_a_move_unsubscribes_before_it_subscribes():
    """Leaving the token on both sockets doubles the feed for it and wastes a
    slot that is already the scarce resource."""
    src = inspect.getsource(ZerodhaService._apply_routing_moves)
    assert src.index("unsubscribe") < src.index('"a": "subscribe"')


def test_a_moved_token_is_put_back_into_full_mode():
    """Subscribe alone gives LTP-only frames — no OHLC, no depth. The day
    high/low the order gates read would go blank on every moved token."""
    assert "full" in inspect.getsource(ZerodhaService._apply_routing_moves)


def test_a_token_is_never_dropped_when_the_target_is_full():
    """Silently losing a token means a position with no price. It stays where
    it is and the skip is logged."""
    src = inspect.getsource(ZerodhaService._apply_routing_moves)
    assert "skipped_cap += 1" in src
    assert "zerodha_feed_failover_capacity_skip" in src


def test_a_steady_state_moves_nothing(z):
    """Called every 3 seconds — it has to be idempotent."""
    z._tickers = [_entry(KEY_A, tokens=[111]), _entry(KEY_B)]
    z._token_to_ws = {111: 0}
    z._symbol_by_token = {111: {"symbol": "RELIANCE", "exchange": "NSE"}}
    z._effective_route = {"NSE": 0}
    z._apply_routing_moves()
    assert z._token_to_ws == {111: 0}
    assert z._tickers[0]["tokens"] == {111}


def test_a_rerouted_token_actually_moves(z):
    z._tickers = [_entry(KEY_A, tokens=[111]), _entry(KEY_B)]
    z._token_to_ws = {111: 0}
    z._symbol_by_token = {111: {"symbol": "GOLD", "exchange": "MCX"}}
    z._effective_route = {"MCX": 1}
    z._apply_routing_moves()
    assert z._token_to_ws[111] == 1
    assert z._tickers[0]["tokens"] == set()
    assert z._tickers[1]["tokens"] == {111}


def test_a_token_with_no_known_exchange_is_left_where_it_is(z):
    """Nothing to route it by — moving it would be a guess."""
    z._tickers = [_entry(KEY_A, tokens=[111]), _entry(KEY_B)]
    z._token_to_ws = {111: 0}
    z._symbol_by_token = {}
    z._effective_route = {"MCX": 1}
    z._apply_routing_moves()
    assert z._token_to_ws[111] == 0


# ── account-scoped teardown ───────────────────────────────────────────
def test_dropping_one_account_leaves_the_other_alone():
    """`_stop_ticker` is all-or-nothing. Reconnecting a failed account must
    not kill the socket currently carrying the feed."""
    src = inspect.getsource(ZerodhaService.disconnect_account_ws)
    assert 'e.get("api_key") == api_key' in src
    assert "self._ws_subscribe(list(set(dropped)))" in src


def test_the_index_map_is_rebuilt_after_a_structural_change():
    """Removing a non-last pool entry shifts every index after it; stale
    token-to-index pointers would send ticks to the wrong socket."""
    src = inspect.getsource(ZerodhaService.disconnect_account_ws)
    assert "self._reindex_token_map_locked()" in src


def test_reindexing_rebuilds_from_the_entries_themselves(z):
    z._tickers = [_entry(KEY_A, tokens=[111, 222]), _entry(KEY_B, tokens=[333])]
    z._token_to_ws = {111: 9, 222: 9, 333: 9}
    z._reindex_token_map_locked()
    assert z._token_to_ws == {111: 0, 222: 0, 333: 1}


# ── cross-process ─────────────────────────────────────────────────────
def test_status_is_published_because_the_admin_runs_elsewhere():
    """The WS pool lives only in the feed leader; the admin API is served by
    other workers and can see nothing directly."""
    src = inspect.getsource(ZerodhaService.feed_failover_loop)
    assert "FAILOVER_STATUS_KEY" in src and "cache_set" in src


def test_the_admin_test_disconnect_goes_through_the_channel():
    from app.api.v1.admin import zerodha as api

    src = inspect.getsource(api.routing_test_disconnect)
    assert "FAILOVER_CMD_CHANNEL" in src
    assert "publish" in src


def test_only_a_super_admin_can_reroute_or_drop_an_account():
    from app.api.v1.admin import zerodha as api

    for fn in (api.update_routing, api.routing_test_disconnect):
        assert "UserRole.SUPER_ADMIN" in inspect.getsource(fn)


def test_the_routing_map_only_accepts_real_account_indexes():
    """A typo'd 2 would route an exchange to an account that does not exist —
    every one of its tokens would fall off the feed."""
    from app.api.v1.admin import zerodha as api

    assert "if iv in (0, 1):" in inspect.getsource(api.update_routing)


def test_the_loops_run_only_where_the_pool_is():
    from app import main

    src = inspect.getsource(main)
    assert "zerodha_feed_failover" in src and "zerodha_failover_cmd" in src
    assert '("app.services.zerodha_service", "stop_feed_failover")' in src


def test_the_routing_doc_is_registered_with_beanie():
    from app.core import database

    assert "ZerodhaFeedRouting" in inspect.getsource(database)
