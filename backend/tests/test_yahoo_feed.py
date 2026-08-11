"""Yahoo gap-filler feed — map hygiene + the never-stomp-a-better-feed guard.

The guard is the load-bearing bit: Yahoo only has FUTURES for gold/silver
(GC=F / SI=F), which quote ~55 points away from the SPOT price MetaAPI serves.
If Yahoo ever wrote those keys it would move the price under open gold
positions, so `_should_write` must refuse any symbol another feed is already
keeping fresh.
"""

from __future__ import annotations

import time

import pytest

from app.services import yahoo_service as ys


def _seed_tick(monkeypatch, sym: str, *, source: str, age_sec: float):
    """Put a tick from `source` into the shared cache, `age_sec` old."""

    class _FakeInfoway:
        ticks = {sym: {"source": source, "ts": (time.time() - age_sec) * 1000}}

    import app.services.infoway_service as real

    monkeypatch.setattr(real, "infoway", _FakeInfoway, raising=False)


def test_metals_are_not_in_the_map():
    """MetaAPI owns XAUUSD/XAGUSD as real-time SPOT — Yahoo must never claim them."""
    assert "XAUUSD" not in ys.SYMBOL_MAP
    assert "XAGUSD" not in ys.SYMBOL_MAP
    # …but platinum/palladium have no other feed, so Yahoo does serve those.
    assert ys.SYMBOL_MAP["XPTUSD"] == "PL=F"
    assert ys.SYMBOL_MAP["XPDUSD"] == "PA=F"


def test_no_crypto_in_the_map():
    """Binance owns every crypto key."""
    for sym in ys.SYMBOL_MAP:
        assert "USDT" not in sym
        assert sym not in {"BTCUSD", "ETHUSD", "LTCUSD", "XRPUSD", "BCHUSD", "DASHUSD"}


def test_every_symbol_has_a_freshness_verdict():
    """A symbol with no DELAYED_SEC entry is one nobody classified — that is how
    a delayed feed silently becomes tradeable. US stocks are the known gap."""
    unclassified = set(ys.SYMBOL_MAP) - set(ys.DELAYED_SEC)
    assert unclassified == {"AAPL", "MSFT", "GOOGL", "AMZN", "TSLA", "NVDA", "META", "NFLX"}


def test_writes_when_cache_is_empty(monkeypatch):
    _seed_tick(monkeypatch, "OTHER", source="binance", age_sec=1)
    assert ys._should_write("EURUSD") is True


def test_refuses_to_stomp_a_fresh_foreign_tick(monkeypatch):
    """MetaAPI publishing EURUSD → Yahoo must back off, no code change needed."""
    _seed_tick(monkeypatch, "EURUSD", source="metaapi", age_sec=2)
    assert ys._should_write("EURUSD") is False


def test_takes_over_when_the_foreign_feed_goes_stale(monkeypatch):
    """…but a dead feed must not leave the symbol frozen forever."""
    _seed_tick(monkeypatch, "EURUSD", source="metaapi", age_sec=ys._FOREIGN_TICK_FRESH_SEC + 30)
    assert ys._should_write("EURUSD") is True


def test_overwrites_its_own_tick(monkeypatch):
    _seed_tick(monkeypatch, "EURUSD", source="yahoo", age_sec=0.5)
    assert ys._should_write("EURUSD") is True


@pytest.mark.parametrize("bad", [None, float("nan"), float("inf"), "abc", ""])
def test_f_rejects_garbage(bad):
    assert ys._f(bad) == 0.0
