"""Crypto options carried a 5-point spread nobody had set. Binance's /mark
gives no book, so the feed bracketed the mark by half a tick, and a BTC
option's tick is 5 USDT: BUY filled 2.5 above the mark, SELL 2.5 below.
Both sides now quote the mark."""

import asyncio
import types

from app.services import binance_options_service as bos

SYM = "BTC-261127-100000-C"


def test_both_sides_quote_the_mark(monkeypatch):
    svc = bos.BinanceOptionsService()
    svc._universe = {SYM: {"strike": 100000, "opt_type": "CE", "tick_size": 5.0}}
    monkeypatch.setattr(svc, "_in_cooldown", lambda: False)

    async def fake_get(_client, _path):
        return types.SimpleNamespace(status_code=200, json=lambda: [{"symbol": SYM, "markPrice": "1205"}])

    monkeypatch.setattr(svc, "_get", fake_get)
    written = {}

    async def fake_cache_set(key, val, **_kw):
        written[key] = val

    async def fake_publish(*_a, **_kw):
        return None

    monkeypatch.setattr(bos, "cache_set", fake_cache_set)
    monkeypatch.setattr(bos, "publish", fake_publish)

    assert asyncio.run(svc._poll_once()) == 1
    q = next(iter(written.values()))
    assert q["bid"] == q["ask"] == q["ltp"] == 1205.0
