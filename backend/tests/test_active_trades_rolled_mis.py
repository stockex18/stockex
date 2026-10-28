"""Active Trades: an intraday position rolled to carry keeps its own fills.

SILVERMIC26NOVFUT, client CL22471117 (28 Oct). A 5-lot long built from MIS
fills on 27 Oct was rolled to carry (NRML) at the close; its Trades still say
MIS. Active Trades matched fills on the Trade's own product, found none for an
NRML position and fell back to the user's most recent NRML buys from ANY
time: three rows at 198,800 / 227,818 / 227,910 (each from a long-closed
position) with -1,244 / -30,262 / -30,354 P&L, while Positions correctly
showed one 5-lot long at +12,525.80. Same rule as the Closed blotter now: a
fill takes the product of the position that spans it.

Data below is that client's real fill and position history on the token.
"""

import asyncio
import datetime as dt
import types

from bson import ObjectId

import app.api.v1.user.positions as api
from app.models._base import OrderAction, ProductType

UID = ObjectId()
TOK = "143886855"
INST = types.SimpleNamespace(
    token=TOK, symbol="SILVERMIC26NOVFUT", exchange="MCX", segment="MCX_FUT", lot_size=1, tick_size=1,
)


def ts(s):
    return dt.datetime.strptime(s, "%Y-%m-%d %H:%M:%S.%f").replace(tzinfo=dt.timezone.utc)


# (executed_at UTC, action, product, price, qty)
FILLS = [
    ("2026-09-23 14:40:25.876", "BUY", "MIS", 238293, 1),
    ("2026-09-23 14:54:25.219", "SELL", "MIS", 238901, 1),
    ("2026-09-24 04:55:58.496", "BUY", "MIS", 236899, 1),
    ("2026-09-24 16:40:25.984", "BUY", "MIS", 235945, 1),
    ("2026-09-24 16:43:39.541", "SELL", "MIS", 236378, 1),
    ("2026-09-25 09:30:51.562", "SELL", "MIS", 237870, 1),
    ("2026-09-25 09:31:52.402", "SELL", "MIS", 237953, 1),
    ("2026-09-25 09:35:46.632", "BUY", "MIS", 238045, 2),
    ("2026-09-25 09:37:30.870", "BUY", "MIS", 237895, 1),
    ("2026-09-25 10:07:09.997", "SELL", "MIS", 237933, 1),
    ("2026-09-25 10:08:28.482", "SELL", "MIS", 237968, 1),
    ("2026-09-28 14:13:40.442", "SELL", "MIS", 229895, 1),
    ("2026-09-28 14:32:09.541", "BUY", "MIS", 229651, 1),
    ("2026-09-28 15:31:57.088", "SELL", "MIS", 228895, 1),
    ("2026-09-29 03:35:23.480", "BUY", "MIS", 228455, 1),
    ("2026-09-29 08:04:47.156", "SELL", "NRML", 228005, 1),
    ("2026-09-29 08:05:25.557", "BUY", "NRML", 227910, 1),
    ("2026-09-29 08:52:25.336", "BUY", "NRML", 227818, 1),
    ("2026-09-29 08:53:19.834", "SELL", "MIS", 227790, 1),
    ("2026-10-22 07:09:19.757", "SELL", "MIS", 206350, 1),
    ("2026-10-22 07:49:02.521", "BUY", "MIS", 206002, 1),
    ("2026-10-22 13:10:52.513", "SELL", "MIS", 205550, 1),
    ("2026-10-22 13:37:18.318", "BUY", "MIS", 203801, 1),
    ("2026-10-22 16:33:02.189", "BUY", "MIS", 202686, 1),
    ("2026-10-22 16:38:14.293", "SELL", "MIS", 202599, 1),
    ("2026-10-22 17:05:29.575", "SELL", "MIS", 201595, 1),
    ("2026-10-23 03:31:40.894", "BUY", "NRML", 198800, 1),
    ("2026-10-23 05:22:23.427", "BUY", "MIS", 197501, 1),
    ("2026-10-23 05:25:09.541", "BUY", "MIS", 197401, 1),
    ("2026-10-23 05:26:52.288", "BUY", "MIS", 197361, 1),
    ("2026-10-23 05:28:17.326", "BUY", "MIS", 197101, 1),
    ("2026-10-23 05:47:00.343", "SELL", "MIS", 198669, 1),
    ("2026-10-23 05:48:11.096", "SELL", "MIS", 199450, 1),
    ("2026-10-23 06:00:15.073", "SELL", "MIS", 198899, 1),
    ("2026-10-23 06:06:22.357", "SELL", "MIS", 198550, 1),
    ("2026-10-23 14:15:54.486", "BUY", "MIS", 196101, 1),
    ("2026-10-23 15:15:28.588", "SELL", "MIS", 198150, 1),
    ("2026-10-27 04:58:14.368", "SELL", "MIS", 196099, 1),
    ("2026-10-27 05:27:18.184", "BUY", "MIS", 195501, 1),
    ("2026-10-27 05:30:14.908", "BUY", "MIS", 194801, 1),
    ("2026-10-27 05:39:38.791", "SELL", "MIS", 195599, 1),
    ("2026-10-27 05:44:03.395", "SELL", "MIS", 195299, 1),
    ("2026-10-27 06:02:35.819", "BUY", "MIS", 195151, 1),
    ("2026-10-27 06:05:19.328", "BUY", "MIS", 195101, 1),
    ("2026-10-27 06:38:32.329", "BUY", "MIS", 194000, 1),
    ("2026-10-27 06:38:32.503", "BUY", "MIS", 194051, 1),
    ("2026-10-27 06:41:16.625", "BUY", "MIS", 193901, 1),
    ("2026-10-27 06:44:42.130", "BUY", "MIS", 193751, 1),
    ("2026-10-27 13:36:17.891", "SELL", "MIS", 197650, 1),
    ("2026-10-27 16:15:42.808", "BUY", "MIS", 198611, 1),
]

