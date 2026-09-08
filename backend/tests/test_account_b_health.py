"""A socket with nothing subscribed is silent, not broken.

Account B logged in cleanly - token set, `isConnected` true, socket up - and
the panel still showed UNHEALTHY with "Failover ACTIVE: MCX -> Account A".

    acct 0 (A)  token=set  connected=True  subs=515
    acct 1 (B)  token=set  connected=True  subs=0
    routing     MCX -> 1

The health check calls a connected socket unhealthy when some OTHER account is
ticking and this one is not. B held zero tokens, so it could not tick, so it
was judged down - and a down account never receives its exchange:

    B holds 0 tokens -> B never ticks -> B "UNHEALTHY"
      -> MCX stays failed over to A -> B is never given tokens
      -> back to the start

The tokens had all landed on A because they were subscribed while B was not yet
logged in: the WS router asks `_find_account_entry_idx_locked(1)` first, gets
-1, and falls back to A. Nothing re-checks that later - only a ROUTE change
migrates tokens, and the route could not change while B looked dead.
"""

from __future__ import annotations

import inspect

from app.services.zerodha_service import ZerodhaService

SRC = inspect.getsource(ZerodhaService.account_healthy)


def test_an_empty_socket_is_healthy():
    assert "_tok_count == 0" in SRC
    assert "return True" in SRC[SRC.index("_tok_count == 0"):]


def test_it_is_checked_before_the_tick_comparison():
    """The tick check is what condemns it; the count has to come first."""
    assert SRC.index("_tok_count") < SRC.index("_last_tick_at_by_api_key")


def test_a_disconnected_socket_is_still_unhealthy():
    """The count exemption must not rescue a socket that is actually down."""
    assert SRC.index("if not connected:") < SRC.index("_tok_count")
    i = SRC.index("if not connected:")
    assert "return False" in SRC[i : i + 60]


def test_an_account_with_no_api_key_is_still_unhealthy():
    assert "if not api_key:" in SRC
    i = SRC.index("if not api_key:")
    assert "return False" in SRC[i : i + 60]


def test_a_socket_that_holds_tokens_is_still_judged_on_ticks():
    """The half-open Kite socket this check exists for holds tokens and goes
    quiet - that case must keep working."""
    assert "self._health_stale_sec" in SRC
    assert "feed_live" in SRC


def test_the_route_can_now_reach_b():
    """Once B is healthy the failover loop fails back to it after
    `failback_confirm_up_sec`, and the move is what hands it the tokens."""
    src = inspect.getsource(ZerodhaService.feed_failover_loop)
    assert "_apply_routing_moves()" in src
    assert "_failback_confirm_up_sec" in src


def test_the_router_prefers_the_exchanges_own_account():
    """MCX -> account 1 has always been the intent; it just never had a
    healthy B to resolve to."""
    src = inspect.getsource(ZerodhaService._ws_subscribe)
    assert "self.resolve_target_account(ex)" in src
    assert "_find_account_entry_idx_locked(target_acct)" in src
