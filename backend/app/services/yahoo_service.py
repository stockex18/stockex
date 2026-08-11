"""Yahoo Finance quote feed — fills ONLY the symbols no other feed covers.

Third feed alongside `binance_service` (crypto) and `metaapi_service`
(forex/metals via MT5), and it follows the same contract: every tick is written
into the shared cache (`infoway.ticks[PLATFORM_SYMBOL]`) and published on
`infoway:tick:{sym}`, which `market_data_service`, `core.ws_hub` and the
option-chain already consume — so NO consumer changes.

Why this exists: the configured MT5 broker account offers exactly 8 symbols
(XAUUSD, XAGUSD + 6 crypto), and Infoway is off. That left every forex pair,
index, international stock and energy contract with no feed at all — the user
app rendered them as 0.0000. Yahoo's free chart endpoint covers all of them.

DATA FRESHNESS — read before enabling trading on any of these:

    forex (EURUSD…USDINR)     measured  1–33 s   → effectively real-time
    indices (^GDAXI, ^FTSE…)  measured ~900 s    → 15 MINUTES DELAYED
    futures (CL=F, PL=F…)     measured ~610 s    → 10 MINUTES DELAYED
    US stocks                 not measurable while the US market is shut

A delayed price is a real hazard for a B-book: anyone with a genuine feed can
watch the true move and then trade against our stale number risk-free. Prices
from the DELAYED set are safe to DISPLAY; keep `tradingEnabled = false` on
those admin segment rows unless you have accepted that exposure. `DELAYED_SEC`
below records what was measured, and `status()` surfaces it.

XAUUSD / XAGUSD are deliberately ABSENT from the map: MetaAPI already serves
them as real-time SPOT. Yahoo only has the futures (GC=F / SI=F), which quote
~55 points away from spot — publishing those would move the price under open
gold positions. The freshness guard in `_should_write` is the belt-and-braces
version of the same rule for every other symbol.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from app.core.config import settings
from app.core.redis_client import publish

logger = logging.getLogger(__name__)

# Platform symbol → Yahoo symbol. Keys MUST match `Instrument.token` for the
# mirrored international rows (they are bare tickers: EURUSD, AAPL, DE40).
SYMBOL_MAP: dict[str, str] = {
    # ── Forex — real-time on Yahoo ────────────────────────────────────
    "EURUSD": "EURUSD=X",
    "GBPUSD": "GBPUSD=X",
    "USDJPY": "USDJPY=X",
    "AUDUSD": "AUDUSD=X",
    "USDCAD": "USDCAD=X",
    "USDCHF": "USDCHF=X",
    "NZDUSD": "NZDUSD=X",
    "USDINR": "USDINR=X",
    # ── Indices — ~15 min delayed ─────────────────────────────────────
    "SPX500": "^GSPC",
    "NAS100": "^NDX",
    "US30": "^DJI",
    "UK100": "^FTSE",
    "DE40": "^GDAXI",
    "JPN225": "^N225",
    "HK50": "^HSI",
    # ── US stocks ─────────────────────────────────────────────────────
    "AAPL": "AAPL",
    "MSFT": "MSFT",
    "GOOGL": "GOOGL",
    "AMZN": "AMZN",
    "TSLA": "TSLA",
    "NVDA": "NVDA",
    "META": "META",
    "NFLX": "NFLX",
    # ── Energy + platinum/palladium (futures) — ~10 min delayed ───────
    "USOIL": "CL=F",
    "UKOIL": "BZ=F",
    "NATGAS": "NG=F",
    "XPTUSD": "PL=F",
    "XPDUSD": "PA=F",
}

# Measured staleness (seconds) per group, from a live probe on the production
# host. Surfaced in `status()` so an operator can see the exposure without
# re-deriving it. 0 → treat as real-time.
DELAYED_SEC: dict[str, int] = {
    **{s: 0 for s in ("EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD", "USDCHF", "NZDUSD", "USDINR")},
    **{s: 900 for s in ("SPX500", "NAS100", "US30", "UK100", "DE40", "JPN225", "HK50")},
    **{s: 610 for s in ("USOIL", "UKOIL", "NATGAS", "XPTUSD", "XPDUSD")},
}

_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{sym}"
# Yahoo 403s the default httpx UA. The batch `v7/finance/quote` endpoint —
# which would collapse all 30 symbols into ONE request — now answers 401
# without a session crumb, so we poll per symbol and bound the concurrency.
_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; StockExBot/1.0)"}
_MAX_CONCURRENCY = 5
# A tick from any OTHER feed newer than this wins; we never overwrite it.
_FOREIGN_TICK_FRESH_SEC = 60.0


def _f(v: Any, default: float = 0.0) -> float:
    if v is None:
        return default
    try:
        f = float(v)
    except (TypeError, ValueError):
        return default
    if f != f or f in (float("inf"), float("-inf")):
        return default
    return f


def _should_write(psym: str) -> bool:
    """False when another feed is already serving this symbol with a fresh tick.

    Keeps Yahoo strictly a GAP-FILLER: the moment a real feed (a better MT5
    account offering EURUSD, say) starts publishing, Yahoo stops stomping it —
    without anyone having to remember to prune `SYMBOL_MAP`.
    """
    try:
        from app.services.infoway_service import infoway

        cur = infoway.ticks.get(psym)
        if not cur or cur.get("source") == "yahoo":
            return True
        age = time.time() - (_f(cur.get("ts")) / 1000.0)
        return age > _FOREIGN_TICK_FRESH_SEC
    except Exception:  # noqa: BLE001
        return True


class YahooService:
    def __init__(self) -> None:
        self._task: asyncio.Task | None = None
        self._stop = False
        self._connected = False
        self._last_error: str | None = None
        self._live: dict[str, float] = {}  # platform symbol → last published ltp

    @property
    def is_connected(self) -> bool:
        return self._connected

    def status(self) -> dict[str, Any]:
        return {
            "connected": self._connected,
            "symbols": sorted(self._live),
            "resolved": len(self._live),
            "configured": len(SYMBOL_MAP),
            "delayedSec": DELAYED_SEC,
            "lastError": self._last_error,
        }

    async def start(self) -> None:
        if self._task and not self._task.done():
            return
        if not SYMBOL_MAP:
            return
        self._stop = False
        self._task = asyncio.create_task(self._run_loop(), name="yahoo_feed")
        logger.info("yahoo_started symbols=%d", len(SYMBOL_MAP))

    async def stop(self) -> None:
        self._stop = True
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
        self._task = None
        self._connected = False

    async def _run_loop(self) -> None:
        import httpx

        poll = max(5.0, float(getattr(settings, "YAHOO_POLL_SEC", 10) or 10))
        sem = asyncio.Semaphore(_MAX_CONCURRENCY)
        # One client for the process — Yahoo throttles per connection storm, and
        # a fresh AsyncClient per poll would open 30 TLS handshakes every cycle.
        async with httpx.AsyncClient(timeout=10.0, headers=_HEADERS) as client:
            while not self._stop:
                try:
                    n = await self._poll_once(client, sem)
                    self._connected = n > 0
                    if n:
                        self._last_error = None
                except asyncio.CancelledError:
                    raise
                except Exception as e:  # noqa: BLE001
                    self._last_error = str(e)[:300]
                    logger.warning("yahoo_poll_failed: %s", str(e)[:200])
                await asyncio.sleep(poll)

    async def _poll_once(self, client, sem) -> int:
        results = await asyncio.gather(
            *[self._one(client, sem, p, y) for p, y in SYMBOL_MAP.items()],
            return_exceptions=True,
        )
        return sum(1 for r in results if r is True)

    async def _one(self, client, sem, psym: str, ysym: str) -> bool:
        if not _should_write(psym):
            return False
        async with sem:
            try:
                r = await client.get(
                    _CHART_URL.format(sym=ysym),
                    params={"interval": "1m", "range": "1d"},
                )
                meta = r.json()["chart"]["result"][0]["meta"]
            except Exception:  # noqa: BLE001 — one bad symbol never stops the rest
                return False

        ltp = _f(meta.get("regularMarketPrice"))
        if ltp <= 0:
            return False

        prev_close = _f(meta.get("chartPreviousClose")) or _f(meta.get("previousClose"))
        change = (ltp - prev_close) if prev_close > 0 else 0.0
        # Yahoo's chart meta carries no book, so bid == ask == ltp. The admin's
        # configured spread is layered on top for DISPLAY by
        # `market_data_service._apply_admin_spread`, and again at fill time by
        # the matching engine's per-pool spread — so a broker markup still
        # applies exactly as it does for every other feed.
        quote_ts = int(_f(meta.get("regularMarketTime")))
        tick = {
            "symbol": psym,
            "ltp": ltp,
            "bid": ltp,
            "ask": ltp,
            "volume": 0.0,
            # `ts` = when WE produced this tick, matching binance/metaapi. The
            # true age of the underlying quote is carried separately so nothing
            # downstream mistakes a 15-min-old index print for a live one.
            "ts": int(time.time() * 1000),
            "quote_ts": quote_ts,
            "age_sec": max(0, int(time.time()) - quote_ts) if quote_ts else None,
            "close_24h": prev_close,
            "change": change,
            "change_pct": (change / prev_close * 100) if prev_close > 0 else 0.0,
            "open": _f(meta.get("regularMarketOpen")),
            "high": _f(meta.get("regularMarketDayHigh")),
            "low": _f(meta.get("regularMarketDayLow")),
            "source": "yahoo",
        }
        try:
            from app.services.infoway_service import infoway

            infoway.ticks[psym] = tick
        except Exception:  # noqa: BLE001
            logger.debug("yahoo_cache_write_failed %s", psym, exc_info=True)
        try:
            await publish(f"infoway:tick:{psym}", tick)
        except Exception:  # noqa: BLE001
            logger.debug("yahoo_publish_failed %s", psym, exc_info=True)
        self._live[psym] = ltp
        return True


# Singleton
yahoo = YahooService()
