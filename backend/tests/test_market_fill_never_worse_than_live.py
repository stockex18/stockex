"""A MARKET order fills at the market: Fyers' quote when it is there.

Our Zerodha quote is up to a second old (Kite ticks about once a second). On
25-26 Nov CL23171371's GOLD26DECFUT market orders filled on our last tick
while the market had moved: BUY 1,20,430 with the real ask at 1,20,494 (32
points under the bid, 100 qty), SELL 1,20,585 with the real bid at 1,20,544.
Fyers' quote taken at placement matched our NEXT tick every time, so the fill
uses it (operator, 26 Nov). The order panel's price no longer moves a MARKET
fill either way: within the old 1 % cap it was a free ~1,200 a unit on gold.
"""

import asyncio
import inspect
import types
from decimal import Decimal as D

from app.models._base import OrderAction
from app.services import matching_engine as me


def _task(bid, ask, delay=0.0):
    async def snap():
        if delay:
            await asyncio.sleep(delay)
        return types.SimpleNamespace(fyers=types.SimpleNamespace(bid=bid, ask=ask))

    return snap


def side(action, kite, bid=None, ask=None, delay=0.0, none=False):
    async def go():
        t = None if none else asyncio.ensure_future(_task(bid, ask, delay)())
        return await me._fyers_live_side(t, action, kite)

    return asyncio.run(go())


def test_the_25_nov_buy_fills_at_the_real_ask():
    # Our ask 1,20,430 was a second old; Fyers 1,20,462 - 1,20,494.
    assert side(OrderAction.BUY, D("120430"), D("120462"), D("120494")) == D("120494")


def test_the_25_nov_sell_fills_at_the_real_bid():
    assert side(OrderAction.SELL, D("120585"), D("120544"), D("120578")) == D("120544")


def test_no_fyers_keeps_our_quote():
    assert side(OrderAction.BUY, D("120430"), none=True) is None


def test_a_slow_fyers_keeps_our_quote():
    assert side(OrderAction.BUY, D("120430"), D("120462"), D("120494"), delay=me.FYERS_FILL_WAIT_SEC + 0.2) is None


def test_a_crossed_or_far_off_fyers_quote_is_ignored():
    assert side(OrderAction.BUY, D("120430"), D("120500"), D("120490")) is None  # bid > ask
    assert side(OrderAction.BUY, D("120430"), D("121200"), D("121300")) is None  # 0.72 % away


def test_a_market_order_fills_at_the_live_side_not_the_screen():
    src = inspect.getsource(me.execute_market_order)
    assert "_fyers_live_side(fyers_task, order.action, live_side)" in src
    i = src.index('not in ("SL_HIT", "TP_HIT") and live_side is not None:')
    assert "fill_price = live_side" in src[i : i + 120]
    assert "_never_worse_than_live" not in inspect.getsource(me)


def test_the_order_path_hands_the_fyers_quote_to_the_engine():
    from app.services import order_service

    assert "fyers_task=fyers_check" in inspect.getsource(order_service.place_order)
