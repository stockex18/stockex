"""Crossed bid-ask guard on the B-book market-fill path.

A BUY fills at the ask and a SELL at the bid. That is only sound while
ask >= bid. A stale or mis-merged tick can invert them, and on a crossed quote
the sides point the WRONG way: buy at the LOW ask, sell at the HIGH bid, same
instant, risk-free. A frozen crossed quote can simply be hammered.

Real incident: feed stuck at bid 1352 / ask 1273.40 against a real price near
1313; one account round-tripped 100-500 qty for ~2 minutes and booked ~99,000.
"""

from __future__ import annotations

import inspect
from decimal import Decimal as D

import pytest

from app.services import matching_engine as me
from app.services.matching_engine import is_crossed_quote


def test_the_incident_quote_is_caught():
    assert is_crossed_quote(D("1352"), D("1273.40")) is True


def test_normal_spread_is_untouched():
    assert is_crossed_quote(D("8367"), D("8369")) is False


def test_locked_quote_is_ALLOWED():
    """bid == ask is normal in a thin book, and several feeds emit
    bid = ask = ltp. Using >= would discard nearly every quote."""
    assert is_crossed_quote(D("8368"), D("8368")) is False


@pytest.mark.parametrize(
    "bid,ask",
    [(None, D("100")), (D("100"), None), (None, None)],
)
def test_missing_side_is_not_crossed(bid, ask):
    """Nothing to compare — the existing missing-quote path handles it."""
    assert is_crossed_quote(bid, ask) is False


def test_barely_crossed_is_still_crossed():
    assert is_crossed_quote(D("100.02"), D("100.01")) is True


# ── guards against the specific mistakes this fix is prone to ────────
def test_source_uses_strict_greater_than():
    """`>=` would treat every locked quote as invalid."""
    src = inspect.getsource(is_crossed_quote)
    assert "bid > ask" in src
    assert "bid >= ask" not in src


def test_both_sides_are_discarded_not_one():
    """Leaving either side in place still lets the round-trip come out
    lopsided; both must go so the fill falls through to a single LTP."""
    src = inspect.getsource(me.execute_market_order)
    i = src.index("is_crossed_quote")
    window = src[i : i + 700]
    assert "bid = ask = None" in window


def test_fallback_reference_is_ltp_for_the_slippage_cap():
    """Once bid/ask are gone the anti-tamper cap must compare against LTP,
    or a client that tampers its expected price to the crossed value shows
    0% deviation and sails through."""
    src = inspect.getsource(me.execute_market_order)
    assert "reference = live_side or ltp" in src


def test_guard_runs_before_the_side_is_picked():
    """Discarding after `live_side` is chosen would be a no-op."""
    src = inspect.getsource(me.execute_market_order)
    assert src.index("is_crossed_quote") < src.index("live_side = ask if")
