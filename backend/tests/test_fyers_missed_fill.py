"""Fyers missed-fill alert: an open LIMIT / SL-M order Fyers shows the market
reaching, still not filled here.

Added at the client's request (Nov 2026). The order-time check only looked at
orders that filled; an order our feed never triggered was never looked at."""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace as Namespace

import pytest
from bson import ObjectId

from app.models.order import OrderAction, OrderType
from app.services import fyers_missed_fill as mf
from app.services import fyers_price_check as fc
from app.services import fyers_service as fs
from app.services import market_data_service, matching_engine

D = Decimal


def _order(order_type="LIMIT", action="BUY", price="100", trigger="0", ref_high=None, ref_low=None, oid=None):
    return Namespace(
        id=oid or ObjectId(), order_number="O1", user_id=ObjectId(), quantity=10,
        order_type=OrderType(order_type), action=OrderAction(action),
        price=D(price), trigger_price=D(trigger),
        range_ref_high=D(ref_high) if ref_high else None,
        range_ref_low=D(ref_low) if ref_low else None,
        instrument=Namespace(token=str((53490 << 8) | 2), symbol="NIFTY26NOVFUT",
                             exchange="NFO", segment="NSE_INDEX_FUTURE", tick_size=D("0.05")),
    )


def _q(ltp=None, bid=None, ask=None, high=None, low=None):
    d = lambda v: D(v) if v else None  # noqa: E731
    return fs.FyersQuote(ltp=d(ltp), bid=d(bid), ask=d(ask), high=d(high), low=d(low))


# ── The rule ──────────────────────────────────────────────────────────
def test_buy_limit_fyers_traded_at_or_below_is_missed():
    past, note = mf.judge(_order(price="100"), _q(ltp="99.5"))
    assert past == D("0.5")
    assert note == "Fyers LTP 99.5 reached the limit 100; order still open"


def test_sell_limit_and_stops_follow_the_level_direction():
    assert mf.judge(_order(action="SELL", price="200"), _q(ltp="200")) is not None
    assert mf.judge(_order(action="SELL", price="200"), _q(ltp="199.95")) is None
    # SL-M BUY is a break-out (upward); SL-M SELL a stop-loss (downward).
    assert mf.judge(_order("SL_M", "BUY", trigger="250"), _q(ltp="250.10")) is not None
    assert mf.judge(_order("SL_M", "SELL", trigger="240"), _q(ltp="239.9")) is not None
    assert mf.judge(_order("SL_M", "SELL", trigger="240"), _q(ltp="240.05")) is None


def test_not_reached_is_not_reported():
    assert mf.judge(_order(price="100"), _q(ltp="100.05", low="100.05")) is None


def test_the_quote_alone_does_not_count():
    # Our poller fills on traded prices, so an ask touching a BUY limit while
    # nothing traded there is not a missed fill.
    assert mf.judge(_order(price="100"), _q(ltp="100.50", ask="100", bid="99.5")) is None


def test_a_day_extreme_after_placement_counts():
    past, note = mf.judge(_order(price="100", ref_low="101"), _q(ltp="100.80", low="99.70"))
    assert past == D("0.30")
    assert note == "Fyers day low 99.70 reached the limit 100 (LTP now 100.80); order still open"


def test_an_extreme_from_before_the_order_does_not_count():
    # The day's low 99 was printed before this BUY LIMIT 100 was parked
    # (watermark low 99 is below the level), as in the poller.
    assert mf.judge(_order(price="100", ref_low="99"), _q(ltp="101", low="99")) is None


def test_without_a_watermark_only_the_ltp_counts():
    assert mf.judge(_order(price="100"), _q(ltp="101", low="99")) is None


def test_no_fyers_ltp_cannot_be_judged():
    assert mf.judge(_order(price="100"), _q(low="99")) is None


# ── The scan ──────────────────────────────────────────────────────────
class _Find:
    def __init__(self, rows):
        self.rows = rows

    async def to_list(self):
        return self.rows


