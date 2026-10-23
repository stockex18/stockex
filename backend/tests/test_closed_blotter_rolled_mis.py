"""Closed blotter: a fill queues under its POSITION's product.

GOLDTEN26OCTFUT, client CL22471117 (23 Oct complaint). A 9 Oct MIS buy at
150,392 was rolled to carry (NRML) and weekly-settled on 10 Oct, but its
Trade still said MIS, so it sat in the MIS FIFO queue. On 23 Oct the 11:27
MIS close at 141,399 paired with it (−8,993 shown) and the 18:52 close at
141,699 paired with 141,552 instead of 141,606. The wallet was right
(pnl_inr −174.21 / +71.75); only the blotter rows were wrong.
"""

import asyncio
import datetime as dt
import types

from bson import ObjectId

import app.models.position as position_model
import app.models.trade as trade_model
from app.models._base import OrderAction, ProductType
from app.services import position_service

UID = str(ObjectId())
TOK = "GOLDTEN"
INST = types.SimpleNamespace(token=TOK, symbol="GOLDTEN26OCTFUT")
MIS, NRML = ProductType("MIS"), ProductType("NRML")


def at(day, h, m, s=0):
    return dt.datetime(2026, 10, day, h, m, s) - dt.timedelta(hours=5, minutes=30)  # IST → UTC


def fill(when, action, product, price, pnl=None):
    return types.SimpleNamespace(
        id=ObjectId(), user_id=UID, instrument=INST, product_type=product, action=OrderAction(action),
        quantity="1", price=str(price), executed_at=when, pnl_inr=None if pnl is None else str(pnl),
        brokerage="21", total_charges=None, superseded_by_reopen=False,
    )


def pos(product, side, opened, closed, avg, ltp, reason=None, qty=0):
    return types.SimpleNamespace(
        id=ObjectId(), instrument=INST, product_type=product, opened_side=OrderAction(side),
        opened_at=opened, closed_at=closed, close_reason=reason, quantity=qty, opening_quantity=1,
        avg_price=str(avg), ltp=str(ltp),
    )


TRADES = [
    fill(at(9, 22, 20, 38), "BUY", MIS, 150392),           # opened MIS, rolled to NRML
    fill(at(12, 10, 45), "BUY", NRML, 149108),
    fill(at(22, 21, 43), "SELL", NRML, 142599, -6654),
    fill(at(23, 11, 14, 49), "BUY", MIS, 141552),
    fill(at(23, 11, 27, 17), "SELL", MIS, 141399, -174),
    fill(at(23, 17, 38, 1), "BUY", MIS, 141606),
    fill(at(23, 18, 52, 23), "SELL", MIS, 141699, 71),
]
POSITIONS = [
    pos(NRML, "BUY", at(9, 22, 20, 38), at(10, 23, 0, 52), 150392, 150519, "WEEKLY_SETTLEMENT", qty=1),
    pos(NRML, "BUY", at(10, 23, 0, 52), at(22, 21, 43), 149806, 142599),
    pos(MIS, "BUY", at(23, 11, 14, 49), at(23, 11, 27, 17), 141552, 141399),
    pos(MIS, "BUY", at(23, 17, 38, 1), at(23, 18, 52, 23), 141606, 141699),
]


class _Q:
    def __init__(self, rows):
        self.rows = rows

    def sort(self, *a):
        return _Q(sorted(self.rows, key=lambda t: t.executed_at, reverse=True))

    def limit(self, n):
        return self

    async def to_list(self):
        return list(self.rows)


def test_each_close_pairs_with_its_own_entry(monkeypatch):
    monkeypatch.setattr(trade_model, "Trade", types.SimpleNamespace(user_id=None, find=lambda *a: _Q(TRADES)))
    monkeypatch.setattr(
        position_model, "Position",
        types.SimpleNamespace(user_id=None, status=None, find=lambda *a: _Q(POSITIONS)),
    )
    rows, _ = asyncio.run(position_service.list_closed_trade_events_fifo(UID, limit=50))
    by_close = {r["close_price"]: r["entry_price"] for r in rows}
    assert by_close[141399.0] == 141552.0  # was 150392 → "−8,993"
    assert by_close[141699.0] == 141606.0  # was 141552
