"""Editing a resting order may not hand the user an instant fill.

Operator, with COPPER26SEPFUT at 1374.75 (high 1375.50, low 1367.95):
"high low ke bich lag diya edit karke — yahan se update me kuch bhi lag ja
raha hai."

The high-low band straddles the live price, so "somewhere between high and
low" is a BUY level ABOVE the market — or a SELL level below it — half the
time. The poller fills that on its very next pass, at the price the user was
trying to wait for. The modify endpoint had no validation at all: whatever
price arrived was written to the order.

Placing a MARKET order is how you take the market. Editing a resting order is
not, and the backend now says so rather than trusting the browser to.
"""

from __future__ import annotations

import inspect
from decimal import Decimal as D

from app.api.v1.user import orders as user_orders
from app.models.order import OrderAction, OrderType
from app.services.matching_engine import would_fill_now

LTP = D("1374.75")  # live price; day range that session was 1367.95 - 1375.50


def _buy(level):
    return would_fill_now(OrderType.LIMIT, OrderAction.BUY, LTP, D(level), D("0"))


def _sell(level):
    return would_fill_now(OrderType.LIMIT, OrderAction.SELL, LTP, D(level), D("0"))


def test_a_buy_above_the_market_is_an_instant_fill():
    # Inside the day's range, but above the live price.
    assert _buy("1375.00") is True
    assert _buy("1375.50") is True


def test_a_buy_below_the_market_rests():
    assert _buy("1370.00") is False
    assert _buy("1367.95") is False


def test_a_sell_below_the_market_is_an_instant_fill():
    assert _sell("1370.00") is True
    assert _sell("1367.95") is True


def test_a_sell_above_the_market_rests():
    assert _sell("1380.00") is False


def test_a_stop_already_through_the_market_is_an_instant_fill():
    # SL-M BUY triggers at or above LTP, so a trigger under the market fires.
    assert would_fill_now(OrderType.SL_M, OrderAction.BUY, LTP, D("0"), D("1370")) is True
    assert would_fill_now(OrderType.SL_M, OrderAction.BUY, LTP, D("0"), D("1380")) is False


def test_the_day_extremes_play_no_part_here():
    # Same rule the poller uses for the plain price cross, and nothing else:
    # this answers "already through the market", not "did the session reach it".
    src = inspect.getsource(would_fill_now)
    assert "_should_fill(order_type, action, ltp, limit_price, trigger_price)" in src


def _modify_src() -> str:
    return inspect.getsource(user_orders.modify)


def test_the_edit_is_refused_before_anything_is_written():
    s = _modify_src()
    assert "would_fill_now(" in s
    assert s.index("would_fill_now(") < s.index("await o.save()")
    # Refused, not quietly filled.
    assert "status_code=400" in s


def test_no_live_price_means_no_judgement():
    s = _modify_src()
    # ltp 0 would make `0 <= limit` true for every BUY — the poller skips those
    # too, so the edit is allowed rather than refused on a dead feed.
    assert "_ltp > 0 and matching_engine.would_fill_now(" in s


def test_changing_only_lots_is_left_alone():
    s = _modify_src()
    assert "if level_moved:" in s
    assert s.index("level_moved = ") < s.index("would_fill_now(")


# ── the operator's stricter rule ─────────────────────────────────────
# "high and low ke beech ka na lage edit karke bhi — pop de ki edit nahi hoga."
# Not just the half that fills: an edit may not point anywhere the session has
# already traded. A BUY goes below the day's low, a SELL above its high.
def test_an_edit_into_the_days_range_is_refused():
    s = _modify_src()
    assert "_day_low <= _level <= _day_high" in s
    assert "inside today's range" in s


def test_the_range_check_runs_before_the_order_is_written():
    s = _modify_src()
    assert s.index("_day_low <= _level <= _day_high") < s.index("await o.save()")
    # And before the watermark is re-stamped, so a refused edit leaves the
    # order exactly as it was.
    assert s.index("_day_low <= _level <= _day_high") < s.index("restamp_range_ref")


def test_an_unknown_range_does_not_block_the_edit():
    s = _modify_src()
    # high/low arrive as 0 on a cold token; judging against that would refuse
    # every edit on an instrument the feed has not filled in yet.
    assert "_day_high > 0 and _day_low > 0" in s


def test_the_refusal_says_where_the_level_may_go():
    s = _modify_src()
    assert "BUY below" in s and "SELL above" in s
