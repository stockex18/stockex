"""A resting order must sit on the side that WAITS.

Priced through the market, its trigger is already true, so the poller fires it
on the next pass — and a LIMIT books at the price the USER typed, not the
market's. A BUY LIMIT at 8400 against a market of 8366 filled instantly at
8400: 34 points x 100 qty handed away at placement. That is the bug this
guards.
"""

from __future__ import annotations

from decimal import Decimal as D

import pytest

from app.models._base import OrderAction, OrderType
from app.services.order_validator import resting_side_error

MKT = D("8366")


def _lim(action, p):
    return resting_side_error(OrderType.LIMIT, action, D(p), None, MKT)


def _slm(action, t):
    return resting_side_error(OrderType.SL_M, action, D("0"), D(t), MKT)


# ── LIMIT: rests for a pullback ──────────────────────────────────────
def test_buy_limit_above_market_is_blocked():
    """The exact reported case."""
    msg = _lim(OrderAction.BUY, "8400")
    assert msg and "must be BELOW" in msg
    assert "SL-M" in msg  # tells them the right tool


def test_buy_limit_below_market_is_allowed():
    assert _lim(OrderAction.BUY, "8300") is None


def test_sell_limit_below_market_is_blocked():
    msg = _lim(OrderAction.SELL, "8300")
    assert msg and "must be ABOVE" in msg


def test_sell_limit_above_market_is_allowed():
    assert _lim(OrderAction.SELL, "8400") is None


@pytest.mark.parametrize("action", [OrderAction.BUY, OrderAction.SELL])
def test_limit_exactly_at_market_is_blocked(action):
    """`ltp <= limit` / `ltp >= limit` are both true at equality — it fires."""
    assert _lim(action, "8366") is not None


# ── SL-M: the mirror image, rests for a breakout ─────────────────────
def test_buy_slm_below_market_is_blocked():
    msg = _slm(OrderAction.BUY, "8300")
    assert msg and "must be ABOVE" in msg


def test_buy_slm_above_market_is_allowed():
    assert _slm(OrderAction.BUY, "8400") is None


def test_sell_slm_above_market_is_blocked():
    msg = _slm(OrderAction.SELL, "8400")
    assert msg and "must be BELOW" in msg


def test_sell_slm_below_market_is_allowed():
    assert _slm(OrderAction.SELL, "8300") is None


def test_slm_and_limit_are_opposites():
    """Guarding only one lets a user dodge the block by switching type."""
    up = "8400"
    assert _lim(OrderAction.BUY, up) is not None      # limit: too high
    assert _slm(OrderAction.BUY, up) is None          # sl-m: correct


# ── never block on missing information ───────────────────────────────
@pytest.mark.parametrize("mkt", [None, D("0"), D("-1")])
def test_no_market_price_stands_aside(mkt):
    assert resting_side_error(OrderType.LIMIT, OrderAction.BUY, D("8400"), None, mkt) is None


def test_market_order_is_never_touched():
    assert resting_side_error(OrderType.MARKET, OrderAction.BUY, D("8400"), None, MKT) is None


@pytest.mark.parametrize("p", [None, D("0")])
def test_no_price_entered_stands_aside(p):
    assert resting_side_error(OrderType.LIMIT, OrderAction.BUY, p, None, MKT) is None


def test_exit_exemption_is_enforced_by_the_caller():
    import inspect

    from app.services import order_validator

    src = inspect.getsource(order_validator.validate)
    i = src.index("resting_side_error")
    window = src[max(0, i - 900) : i]
    assert "not is_squareoff" in window and "not is_reducing" in window
