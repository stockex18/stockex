"""The live feed must carry the 5-level book through to the quote.

The market-depth window reads `quote.depth.bids / asks`. The tick handler used
the Kite book only to derive bid / ask and then dropped it, so during market
hours every live quote had an empty book and the window said "Depth not
available". Only the REST snapshot (no live feed: weekends, pre-open) carried
one, which is why it looked right when checked off-hours.

The book stays OFF the `market:tick` publish: that frame goes to every browser
watching the token, and the window reads the book from the quote endpoint.
"""

from __future__ import annotations

import asyncio
import json

import pytest

import app.core.redis_client as rc
from app.services import market_data_service as mds
from app.services import zerodha_service as zs
from app.services.zerodha_service import zerodha

TOKEN = 999999002


def _book():
    return {
        "buy": [{"price": 100.0 - i * 0.05, "quantity": 10 * (i + 1), "orders": i + 1} for i in range(5)],
        "sell": [{"price": 100.1 + i * 0.05, "quantity": 20 * (i + 1), "orders": i + 2} for i in range(5)],
    }


FULL = {
    "instrument_token": TOKEN,
    "last_price": 100.05,
    "ohlc": {"open": 99.0, "high": 101.0, "low": 98.5, "close": 99.5},
    "volume_traded": 5000,
    "total_buy_quantity": 1500,
    "total_sell_quantity": 900,
    "exchange_timestamp": 1788000000,
    "last_trade_time": 1788000000,
}


@pytest.fixture(autouse=True)
def _clean():
    zerodha.ticks_by_token.pop(TOKEN, None)
    yield
    zerodha.ticks_by_token.pop(TOKEN, None)


def test_a_full_frame_keeps_its_book():
    zerodha._handle_parsed_ticks([{**FULL, "depth": _book()}])
    q = zerodha.ticks_by_token[TOKEN]
    assert len(q["depth"]["buy"]) == 5 and len(q["depth"]["sell"]) == 5
    assert (q["bid"], q["ask"]) == (100.0, 100.1)


def test_a_frame_without_a_book_adds_no_depth_key():
    zerodha._handle_parsed_ticks([FULL])
    assert "depth" not in zerodha.ticks_by_token[TOKEN]


def test_a_priceless_frame_holds_the_book_with_the_price():
    zerodha._handle_parsed_ticks([{**FULL, "depth": _book()}])
    zerodha._handle_parsed_ticks([{"instrument_token": TOKEN, "last_price": 0}])
    q = zerodha.ticks_by_token[TOKEN]
    assert q["ltp"] == 100.05
    assert len(q["depth"]["buy"]) == 5


def test_the_tick_publish_leaves_the_book_out(monkeypatch):
    sent: list[tuple[str, dict]] = []

    async def fake_publish(channel, payload):
        sent.append((channel, payload))

    monkeypatch.setattr(zs, "publish", fake_publish)

    async def run():
        zerodha._handle_parsed_ticks([{**FULL, "depth": _book()}])
        await asyncio.sleep(0)

    asyncio.run(run())
    assert sent, "tick was not published"
    channel, payload = sent[-1]
    assert channel == f"market:tick:{TOKEN}"
    assert "depth" not in payload
    assert payload["bid"] == 100.0  # the rest of the tick is untouched
    # ...and the cached quote still has it.
    assert "depth" in zerodha.ticks_by_token[TOKEN]


def test_the_quote_overlay_serves_the_live_book():
    zerodha._handle_parsed_ticks([{**FULL, "depth": _book()}])
    out = asyncio.run(
        mds._zerodha_overlay(str(TOKEN), mds._empty_quote(str(TOKEN)), allow_rest=False)
    )
    bids, asks = out["depth"]["bids"], out["depth"]["asks"]
    assert len(bids) == 5 and len(asks) == 5
    assert bids[0] == {"price": 100.0, "qty": 10, "orders": 1}
    assert asks[0] == {"price": 100.1, "qty": 20, "orders": 2}
    assert (out["total_buy_qty"], out["total_sell_qty"]) == (1500, 900)


def test_the_mirror_carries_the_book_only_for_watched_tokens(monkeypatch):
    """Every token is mirrored; the book rides along only where it is read."""
    written: dict[str, dict] = {}

    class Pipe:
        def set(self, key, blob, ex=None):
            written[key] = json.loads(blob)

        async def execute(self):
            return None

    class Redis:
        def pipeline(self, transaction=False):
            return Pipe()

    monkeypatch.setattr(rc, "get_redis", Redis)
    book = {
        "bids": [{"price": 100.0, "qty": 10, "orders": 1}],
        "asks": [{"price": 100.1, "qty": 20, "orders": 2}],
    }
    q = {"ltp": 100.05, "depth": book}
    monkeypatch.setattr(mds, "_subscribed", {"111"})
    asyncio.run(mds._write_mdlive_batch([("111", dict(q)), ("222", dict(q))]))
    assert written["mdlive:111"]["depth"] == book
    assert written["mdlive:222"]["depth"] == {"bids": [], "asks": []}
    assert written["mdlive:222"]["ltp"] == 100.05  # still mirrored
