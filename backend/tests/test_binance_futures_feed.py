"""Gold, silver and the rest of metals / energy from Binance USDT-M futures.

Replaced MetaAPI (an MT5 account that went UNDEPLOYED and left XAUUSD / XAGUSD
at 0) and Yahoo's 10-minute-delayed futures. Ticks are keyed by OUR symbol, so
instruments and open positions are untouched.
"""

import asyncio
import pathlib
import types

import pytest

import app.services.infoway_service as iw
from app.api.v1.user import instruments
from app.services import binance_futures_service as bf

ROOT = pathlib.Path(__file__).resolve().parents[1]


@pytest.fixture
def feed(monkeypatch):
    cache = types.SimpleNamespace(ticks={})
    published = []

    async def publish(channel, tick):
        published.append((channel, tick["ltp"]))

    monkeypatch.setattr(iw, "infoway", cache, raising=False)
    monkeypatch.setattr(bf, "publish", publish)
    svc = bf.BinanceFuturesService()

    def send(event, now):
        asyncio.run(svc.handle({"stream": "x", "data": event}, now=now))

    return svc, cache.ticks, published, send


def book(sym, bid, ask):
    return {"e": "bookTicker", "s": sym, "b": str(bid), "a": str(ask)}


def trade(sym, price):
    return {"e": "aggTrade", "s": sym, "p": str(price)}


def test_our_symbols_map_to_the_real_contracts():
    assert bf.contract_for("XAUUSD") == "XAUUSDT"
    assert bf.contract_for("xagusd") == "XAGUSDT"
    assert bf.contract_for("USOIL") == "CLUSDT"   # WTI — the one nobody guesses
    assert bf.contract_for("UKOIL") == "BZUSDT"   # Brent
    assert bf.contract_for("NATGAS") == "NATGASUSDT"
    assert bf.contract_for("BTCUSD") is None      # crypto stays on Binance spot
    assert bf.contract_for("NIFTY") is None


def test_a_trade_is_the_last_price_and_the_book_is_bid_ask(feed):
    svc, ticks, _, send = feed
    send(book("XAUUSDT", 4197.84, 4197.85), now=100.0)
    send(trade("XAUUSDT", 4197.90), now=100.2)
    t = ticks["XAUUSD"]                     # OUR symbol, not the contract
    assert t["ltp"] == 4197.90
    assert (t["bid"], t["ask"]) == (4197.84, 4197.85)
    assert t["source"] == "binance_futures"
    assert t["symbol"] == "XAUUSD"


def test_after_three_quiet_seconds_the_mid_takes_over(feed):
    svc, ticks, _, send = feed
    send(book("XAGUSDT", 60.36, 60.37), now=100.0)
    send(trade("XAGUSDT", 60.40), now=100.0)
    send(book("XAGUSDT", 60.50, 60.52), now=103.5)
    assert ticks["XAGUSD"]["ltp"] == pytest.approx(60.51)


def test_a_lone_print_far_from_the_book_is_dropped(feed):
    svc, ticks, _, send = feed
    send(book("XAUUSDT", 4000.0, 4000.2), now=100.0)
    send(trade("XAUUSDT", 4100.0), now=100.2)      # 2.5% off the book
    assert ticks["XAUUSD"]["ltp"] == pytest.approx(4000.1)
    send(trade("XAUUSDT", 4001.0), now=100.4)      # a real print is taken
    assert ticks["XAUUSD"]["ltp"] == 4001.0


def test_the_fan_out_is_coalesced_but_the_cache_is_always_latest(feed):
    svc, ticks, published, send = feed
    send(book("CLUSDT", 90.56, 90.57), now=100.00)
    send(trade("CLUSDT", 90.57), now=100.03)
    send(trade("CLUSDT", 90.58), now=100.06)
    assert ticks["USOIL"]["ltp"] == 90.58          # cache: every event
    assert published == [("infoway:tick:USOIL", pytest.approx(90.565))]  # one publish
    send(trade("CLUSDT", 90.59), now=100.20)
    assert published[-1] == ("infoway:tick:USOIL", 90.59)


def test_unknown_contracts_and_other_events_are_ignored(feed):
    svc, ticks, published, send = feed
    send(trade("BTCUSDT", 80000), now=1.0)
    send({"e": "markPriceUpdate", "s": "XAUUSDT", "p": "1"}, now=1.0)
    assert ticks == {} and published == []


def test_24h_stats_feed_the_change(feed):
    svc, ticks, _, send = feed
    svc.apply_stats([
        {"symbol": "XAUUSDT", "openPrice": "4130.3", "highPrice": "4210", "lowPrice": "4120",
         "priceChange": "67.54", "priceChangePercent": "1.633", "volume": "1000"},
        {"symbol": "ETHUSDT", "openPrice": "1"},
        "junk",
    ])
    send(book("XAUUSDT", 4197.84, 4197.85), now=1.0)
    t = ticks["XAUUSD"]
    assert t["change_pct"] == 1.633
    assert t["open"] == 4130.3 and t["close_24h"] == 4130.3


def test_gold_charts_come_from_the_same_futures_contract(monkeypatch):
    seen = {}

    async def klines(symbol, interval, days, url="spot"):
        seen.update(symbol=symbol, url=url)
        return [{"date": "x", "open": 1, "high": 1, "low": 1, "close": 1, "volume": 0}]

    monkeypatch.setattr(instruments, "_fetch_binance_klines", klines)
    instruments._history_cache.clear()
    out = asyncio.run(instruments.history("XAUUSD", user=None, interval="5minute", days=1))
    assert seen == {"symbol": "XAUUSDT", "url": bf.KLINES_URL}
    assert len(out.data) == 1


def test_metaapi_is_gone():
    main = (ROOT / "app/main.py").read_text(encoding="utf-8")
    assert "metaapi_service" not in main
    assert "binance_futures.start()" in main
    assert not (ROOT / "app/services/metaapi_service.py").exists()
