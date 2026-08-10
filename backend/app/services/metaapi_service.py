"""MetaAPI (metaapi.cloud) market-data feed — FOREX / METALS / ENERGY only.

Connects the configured MT4/MT5 account via the MetaApi streaming connection,
resolves platform symbols (XAUUSD, EURUSD, USOIL…) to the broker's ACTUAL
symbol names (brokers commonly suffix — this one uses `XAUUSD.#`), subscribes,
and writes each tick into the SAME shared tick cache (`infoway.ticks[PLATFORM_
SYMBOL]`) and the SAME Redis channel (`infoway:tick:{sym}`) that
`market_data_service`, `core.ws_hub` and the option-chain already read — so NO
consumer changes, exactly like `binance_service` does for crypto.

CRYPTO is never written here (its keys belong to Binance). The service only
ever writes the forex/metal/energy platform symbols it could resolve against
the broker, so it can't collide with the Binance crypto keys.

Prices come from `terminal_state.price(symbol)` (kept live by the streaming
sync — zero network per read). MetaAPI quotes carry bid/ask/time only (no OHLC
/ volume), so ltp = mid(bid, ask) and OHLC/change are left 0 — bid/ask/ltp is
all the matching engine + risk enforcer need.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from app.core.config import settings
from app.core.redis_client import publish

logger = logging.getLogger(__name__)

RECONNECT_BACKOFF_CAP_SEC = 30

# Broker-naming hints for symbols that MT5 brokers rename (suffixes like `.#`
# are handled separately by the alnum-root match). Platform symbol → candidate
# broker roots, tried in order after the exact/root match.
_ALIASES: dict[str, list[str]] = {
    "USOIL": ["USOIL", "WTI", "XTIUSD", "CRUDE", "OILUSD", "USOil"],
    "UKOIL": ["UKOIL", "BRENT", "XBRUSD", "BRENTUSD", "UKOil"],
    "NATGAS": ["NATGAS", "XNGUSD", "NGAS", "NATURALGAS"],
}


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


def _token() -> str:
    t = settings.METAAPI_TOKEN
    return t.get_secret_value() if hasattr(t, "get_secret_value") else str(t or "")


def platform_symbols() -> list[str]:
    """Forex + metals + energy platform symbols to try (crypto excluded)."""
    out: list[str] = []
    for csv in (
        settings.METAAPI_DEFAULT_FOREX,
        settings.METAAPI_DEFAULT_METALS,
        settings.METAAPI_DEFAULT_ENERGY,
    ):
        for s in (csv or "").split(","):
            t = s.strip().upper()
            if t and t not in out:
                out.append(t)
    return out


def _root(x: str) -> str:
    return "".join(ch for ch in x.upper() if ch.isalnum())


class MetaApiService:
    def __init__(self) -> None:
        self._task: asyncio.Task | None = None
        self._stop: bool = False
        self._connected: bool = False
        self._last_error: str | None = None
        self._api = None
        self._account = None
        self._conn = None
        self._map: dict[str, str] = {}  # platform symbol → broker symbol

    @property
    def is_connected(self) -> bool:
        return self._connected

    def status(self) -> dict[str, Any]:
        return {
            "connected": self._connected,
            "map": self._map,
            "symbols": list(self._map.keys()),
            "lastError": self._last_error,
        }

    # ── Lifecycle ────────────────────────────────────────────────────
    async def start(self) -> None:
        if self._task and not self._task.done():
            return
        if not _token() or not settings.METAAPI_ACCOUNT_ID:
            logger.info("metaapi_skipped: no token / account id configured")
            return
        self._stop = False
        self._task = asyncio.create_task(self._run_loop(), name="metaapi_feed")
        logger.info("metaapi_started")

    async def stop(self) -> None:
        self._stop = True
        if self._conn is not None:
            try:
                await self._conn.close()
            except Exception:  # noqa: BLE001
                pass
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
        self._task = None
        self._connected = False

    # ── Connect / reconnect ──────────────────────────────────────────
    async def _run_loop(self) -> None:
        backoff = 2
        while not self._stop:
            try:
                await self._connect_and_poll()
                backoff = 2
            except asyncio.CancelledError:
                break
            except Exception as e:  # noqa: BLE001
                self._last_error = str(e)[:300]
                logger.warning("metaapi_reconnect: %s", str(e)[:200])
            self._connected = False
            if self._stop:
                break
            await asyncio.sleep(min(backoff, RECONNECT_BACKOFF_CAP_SEC))
            backoff = min(backoff * 2, RECONNECT_BACKOFF_CAP_SEC)

    async def _connect_and_poll(self) -> None:
        from metaapi_cloud_sdk import MetaApi

        opts = {"region": settings.METAAPI_REGION} if settings.METAAPI_REGION else {}
        self._api = MetaApi(_token(), opts) if opts else MetaApi(_token())
        self._account = await self._api.metatrader_account_api.get_account(
            settings.METAAPI_ACCOUNT_ID
        )
        if getattr(self._account, "state", "") not in ("DEPLOYED",):
            try:
                await self._account.deploy()
            except Exception:  # noqa: BLE001
                logger.debug("metaapi_deploy_failed", exc_info=True)
        try:
            await self._account.wait_connected()
        except Exception:  # noqa: BLE001
            logger.debug("metaapi_wait_connected_failed", exc_info=True)

        self._conn = self._account.get_streaming_connection()
        await self._conn.connect()
        await self._conn.wait_synchronized({"timeoutInSeconds": 180})
        self._connected = True
        self._last_error = None
        logger.info("metaapi_connected region=%s", getattr(self._account, "region", "?"))

        await self._resolve_symbols()
        if not self._map:
            logger.warning(
                "metaapi_no_symbols_resolved — broker offers none of the configured "
                "forex/metal/energy symbols; nothing to feed"
            )
            return
        for bsym in self._map.values():
            try:
                await self._conn.subscribe_to_market_data(bsym, [{"type": "quotes"}])
            except Exception as e:  # noqa: BLE001
                logger.debug("metaapi_subscribe_failed %s %s", bsym, str(e)[:80])

        poll = max(0.2, float(settings.METAAPI_POLL_SEC or 0.7))
        while not self._stop:
            ts = self._conn.terminal_state
            # Broker/terminal dropped → unwind so _run_loop reconnects.
            if not getattr(ts, "connected", True):
                logger.warning("metaapi_terminal_disconnected → reconnect")
                return
            for psym, bsym in self._map.items():
                try:
                    p = ts.price(bsym)
                except Exception:  # noqa: BLE001
                    p = None
                if not p:
                    continue
                bid = _f(p.get("bid"))
                ask = _f(p.get("ask"))
                ltp = (bid + ask) / 2 if (bid > 0 and ask > 0) else (bid or ask)
                if ltp <= 0:
                    continue
                tick = {
                    "symbol": psym,
                    "ltp": ltp,
                    "bid": bid,
                    "ask": ask,
                    "volume": 0.0,
                    "ts": int(time.time() * 1000),
                    "close_24h": 0.0,
                    "change": 0.0,
                    "change_pct": 0.0,
                    "open": 0.0,
                    "high": 0.0,
                    "low": 0.0,
                    "source": "metaapi",
                }
                try:
                    from app.services.infoway_service import infoway

                    infoway.ticks[psym] = tick
                except Exception:  # noqa: BLE001
                    logger.debug("metaapi_cache_write_failed %s", psym, exc_info=True)
                try:
                    await publish(f"infoway:tick:{psym}", tick)
                except Exception:  # noqa: BLE001
                    logger.debug("metaapi_publish_failed %s", psym, exc_info=True)
            await asyncio.sleep(poll)

    async def _resolve_symbols(self) -> None:
        """Map each platform symbol → the broker's actual symbol name.

        Fetches the broker's full symbol universe (RPC get_symbols), then for
        each platform symbol tries: exact match → alnum-root match (handles the
        `.#` suffix) → alias candidates. Unresolved symbols (broker doesn't
        offer them) are simply skipped.
        """
        broker: list[str] = []
        try:
            rpc = self._account.get_rpc_connection()
            await asyncio.wait_for(rpc.connect(), timeout=30)
            try:
                await asyncio.wait_for(rpc.wait_synchronized(), timeout=30)
            except Exception:  # noqa: BLE001
                pass
            broker = await asyncio.wait_for(rpc.get_symbols(), timeout=30)
        except Exception as e:  # noqa: BLE001
            logger.warning("metaapi_get_symbols_failed: %s", str(e)[:150])

        bset = {b.upper(): b for b in broker}
        broot: dict[str, str] = {}
        for b in broker:
            broot.setdefault(_root(b), b)

        mapped: dict[str, str] = {}
        for psym in platform_symbols():
            found = None
            for cand in [psym, *_ALIASES.get(psym, [])]:
                cu = cand.upper()
                if cu in bset:
                    found = bset[cu]
                    break
                if _root(cu) in broot:
                    found = broot[_root(cu)]
                    break
            if found:
                mapped[psym] = found
        self._map = mapped
        logger.info(
            "metaapi_symbol_map resolved=%d/%d %s",
            len(mapped), len(platform_symbols()), mapped,
        )


# Singleton
metaapi = MetaApiService()
