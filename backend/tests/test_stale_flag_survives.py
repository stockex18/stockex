"""A last-session price must still say it is a last-session price.

Market closed, TCS on screen:

    ltp        0.0        <- deliberate: nothing can execute against it
    last_ltp   2304.0     <- Friday's close, for display
    stale      False      <- wrong

`_attach_last_quote` sets `stale = True` when it substitutes a stored price.
`_mark_freshness` then runs and re-derives the same field from the EXCHANGE
clock — and a fallback quote has no exchange clock, so it took the else-branch
and set `stale = False`, wiping the mark.

Two different questions sharing one field name:

    _attach_last_quote   "this price is from a previous session"
    _mark_freshness      "the exchange stamp on this tick is old"

The batch path (`get_quotes`) never calls the second one, so the same price
came back stale there and fresh from `get_quote`.

Nothing could trade on it either way — ltp/bid/ask stay 0 and the engine's
stale-feed guard holds — but the screen showed Friday's number on Saturday with
no marker on it.
"""

from __future__ import annotations

import inspect

from app.services import market_data_service as mds


def test_a_quote_with_no_exchange_clock_keeps_a_stale_mark_it_already_had():
    q = mds._mark_freshness({"ltp": 0.0, "last_ltp": 2304.0, "stale": True})
    assert q["stale"] is True
    assert q["age_sec"] is None


def test_a_quote_with_no_exchange_clock_and_no_mark_is_still_not_stale():
    """Infoway crypto / forex report no exchange clock at all. Calling those
    stale would blank the segment — the reason the else-branch exists."""
    q = mds._mark_freshness({"ltp": 4430.28, "bid": 4429.78})
    assert q["stale"] is False
    assert q["age_sec"] is None


def test_the_exchange_clock_still_wins_when_there_is_one():
    """A real timestamp is measurable, so it decides — in both directions."""
    import time

    fresh = mds._mark_freshness({"exchange_timestamp": time.time()})
    old = mds._mark_freshness({"exchange_timestamp": time.time() - 600})
    assert fresh["stale"] is False
    assert old["stale"] is True


def test_a_fresh_tick_can_still_clear_a_stale_mark():
    """The fix must not make `stale` sticky — a live tick arriving after a
    fallback has to be able to say so."""
    q = mds._mark_freshness({"stale": True, "exchange_timestamp": __import__("time").time()})
    assert q["stale"] is False


def test_the_fallback_is_what_sets_the_mark():
    src = inspect.getsource(mds._attach_last_quote)
    assert 'out["stale"] = True' in src
    assert 'out["last_ltp"]' in src


def test_the_fallback_never_hands_over_a_tradeable_price():
    """The whole reason `ltp` stays 0: the matching engine's stale-feed guard
    reads it, and the order panel disables BUY/SELL on it. Filling it in from
    the cache would make a previous session's close executable."""
    src = inspect.getsource(mds._attach_last_quote)
    for field in ("ltp", "bid", "ask"):
        assert f'out["{field}"] =' not in src, field
    # only the header OHLC is back-filled
    assert '("open", "high", "low", "prev_close")' in src


def test_freshness_runs_after_the_fallback():
    """Order matters — that is the whole bug. If this ever flips, the fix
    above stops being load-bearing and this test should be revisited."""
    src = inspect.getsource(mds.get_quote)
    assert "_mark_freshness(await _attach_last_quote(token, out))" in src
