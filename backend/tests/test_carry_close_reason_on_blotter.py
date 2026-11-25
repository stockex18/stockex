"""A carry-sweep close reads as one on the Closed blotter, admin and user.

CL97486914, GOLDM26DECFUT: bought 10 on 23 Nov, and the 24 Nov 23:56 carry
sweep squared 3 the wallet could not hold overnight. The position stayed open
(7 carried), so there was no closed Position to take a reason from, the order
carried none, and both blotters said "USER".
"""

import asyncio
import datetime as dt
import inspect
import types

from bson import ObjectId

import app.models.order as order_model
import app.models.position as position_model
import app.models.trade as trade_model
from app.models._base import OrderAction, ProductType
from app.models.order import order_reason_code
from app.services import position_service

UID = str(ObjectId())
INST = types.SimpleNamespace(token="GOLDM", symbol="GOLDM26DECFUT")
NRML = ProductType("NRML")
OPEN_ORDER, CLOSE_ORDER = ObjectId(), ObjectId()


def at(day, h, m, s=0):
    return dt.datetime(2026, 11, day, h, m, s) - dt.timedelta(hours=5, minutes=30)


def fill(when, action, qty, price, order_id, pnl=None):
    return types.SimpleNamespace(
        id=ObjectId(), user_id=UID, instrument=INST, product_type=NRML, action=OrderAction(action),
        quantity=str(qty), price=str(price), executed_at=when, pnl_inr=None if pnl is None else str(pnl),
        brokerage="73.28", total_charges=None, superseded_by_reopen=False, order_id=order_id,
    )


class _Q:
    def __init__(self, rows):
        self.rows = rows

    def sort(self, *a):
        return _Q(sorted(self.rows, key=lambda t: t.executed_at, reverse=True))

    def limit(self, n):
        return self

    async def to_list(self):
        return list(self.rows)


def _blotter(monkeypatch, close_order):
    trades = [
        fill(at(23, 21, 31, 46), "BUY", 10, 126593, OPEN_ORDER),
        fill(at(24, 23, 56, 41), "SELL", 3, 122130, CLOSE_ORDER, pnl="-13389"),
    ]
    monkeypatch.setattr(trade_model, "Trade", types.SimpleNamespace(user_id=None, find=lambda *a: _Q(trades)))
    # Still open (7 carried): no CLOSED position to match the close against.
    monkeypatch.setattr(position_model, "Position",
                        types.SimpleNamespace(user_id=None, status=None, find=lambda *a: _Q([])))
    monkeypatch.setattr(order_model, "Order", types.SimpleNamespace(find=lambda *a: _Q([close_order])))
    rows, _ = asyncio.run(position_service.list_closed_trade_events_fifo(UID, limit=50))
    return rows[0]


def _order(**kw):
    base = dict(id=CLOSE_ORDER, close_reason=None, placed_from="INTRADAY_ROLLOVER", is_squareoff=True)
    base.update(kw)
    return types.SimpleNamespace(**base)


def test_an_old_carry_close_reads_as_carry_forward(monkeypatch):
    assert _blotter(monkeypatch, _order())["close_reason"] == "CARRY_FORWARD"


def test_a_stamped_carry_close_keeps_its_own_reason(monkeypatch):
    row = _blotter(monkeypatch, _order(close_reason="CARRY_FORWARD_PARTIAL"))
    assert row["close_reason"] == "CARRY_FORWARD_PARTIAL"


def test_a_user_close_still_reads_as_the_user(monkeypatch):
    row = _blotter(monkeypatch, _order(placed_from="WEB", is_squareoff=False))
    assert row.get("close_reason") in (None, "USER")


def test_the_users_own_close_button_is_not_auto(monkeypatch):
    """The Close button sends is_squareoff from WEB. It read as "AUTO" for a
    moment (CL97486914, 23 Nov 20:34); it is the user's close."""
    row = _blotter(monkeypatch, _order(placed_from="WEB", is_squareoff=True))
    assert row.get("close_reason") in (None, "USER")


def test_the_rollover_order_code():
    assert order_reason_code(_order()) == "CARRY_FORWARD"
    assert order_reason_code(_order(close_reason="carry_forward_partial")) == "CARRY_FORWARD_PARTIAL"


def test_both_carry_square_paths_stamp_the_order():
    src = inspect.getsource(position_service)
    assert src.count('"placed_from": "INTRADAY_ROLLOVER",') == 2
    assert src.count('"close_reason": close_reason,') >= 2