# (product, opened_at UTC, closed_at UTC, or None while still open)
SPANS = [
    ("MIS", "2026-09-23 14:40:25.882", "2026-09-23 14:54:25.225"),
    ("NRML", "2026-09-24 04:55:58.506", "2026-09-26 17:30:40.984"),
    ("MIS", "2026-09-25 09:30:51.567", "2026-09-25 09:35:46.638"),
    ("MIS", "2026-09-25 09:37:30.880", "2026-09-25 10:07:10.003"),
    ("NRML", "2026-09-25 10:08:28.489", "2026-09-26 17:30:41.018"),
    ("NRML", "2026-09-26 17:30:40.984", "2026-09-29 08:04:47.161"),
    ("NRML", "2026-09-26 17:30:41.018", "2026-09-29 08:05:25.563"),
    ("MIS", "2026-09-28 14:13:40.456", "2026-09-28 14:32:09.550"),
    ("NRML", "2026-09-28 15:31:57.095", "2026-09-29 08:52:25.343"),
    ("MIS", "2026-09-29 03:35:23.487", "2026-09-29 08:53:19.840"),
    ("MIS", "2026-10-22 07:09:19.765", "2026-10-22 07:49:02.530"),
    ("MIS", "2026-10-22 13:10:52.521", "2026-10-22 13:37:18.325"),
    ("MIS", "2026-10-22 16:33:02.194", "2026-10-22 16:38:14.303"),
    ("NRML", "2026-10-22 17:05:29.582", "2026-10-23 03:31:40.900"),
    ("MIS", "2026-10-23 05:22:23.434", "2026-10-23 06:06:22.362"),
    ("MIS", "2026-10-23 14:15:54.495", "2026-10-23 15:15:28.596"),
    ("MIS", "2026-10-27 04:58:14.373", "2026-10-27 05:27:18.192"),
    ("MIS", "2026-10-27 05:30:14.928", "2026-10-27 05:39:38.796"),
    ("MIS", "2026-10-27 05:44:03.400", "2026-10-27 06:02:35.825"),
    ("NRML", "2026-10-27 06:05:19.333", None),
]


def _trade(row):
    when, action, product, price, qty = row
    return types.SimpleNamespace(
        id=ObjectId(), user_id=UID, instrument=INST, action=OrderAction(action),
        product_type=ProductType(product), quantity=float(qty), price=str(price),
        executed_at=ts(when), created_at=ts(when), brokerage="0", total_charges=None,
        trade_number=None, target=None, stop_loss=None, order_id=ObjectId(),
    )


def _position(row):
    product, opened, closed = row
    is_open = closed is None
    return types.SimpleNamespace(
        id=ObjectId(), user_id=UID, instrument=INST, product_type=ProductType(product),
        quantity=5.0 if is_open else 0.0, avg_price="195050.84", opened_at=ts(opened),
        closed_at=None if is_open else ts(closed), segment_type="MCX", target=None, stop_loss=None,
        unrealized_pnl="0", margin_used="0", is_open=is_open,
    )


TRADES = [_trade(r) for r in FILLS]
POSITIONS = [_position(r) for r in SPANS]
OLD_CLOSED_NRML_BUYS = {198800.0, 227818.0, 227910.0}


class _Q:
    def __init__(self, rows):
        self.rows = rows

    def sort(self, key):
        return _Q(sorted(self.rows, key=lambda t: t.executed_at, reverse=key.startswith("-")))

    async def to_list(self):
        return list(self.rows)


def _position_find(*args):
    # The open-positions query passes only field comparisons; the span query
    # also passes a raw {"instrument.token": ...} filter.
    if any(isinstance(a, dict) for a in args):
        return _Q(POSITIONS)
    return _Q([p for p in POSITIONS if p.is_open])


def _rows(monkeypatch):
    monkeypatch.setattr(api, "Position", types.SimpleNamespace(user_id=None, status=None, find=_position_find))
    monkeypatch.setattr(api, "Trade", types.SimpleNamespace(find=lambda *a: _Q(TRADES)))

    async def ltp(tok):
        return 197556.0

    async def mark(tok, is_long, ltp_val, *a):
        return ltp_val

    async def settings(*a, **k):
        return {"settings": {}}

    monkeypatch.setattr(api.market_data_service, "get_display_ltp", ltp)
    monkeypatch.setattr(api.market_data_service, "get_usd_inr_rate", lambda: 84.0)
    monkeypatch.setattr(api.position_service, "close_side_mark", mark)
    monkeypatch.setattr(api.netting_service, "get_effective_settings", settings)
    return asyncio.run(api.list_active_trades(types.SimpleNamespace(id=UID))).data


def _entry(row):
    for k in ("price", "entry_price", "avg_price"):
        if row.get(k) is not None:
            return float(row[k])
    raise AssertionError(f"no entry price in {sorted(row)}")


def test_rolled_position_lists_its_own_five_fills(monkeypatch):
    rows = _rows(monkeypatch)
    # The 27 Oct buys still open after the 13:36 sell closed the oldest (195,101).
    assert sorted(_entry(r) for r in rows) == [193751.0, 193901.0, 194000.0, 194051.0, 198611.0]


def test_never_borrows_fills_from_closed_positions(monkeypatch):
    assert not {_entry(r) for r in _rows(monkeypatch)} & OLD_CLOSED_NRML_BUYS
