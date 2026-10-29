"""The opening-bell regression: a stale tick in the minute is not a bad fill.

29 Oct 2026, SILVERMIC26NOVFUT, 09:00 IST. For the first two seconds after
the bell our feed still repeated the last session's quote (ltp 196421), so
the 09:00 minute snapshot read 194817-196421 against an exchange candle of
194700-195751 -- 670 above the high. The SELL at 09:00:45 filled at 194915,
exactly on our bid at that second and inside what the exchange traded. Check
Trades called it FEED_OFF by 670. It must pass; a fill whose own price is
outside the exchange range must still fail.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

from beanie import PydanticObjectId

from app.services import trade_audit_service as svc

_USER = PydanticObjectId()
_TOKEN = "143886855"
_AT = datetime(2026, 10, 29, 3, 30, 45, 405000, tzinfo=timezone.utc)  # 09:00:45 IST

_CANDLES = {
    "09:00": {"o": 195000.0, "h": 195751.0, "l": 194700.0, "c": 195100.0, "v": 1.0},
    "09:01": {"o": 195100.0, "h": 195200.0, "l": 194950.0, "c": 195019.0, "v": 1.0},
}

# The 09:00 snapshot as it sits in production: its high is the stale 196421.
_SNAP = SimpleNamespace(
    token=_TOKEN, timestamp=datetime(2026, 10, 29, 3, 30),
    low=194817.0, high=196421.0,
    bid_low=194721.0, bid_high=195750.0,
    ask_low=194823.0, ask_high=196898.0,
)


class _Q:
    def __init__(self, rows):
        self._rows = rows

    def sort(self, *_):
        return self

    def limit(self, *_):
        return self

    async def to_list(self, *_a, **_k):
        return self._rows


def _trade(price: str):
    return SimpleNamespace(
        id=PydanticObjectId(), trade_number="T1", user_id=_USER, order_id=None,
        instrument=SimpleNamespace(token=_TOKEN, symbol="SILVERMIC26NOVFUT", exchange="MCX"),
        action=SimpleNamespace(value="SELL"), quantity=1.0, price=Decimal(price),
        product_type=SimpleNamespace(value="NRML"), pnl_inr=None, executed_at=_AT,
    )


def _run(monkeypatch, trade, at_second):
    async def candles(tok, day, sem):
        return _CANDLES

    async def quotes(pairs):
        return {(_TOKEN, datetime(2026, 10, 29, 3, 30)): _SNAP}

    async def ticks(trades):
        return {str(trade.id): at_second}

    async def no_fix_targets(bad, by_id):
        return None

    monkeypatch.setattr(svc, "_candles_for_token", candles)
    monkeypatch.setattr(svc, "_our_quotes", quotes)
    monkeypatch.setattr(svc, "_our_ticks", ticks)
    monkeypatch.setattr(svc, "_attach_fix_targets", no_fix_targets)
    monkeypatch.setattr(svc.Trade, "find", lambda *a, **k: _Q([trade]))
    monkeypatch.setattr(
        svc.User, "find",
        lambda *a, **k: _Q([SimpleNamespace(id=_USER, user_code="CL22471117")]),
    )
    return asyncio.run(svc.audit(
        start=datetime(2026, 10, 28), end=datetime(2026, 10, 30), user_id=str(_USER),
    ))


def test_a_stale_tick_in_the_minute_does_not_flag_a_good_fill(monkeypatch):
    t = _trade("194915")
    res = _run(monkeypatch, t, (Decimal("194901"), Decimal("194985")))
    row = res["rows"][0]
    assert row["verdict"] == "OK", row
    assert res["summary"]["feed_off"] == 0
    # The feed's own drift is still reported, just not as a verdict.
    assert row["feed_drift"] == 670.0


def test_a_fill_outside_what_the_exchange_traded_still_fails(monkeypatch):
    # Above the exchange high, and inside our (wrong) quote at that second --
    # so only the feed check can catch it.
    t = _trade("196000")
    res = _run(monkeypatch, t, (Decimal("195900"), Decimal("196100")))
    row = res["rows"][0]
    assert row["verdict"] == "FEED_OFF", row
    assert row["off_by"] == 249.0  # 196000 - 195751
    assert row["suggested_price"] == 195751.0


def test_outside_is_zero_on_and_inside_the_band():
    lo, hi = Decimal("194700"), Decimal("195751")
    assert svc._outside(Decimal("194915"), lo, hi) == 0
    assert svc._outside(lo, lo, hi) == 0
    assert svc._outside(hi, lo, hi) == 0
    assert svc._outside(Decimal("194600"), lo, hi) == Decimal("100")
    assert svc._outside(Decimal("195800"), lo, hi) == Decimal("49")