@pytest.fixture
def scan(monkeypatch):
    """A scan wired to fakes. `state["open"]` is what the order collection
    holds; `state["after_grace"]` what it holds when re-read."""
    state: dict = {"open": [], "after_grace": None, "quotes": {}, "calls": [], "closed": False,
                   "reported": [], "rows": [], "events": []}

    async def settings(**_k):
        return Namespace(enabled=True, is_connected=True, access_token="t")

    def find(filt, *_a, **_k):
        if "_id" in filt:
            rows = state["open"] if state["after_grace"] is None else state["after_grace"]
            return _Find(rows)
        return _Find(state["open"])

    async def gate(rows):
        return lambda o: state["closed"]

    async def lookup(exchange, token):
        return "NSE:NIFTY26NOVFUT", None

    async def get_quotes(symbols):
        state["calls"].append(list(symbols))
        return {s: state["quotes"][s] for s in symbols if s in state["quotes"]}

    async def rate_ok():
        return True

    async def no_sleep(_s):
        return None

    async def already(o, level):
        return (str(o.id), str(level)) in state["reported"]

    async def record(o, sym, q, past, note):
        state["rows"].append((o.id, sym, past, note))

    monkeypatch.setattr(fs, "get_settings", settings)
    monkeypatch.setattr(mf.Order, "find", find)
    monkeypatch.setattr(matching_engine, "resting_order_closed_gate", gate)
    monkeypatch.setattr(mf.fyers_symbol_map, "lookup", lookup)
    monkeypatch.setattr(fs, "get_quotes", get_quotes)
    monkeypatch.setattr(fc, "_rate_ok", rate_ok)
    monkeypatch.setattr(mf.asyncio, "sleep", no_sleep)
    monkeypatch.setattr(mf, "_already_reported", already)
    monkeypatch.setattr(mf, "_record", record)
    return state


async def test_an_order_fyers_reached_and_still_open_is_reported(scan):
    o = _order(price="100")
    scan["open"] = [o]
    scan["quotes"] = {"NSE:NIFTY26NOVFUT": _q(ltp="99.90")}
    assert await mf.scan_once() == 1
    assert scan["rows"] == [(o.id, "NSE:NIFTY26NOVFUT", D("0.10"),
                             "Fyers LTP 99.90 reached the limit 100; order still open")]


async def test_an_order_the_poller_fills_during_the_grace_is_not_reported(scan):
    scan["open"] = [_order(price="100")]
    scan["after_grace"] = []  # filled in the meantime
    scan["quotes"] = {"NSE:NIFTY26NOVFUT": _q(ltp="99.90")}
    assert await mf.scan_once() == 0
    assert scan["rows"] == []


async def test_an_order_modified_during_the_grace_is_not_reported(scan):
    o = _order(price="100")
    scan["open"] = [o]
    scan["after_grace"] = [_order(price="98", oid=o.id)]
    scan["quotes"] = {"NSE:NIFTY26NOVFUT": _q(ltp="99.90")}
    assert await mf.scan_once() == 0


async def test_a_closed_market_is_never_scanned(scan):
    scan["open"] = [_order(price="100")]
    scan["closed"] = True
    scan["quotes"] = {"NSE:NIFTY26NOVFUT": _q(ltp="99.90")}
    assert await mf.scan_once() == 0
    assert scan["calls"] == []  # no Fyers request spent


async def test_an_order_is_reported_once(scan):
    o = _order(price="100")
    scan["open"] = [o]
    scan["reported"] = [(str(o.id), "100")]
    scan["quotes"] = {"NSE:NIFTY26NOVFUT": _q(ltp="99.90")}
    assert await mf.scan_once() == 0
    assert scan["calls"] == []  # and no Fyers request is spent on it


