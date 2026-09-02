"""Two feed protections ported from the sibling deployment, where price has
never been the complaint.

1. The tick_loop's iteration sets must stay bounded. The Zerodha LRU trim caps
   the WS subscription, but `_subscribed` / `_state` — the sets the loop
   actually walks — were never trimmed with it. They grow all session as
   traders browse option chains, the loop overlays every one of them per pass
   on one core, and every published price goes seconds stale. "Rate ruk jaate
   hain" is a loop that cannot finish its lap, not a dead feed.

2. A garbage price must never reach the risk enforcer. It acts within a second:
   SL/TP or a stop-out fires, the position closes at the junk price, and the
   phantom P&L is booked before anyone can look.
"""

from __future__ import annotations

import pytest

from app.services import market_data_service as mds
from app.services.zerodha_service import zerodha

TOKEN = 999999002


# ── 1. bounded iteration sets ─────────────────────────────────────────
@pytest.fixture
def sets():
    keep_sub, keep_state = set(mds._subscribed), dict(mds._state)
    mds._subscribed.clear()
    mds._state.clear()
    yield
    mds._subscribed.clear()
    mds._subscribed.update(keep_sub)
    mds._state.clear()
    mds._state.update(keep_state)


def _seed(*tokens):
    for t in tokens:
        mds._subscribed.add(str(t))
        mds._state[str(t)] = {"ltp": 1.0}


def test_tokens_outside_the_keep_set_are_dropped(sets):
    _seed(111, 222, 333)
    assert mds.prune_subscribed_numeric({111, 222}) == 1
    assert mds._subscribed == {"111", "222"}
    assert "333" not in mds._state


def test_the_two_sets_are_pruned_together(sets):
    """`_state` alone still costs the loop a pass; `_subscribed` alone leaves a
    token the loop skips. Both or the fix does nothing."""
    _seed(111, 222)
    mds.prune_subscribed_numeric({111})
    assert "222" not in mds._subscribed and "222" not in mds._state


def test_symbol_tokens_are_never_touched(sets):
    """Crypto / forex tokens belong to the other feed and are not what grows."""
    _seed(111, "CRYPTO_BTCUSDT", "FOREX_EURUSD")
    mds.prune_subscribed_numeric({111})
    assert "CRYPTO_BTCUSDT" in mds._subscribed
    assert "FOREX_EURUSD" in mds._state


def test_an_int_keep_set_matches_string_tokens(sets):
    """The WS keeps ints, `_subscribed` keeps strings. A type mismatch here
    would silently drop EVERY token — the loop would go blind."""
    _seed(111, 222)
    assert mds.prune_subscribed_numeric({111, 222}) == 0
    assert mds._subscribed == {"111", "222"}


def test_an_empty_keep_set_clears_only_the_numeric_side(sets):
    _seed(111, "CRYPTO_BTCUSDT")
    mds.prune_subscribed_numeric(set())
    assert mds._subscribed == {"CRYPTO_BTCUSDT"}


def test_the_trim_calls_it_on_both_exits():
    """The early return (already within budget) is the one that was missed —
    a prior trim shrinks the DB and leaves these sets bloated forever."""
    import inspect

    src = inspect.getsource(zerodha.trim_subscriptions_lru)
    assert src.count("prune_subscribed_numeric") == 2


# ── 2. spike filter ───────────────────────────────────────────────────
@pytest.fixture(autouse=True)
def _clean_tick():
    zerodha.ticks_by_token.pop(TOKEN, None)
    yield
    zerodha.ticks_by_token.pop(TOKEN, None)


def feed(price, **extra):
    zerodha._handle_parsed_ticks([{"instrument_token": TOKEN, "last_price": price, **extra}])
    return zerodha.ticks_by_token.get(TOKEN)


def test_a_garbage_price_is_rejected_outright():
    """BANKNIFTY at 58,000 does not print 28."""
    feed(58000.0)
    assert feed(28.0)["ltp"] == 58000.0


def test_an_ordinary_move_is_not_a_spike():
    feed(58000.0)
    assert feed(58600.0)["ltp"] == 58600.0


def test_a_move_right_up_to_the_threshold_is_allowed():
    feed(100.0)
    assert feed(149.0)["ltp"] == 149.0


def test_just_past_the_threshold_is_not():
    feed(100.0)
    assert feed(151.0)["ltp"] == 100.0


def test_a_crash_is_caught_too():
    """The filter is symmetric — a 99% drop is as impossible as a 99% rise."""
    feed(1.14)
    assert feed(26.0)["ltp"] == 1.14


def test_the_price_can_never_get_permanently_stuck():
    """A genuine fast move, or a fresh session after a gap. Once the last-good
    tick is older than the window it is no longer a reference worth trusting."""
    feed(100.0)
    zerodha.ticks_by_token[TOKEN]["received_at"] -= zerodha._SPIKE_STALE_SEC + 1
    assert feed(300.0)["ltp"] == 300.0


def test_the_first_tick_is_always_accepted():
    """Nothing to compare against; refusing it would mean no price at all."""
    assert feed(58000.0)["ltp"] == 58000.0


def test_a_priceless_frame_is_not_a_spike():
    """It carries no price to compare — the carry-forward rule owns that case,
    and the two must not fight over it."""
    feed(58000.0)
    assert feed(0)["ltp"] == 58000.0
