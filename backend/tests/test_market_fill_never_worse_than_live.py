"""A MARKET fill is never worse for the client than the live quote.

28 Oct, SILVERM26NOVFUT BUY 5: the order panel's price was 196,603, a second
old; our live ask was 196,530. The engine honours the screen's price within a
1 % cap — about 1,960 points on silver — so it booked 196,603, 73 against the
client. The screen's price now counts only when it is the same or better.
"""

import inspect
from decimal import Decimal as D

from app.models._base import OrderAction
from app.services import matching_engine as me


def test_a_buy_pays_at_most_the_live_ask():
    assert me._never_worse_than_live(D("196603"), D("196530"), OrderAction.BUY) == D("196530")
    assert me._never_worse_than_live(D("196500"), D("196530"), OrderAction.BUY) == D("196500")


def test_a_sell_gets_at_least_the_live_bid():
    assert me._never_worse_than_live(D("196400"), D("196512"), OrderAction.SELL) == D("196512")
    assert me._never_worse_than_live(D("196550"), D("196512"), OrderAction.SELL) == D("196550")


def test_no_live_quote_keeps_the_price():
    assert me._never_worse_than_live(D("100"), None, OrderAction.BUY) == D("100")


def test_only_market_orders_and_never_an_sl_tp_close():
    src = inspect.getsource(me.execute_market_order)
    i = src.index("fill_price = _never_worse_than_live(")
    guard = src[src.rindex("if order.order_type == OrderType.MARKET", 0, i):i]
    assert '("SL_HIT", "TP_HIT")' in guard
