"""Binance USDT-M futures feed — metals and energy, free and keyless.

Replaces MetaAPI for gold and silver (an MT5 broker account that had to stay
deployed and billed, went UNDEPLOYED, and left XAUUSD / XAGUSD at 0) and
Yahoo's ~10-minute-delayed futures for platinum, palladium, oil and gas.
Binance lists all of them as USDT-margined perpetuals on its public futures
stream: no key, no account, nothing to deploy.

Ticks go into the SAME shared cache (`infoway.ticks[PLATFORM_SYMBOL]`) and the
SAME Redis channel (`infoway:tick:{sym}`) every consumer already reads, keyed by
OUR symbol (XAUUSD, not XAUUSDT) — instruments, open positions and their
history are untouched; only where the price comes from changes.

Two streams per contract. `@aggTrade` is the last TRADED price — what makes a
quote look alive (the gold book sends dozens of messages a second but its
bid/ask only moves a couple of times a second). `@bookTicker` is bid/ask. A
trade owns `ltp` for 3 s, then the book's mid takes over. The 24 h open / high /
low / change come from REST every 10 s.

CAVEAT — read before quoting these as "spot": they are perpetual futures, with
funding every 8 h and a small basis to spot (~0.05% on gold, measured). Close
to COMEX / spot, never identical.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import math
import time
from typing import Any

import httpx
import websockets

from app.core.redis_client import publish

logger = logging.getLogger(__name__)

#: Our platform symbol → Binance USDT-M contract (all `TRADIFI_PERPETUAL`,
#: underlyingType COMMODITY; measured live on exchangeInfo). Oil is the one
#: pair nobody guesses: WTI is CLUSDT, Brent is BZUSDT.
CONTRACTS: dict[str, str] = {
    "XAUUSD": "XAUUSDT",
    "XAGUSD": "XAGUSDT",
    "XPTUSD": "XPTUSDT",
    "XPDUSD": "XPDUSDT",
    "USOIL": "CLUSDT",
    "UKOIL": "BZUSDT",
    "NATGAS": "NATGASUSDT",
}
_PLATFORM = {c: p for p, c in CONTRACTS.items()}

WS_URL = "wss://fstream.binance.com/stream"
STATS_URL = "https://fapi.binance.com/fapi/v1/ticker/24hr"
KLINES_URL = "https://fapi.binance.com/fapi/v1/klines"

STALE_RX_TIMEOUT_SEC = 30  # a silent socket is a half-open one: reconnect
RECONNECT_BACKOFF_CAP_SEC = 60
STATS_POLL_SEC = 10
TRADE_LEAD_SEC = 3.0  # a trade owns the last price this long, then the mid does
MAX_TRADE_GAP = 0.005  # a print >0.5% from the live book is garbage, not a move
PUBLISH_EVERY_SEC = 0.1  # coalesce the fan-out; the cache always holds the latest


def contract_for(symbol: str) -> str | None:
    """Binance contract for one of our symbols, else None."""
    return CONTRACTS.get(str(symbol or "").upper().strip())


def _f(v: Any) -> float:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return 0.0
    return f if math.isfinite(f) else 0.0


class _Book:
    __slots__ = ("bid", "ask", "trade", "trade_at", "stats", "published_at")

    def __init__(self) -> None:
        self.bid = 0.0
        self.ask = 0.0
        self.trade = 0.0
        self.trade_at = 0.0
        self.stats: dict[str, float] = {}
        self.published_at = 0.0

    def mid(self) -> float:
        if self.bid > 0 and self.ask > 0:
            return (self.bid + self.ask) / 2
        return self.bid or self.ask

    def ltp(self, now: float) -> float:
        if self.trade > 0 and now - self.trade_at < TRADE_LEAD_SEC:
            return self.trade
        return self.mid() or self.trade


def accept_trade(price: float, book: _Book) -> bool:
    """False for a lone print far from the live book — a bad tick, not a move.
    With no book yet there is nothing to judge it by, so it is taken."""
    if price <= 0:
        return False
    mid = book.mid()
    return mid <= 0 or abs(price - mid) / mid <= MAX_TRADE_GAP


class BinanceFuturesService:
    def __init__(self) -> None:
        self._tasks: list[asyncio.Task] = []
        self._stop = False
        self._connected = False
        self._last_error: str | None = None
        self._books: dict[str, _Book] = {c: _Book() for c in CONTRACTS.values()}

    @property
    def is_connected(self) -> bool:
        return self._connected

    def status(self) -> dict[str, Any]:
        return {
            "connected": self._connected,
            "contracts": CONTRACTS,
            "lastError": self._last_error,
        }

    # ── Lifecycle ────────────────────────────────────────────────────
    async def start(self) -> None:
        if any(not t.done() for t in self._tasks):
            return
        self._stop = False
        self._tasks = [
            asyncio.create_task(self._run_loop(), name="binance_futures_ws"),
            asyncio.create_task(self._stats_loop(), name="binance_futures_stats"),
        ]
        logger.info("binance_futures_started contracts=%d", len(CONTRACTS))

    async def stop(self) -> None:
        self._stop = True
        for t in self._tasks:
            t.cancel()
        for t in self._tasks:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await t
        self._tasks = []
        self._connected = False

    # ── Socket ───────────────────────────────────────────────────────
    async def _run_loop(self) -> None:
        backoff = 1
        while not self._stop:
            try:
                await self._connect_once()
                backoff = 1
            except asyncio.CancelledError:
                break
            except Exception as e:  # noqa: BLE001
                self._last_error = str(e)[:300]
                logger.warning("binance_futures_reconnect: %s", str(e)[:200])
            self._connected = False
            if self._stop:
                break
            await asyncio.sleep(min(backoff, RECONNECT_BACKOFF_CAP_SEC))
            backoff = min(backoff * 2, RECONNECT_BACKOFF_CAP_SEC)

    async def _connect_once(self) -> None:
        streams = "/".join(
            f"{c.lower()}@{kind}" for c in CONTRACTS.values() for kind in ("aggTrade", "bookTicker")
        )
        async with websockets.connect(
            f"{WS_URL}?streams={streams}",
            ping_interval=None, ping_timeout=None, close_timeout=5, max_size=2**20,
        ) as ws:
            self._connected = True
            self._last_error = None
            logger.info("binance_futures_ws_connected streams=%d", len(CONTRACTS) * 2)
            while not self._stop:
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=STALE_RX_TIMEOUT_SEC)
                except TimeoutError:
                    logger.warning("binance_futures_stale_rx → reconnect")
                    return
                try:
                    msg = json.loads(raw if isinstance(raw, str) else raw.decode("utf-8"))
                except ValueError:
                    continue
                await self.handle(msg)

    async def handle(self, msg: dict[str, Any], now: float | None = None) -> None:
        d = msg.get("data") if isinstance(msg.get("data"), dict) else msg
        if not isinstance(d, dict):
            return
        contract = str(d.get("s") or "").upper()
        book = self._books.get(contract)
        if book is None:
            return
        now = time.monotonic() if now is None else now
        kind = d.get("e")
        if kind == "bookTicker":
            book.bid, book.ask = _f(d.get("b")), _f(d.get("a"))
        elif kind == "aggTrade":
            price = _f(d.get("p"))
            if not accept_trade(price, book):
                return
            book.trade, book.trade_at = price, now
        else:
            return
        tick = self._tick(contract, book, now)
        if tick is None:
            return
        # The cache always holds the latest; the fan-out is coalesced.
        try:
            from app.services.infoway_service import infoway  # noqa: PLC0415 — cycle

            infoway.ticks[tick["symbol"]] = tick
        except Exception:  # noqa: BLE001
            logger.debug("binance_futures_cache_write_failed %s", contract, exc_info=True)
        if now - book.published_at < PUBLISH_EVERY_SEC:
            return
        book.published_at = now
        try:
            await publish(f"infoway:tick:{tick['symbol']}", tick)
        except Exception:  # noqa: BLE001
            logger.debug("binance_futures_publish_failed %s", contract, exc_info=True)

    def _tick(self, contract: str, book: _Book, now: float) -> dict[str, Any] | None:
        ltp = book.ltp(now)
        if ltp <= 0:
            return None
        s = book.stats
        return {
            "symbol": _PLATFORM[contract],
            "ltp": ltp,
            "bid": book.bid or ltp,
            "ask": book.ask or ltp,
            "volume": s.get("volume", 0.0),
            "ts": int(time.time() * 1000),
            "close_24h": s.get("open", 0.0),
            "change": s.get("change", 0.0),
            "change_pct": s.get("change_pct", 0.0),
            "open": s.get("open", 0.0),
            "high": s.get("high", 0.0),
            "low": s.get("low", 0.0),
            "source": "binance_futures",
        }

    # ── 24 h stats ───────────────────────────────────────────────────
    async def _stats_loop(self) -> None:
        # One request for every contract; the stream that would carry these
        # (!ticker@arr) is acknowledged on this endpoint and never delivers.
        async with httpx.AsyncClient(timeout=8.0) as client:
            while not self._stop:
                try:
                    r = await client.get(STATS_URL)
                    r.raise_for_status()
                    self.apply_stats(r.json())
                except asyncio.CancelledError:
                    raise
                except Exception as e:  # noqa: BLE001
                    logger.info("binance_futures_stats_failed: %s", str(e)[:150])
                await asyncio.sleep(STATS_POLL_SEC)

    def apply_stats(self, rows: Any) -> None:
        for row in rows if isinstance(rows, list) else []:
            book = self._books.get(str(row.get("symbol") or "").upper()) if isinstance(row, dict) else None
            if book is None:
                continue
            book.stats = {
                "open": _f(row.get("openPrice")),
                "high": _f(row.get("highPrice")),
                "low": _f(row.get("lowPrice")),
                "change": _f(row.get("priceChange")),
                "change_pct": _f(row.get("priceChangePercent")),
                "volume": _f(row.get("volume")),
            }


# Singleton
binance_futures = BinanceFuturesService()