async def test_fyers_off_means_no_scan(scan, monkeypatch):
    async def off(**_k):
        return Namespace(enabled=False, is_connected=True, access_token="t")

    monkeypatch.setattr(fs, "get_settings", off)
    scan["open"] = [_order(price="100")]
    assert await mf.scan_once() == 0
    assert scan["calls"] == []


async def test_contracts_share_one_request_per_fifty(scan, monkeypatch):
    syms = iter(f"NSE:C{i}" for i in range(120))
    tok_sym: dict = {}

    async def lookup(exchange, token):
        tok_sym.setdefault(token, next(syms))
        return tok_sym[token], None

    monkeypatch.setattr(mf.fyers_symbol_map, "lookup", lookup)
    orders = []
    for i in range(120):
        o = _order(price="100")
        o.instrument = Namespace(**{**vars(o.instrument), "token": str(((1000 + i) << 8) | 2)})
        orders.append(o)
    scan["open"] = orders
    await mf.scan_once()
    # 120 contracts, capped at 2 requests of 50 this scan.
    assert [len(c) for c in scan["calls"]] == [50, 50]


# ── Fyers batch quotes ────────────────────────────────────────────────
async def test_get_quotes_reads_each_symbol_by_name(monkeypatch):
    async def call(symbols):
        assert symbols == "NSE:A,NSE:B"
        return {"s": "ok", "d": [
            {"n": "NSE:A", "s": "ok", "v": {"lp": 10.5, "bid": 10.4, "ask": 10.6,
                                           "high_price": 11, "low_price": 10}},
            {"n": "NSE:B", "s": "error", "v": {}},
        ]}

    monkeypatch.setattr(fs, "_quotes_call", call)
    out = await fs.get_quotes(["NSE:A", "NSE:B"])
    assert list(out) == ["NSE:A"]
    assert (out["NSE:A"].ltp, out["NSE:A"].high, out["NSE:A"].low) == (D("10.5"), D("11"), D("10"))


async def test_get_quote_still_works_for_one_symbol(monkeypatch):
    async def call(symbols):
        return {"s": "ok", "d": [{"n": symbols, "s": "ok", "v": {"lp": 5}}]}

    monkeypatch.setattr(fs, "_quotes_call", call)
    assert (await fs.get_quote("NSE:X")).ltp == D("5")


# ── Recording ─────────────────────────────────────────────────────────
async def test_a_missed_fill_row_is_saved_and_the_super_admin_alerted(monkeypatch):
    from beanie import init_beanie
    from mongomock_motor import AsyncMongoMockClient

    from app.models.fyers_price_check import FyersPriceCheck
    from app.models.user import User

    await init_beanie(database=AsyncMongoMockClient()["fyers_missed_test"], document_models=[FyersPriceCheck])
    events: list = []

    async def publish(kind, payload):
        events.append((kind, payload["kind"]))

    async def get_user(_id):
        return Namespace(user_code="CL1", full_name="A")

    async def zq(_t):
        return {"ltp": 100.4, "bid": 100.35, "ask": 100.45}

    monkeypatch.setattr(mf, "publish_admin_event", publish)
    monkeypatch.setattr(User, "get", get_user)
    monkeypatch.setattr(market_data_service, "get_quote", zq)
    mf._reported.clear()

    o = _order(price="100")
    await mf._record(o, "NSE:NIFTY26NOVFUT", _q(ltp="99.90", low="99.80"), D("0.10"), "note")
    row = await FyersPriceCheck.find_one({"order_id": o.id})
    assert (row.status.value, row.order_type, row.user_code) == ("MISSED_FILL", "LIMIT", "CL1")
    assert row.trade_id is None
    assert row.level_price.to_decimal() == D("100")
    assert row.zerodha_ltp.to_decimal() == D("100.4")
    assert events == [("price_mismatch", "missed_fill")]
    # Found again in the DB after a restart (memory cleared).
    mf._reported.clear()
    assert await mf._already_reported(o, D("100")) is True
    assert await mf._already_reported(_order(price="100"), D("100")) is False
