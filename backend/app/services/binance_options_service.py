"""Binance crypto OPTIONS feed — European, USDT-settled, free & keyless (eapi).

Phase 1 is VIEW-ONLY: this service publishes live option prices + greeks so the
crypto option chain renders; trading on the CRYPTO_OPT segment stays blocked
(seeded `tradingEnabled=False`) until the operator turns it on.

Poll-based, not WebSocket: one REST call to `/eapi/v1/mark` returns every
option's mark price + greeks in a single shot, and one `/eapi/v1/ticker` call
returns bid/ask/last/volume — cheap enough at a few-second cadence and far
simpler than a per-symbol socket. Each BTC option tick is written into the SAME
shared cache (`infoway.ticks`) and Redis channel (`infoway:tick:{sym}`) that
`market_data_service`, `core.ws_hub` and the watchlist already read, so no
consumer needs changing. Greeks + strike/expiry/type ride along on the tick
dict (extra keys pass through untouched) for the option-chain endpoint.

The instrument universe is WINDOWED — only the nearest N expiries and strikes
within ±X% of spot become `Instrument` rows — so we don't flood the DB/UI with
Binance's full several-hundred-strike board.
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import date, datetime
from typing import Any

import httpx

from app.core.config import settings
from app.core.redis_client import cache_set, publish

# Match market_data_service's cross-worker snapshot keys so get_quote() serves
# option prices on EVERY worker, not just the one running the feed.
_MDLIVE_KEY = "mdlive:{token}"
_MDLIVE_TTL_SEC = 30
_MDLAST_KEY = "mdlast:{token}"
_MDLAST_TTL_SEC = 7 * 86400

logger = logging.getLogger(__name__)


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


def underlyings() -> list[str]:
    """Configured option roots (upper, deduped) — e.g. ["BTC"]."""
    out: list[str] = []
    seen: set[str] = set()
    for s in (settings.BINANCE_OPTIONS_UNDERLYINGS or "").split(","):
        t = s.strip().upper()
        if t and t not in seen:
            seen.add(t)
            out.append(t)
    return out


def parse_option_symbol(sym: str) -> dict | None:
    """`BTC-260925-145000-C` → {root, expiry(date), strike(float), opt_type CE/PE}.
    Returns None if the shape isn't a Binance option symbol."""
    parts = (sym or "").split("-")
    if len(parts) != 4:
        return None
    root, yymmdd, strike_s, cp = parts
    try:
        expiry = datetime.strptime(yymmdd, "%y%m%d").date()
        strike = float(strike_s)
    except (ValueError, TypeError):
        return None
    if cp.upper() not in ("C", "P") or strike <= 0:
        return None
    return {
        "root": root.upper(),
        "expiry": expiry,
        "strike": strike,
        "opt_type": "CE" if cp.upper() == "C" else "PE",
    }


def _spot_for(root: str) -> float:
    """Live spot for the option's underlying, from the shared crypto cache
    (Binance spot writes BTCUSDT there). Used to window strikes around ATM."""
    try:
        from app.services.infoway_service import infoway

        for key in (f"{root}USDT", f"{root}USD", root):
            t = infoway.ticks.get(key)
            if t and _f(t.get("ltp")) > 0:
                return _f(t.get("ltp"))
    except Exception:
        pass
    return 0.0


class BinanceOptionsService:
    def __init__(self) -> None:
        self._task: asyncio.Task | None = None
        self._stop = False
        self._connected = False
        self._last_error: str | None = None
        # symbol → contract meta {root, expiry, strike, opt_type, tick_size}
        self._universe: dict[str, dict] = {}
        self._last_universe_refresh = 0.0
        # Binance rate-limit guard. From a datacenter IP the eapi will answer a
        # burst with 429 then auto-ban with 418 (escalating 2 min → days). We
        # respect Retry-After and stop hitting the API until the cooldown ends.
        self._cooldown_until = 0.0

    @property
    def is_connected(self) -> bool:
        return self._connected

    def status(self) -> dict[str, Any]:
        return {
            "connected": self._connected,
            "universe": len(self._universe),
            "underlyings": underlyings(),
            "lastError": self._last_error,
        }

    def universe(self) -> dict[str, dict]:
        return dict(self._universe)

    # ── Rate-limit aware GET ─────────────────────────────────────────────
    def _in_cooldown(self) -> bool:
        return time.monotonic() < self._cooldown_until

    def _trip_cooldown(self, resp: httpx.Response | None, default_sec: float = 120.0) -> None:
        """Enter a cooldown after a 418/429. Honour Retry-After when present."""
        wait = default_sec
        try:
            if resp is not None:
                ra = resp.headers.get("Retry-After")
                if ra:
                    wait = max(wait, float(ra))
        except Exception:
            pass
        self._cooldown_until = time.monotonic() + wait
        self._last_error = f"rate-limited (cooldown {int(wait)}s)"
        logger.warning("binance_options_rate_limited cooldown=%ss", int(wait))

    async def _get(self, client: httpx.AsyncClient, path: str) -> httpx.Response | None:
        """GET an eapi path; on 418/429 trip the cooldown and return None."""
        r = await client.get(f"{settings.BINANCE_OPTIONS_EAPI_BASE}{path}")
        if r.status_code in (418, 429):
            self._trip_cooldown(r)
            return None
        return r

    # ── Universe (exchangeInfo → windowed contracts) ─────────────────────
    async def _fetch_exchange_info(self) -> list[dict]:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await self._get(client, "/eapi/v1/exchangeInfo")
            if r is None:
                return []
            r.raise_for_status()
            data = r.json() or {}
        return data.get("optionSymbols") or []

    async def refresh_universe(self) -> dict[str, dict]:
        """Rebuild the windowed contract universe: only the roots we want, the
        nearest N expiries, and strikes within ±X% of spot."""
        if self._in_cooldown():
            return self._universe
        roots = set(underlyings())
        max_expiries = max(1, int(settings.BINANCE_OPTIONS_MAX_EXPIRIES))
        strike_pct = float(settings.BINANCE_OPTIONS_STRIKE_PCT) or 15.0

        try:
            rows = await self._fetch_exchange_info()
        except Exception as e:  # noqa: BLE001
            self._last_error = f"exchangeInfo: {str(e)[:200]}"
            logger.warning("binance_options_exchangeinfo_failed: %s", str(e)[:200])
            return self._universe

        # Parse every option symbol, keep only our roots.
        parsed: list[dict] = []
        for row in rows:
            sym = row.get("symbol") or ""
            meta = parse_option_symbol(sym)
            if meta is None or meta["root"] not in roots:
                continue
            # tick size from the PRICE_FILTER if present
            tick_size = 0.1
            for filt in row.get("filters") or []:
                if filt.get("filterType") == "PRICE_FILTER":
                    tick_size = _f(filt.get("tickSize"), 0.1) or 0.1
            meta["symbol"] = sym
            meta["tick_size"] = tick_size
            meta["unit"] = _f(row.get("unit"), 1.0) or 1.0  # contract multiplier
            parsed.append(meta)

        if not parsed:
            return self._universe

        today = date.today()
        from app.services import crypto_expiry_settings as _ces

        # Super-admin's count of expiries to list, nearest first. Falls back to
        # the env default when unset.
        _configured = await _ces.max_expiries()
        if _configured > 0:
            max_expiries = _configured
        # Nearest N future (or today) expiries per root.
        universe: dict[str, dict] = {}
        for root in roots:
            spot = _spot_for(root)
            root_rows = [p for p in parsed if p["root"] == root and p["expiry"] >= today]
            # Nearest N, not "within N days". Crypto expires daily so the two
            # agree until today's contract settles — after 13:30 IST Binance
            # drops it, the nearest expiry becomes tomorrow's, and a day-based
            # cap would list nothing at all for the rest of the day.
            expiries = sorted({p["expiry"] for p in root_rows})[:max_expiries]
            exp_set = set(expiries)
            for p in root_rows:
                if p["expiry"] not in exp_set:
                    continue
                # Strike window around spot (skip if we have no spot yet — then
                # keep all, the next refresh with a spot narrows it).
                if spot > 0:
                    lo = spot * (1 - strike_pct / 100.0)
                    hi = spot * (1 + strike_pct / 100.0)
                    if not (lo <= p["strike"] <= hi):
                        continue
                universe[p["symbol"]] = p

        self._universe = universe
        self._last_universe_refresh = time.monotonic()
        logger.info("binance_options_universe refreshed=%s", len(universe))
        return universe

    # ── Live price poll ──────────────────────────────────────────────────
    async def _poll_once(self) -> int:
        if self._in_cooldown():
            return 0
        marks: dict[str, dict] = {}
        # VIEW-ONLY phase: poll ONLY /mark (markPrice + greeks). It's the
        # lightest single call that carries everything the chain needs; bid/ask
        # are bracketed off the mark. Dropping the extra /ticker call halves the
        # eapi weight, which matters on a datacenter IP prone to 418 bans.
        async with httpx.AsyncClient(timeout=10.0) as client:
            try:
                mr = await self._get(client, "/eapi/v1/mark")
                if mr is not None and mr.status_code == 200:
                    for m in mr.json() or []:
                        marks[m.get("symbol")] = m
            except Exception:
                logger.debug("binance_options_mark_poll_failed", exc_info=True)

        if not marks:
            return 0

        try:
            from app.services.infoway_service import infoway
        except Exception:
            infoway = None  # type: ignore

        written = 0
        now_ms = int(time.time() * 1000)
        for sym, meta in self._universe.items():
            m = marks.get(sym) or {}
            ltp = _f(m.get("markPrice"))
            if ltp <= 0:
                continue
            # No live book in the /mark payload — bracket the mark by half a tick
            # so bid<ltp<ask holds (good enough for a view-only chain).
            half = max(_f(meta.get("tick_size"), 0.1), 0.1) / 2
            bid, ask = max(0.0, ltp - half), ltp + half
            tick = {
                "symbol": sym,
                "ltp": ltp,
                "bid": bid,
                "ask": ask,
                "volume": 0.0,
                "ts": now_ms,
                "open": 0.0,
                "high": 0.0,
                "low": 0.0,
                "change": 0.0,
                "change_pct": 0.0,
                # Option context + greeks — extra keys pass through the cache;
                # the option-chain endpoint reads them straight from here.
                "is_option": True,
                "strike": meta.get("strike"),
                "opt_type": meta.get("opt_type"),
                "delta": _f(m.get("delta")),
                "gamma": _f(m.get("gamma")),
                "theta": _f(m.get("theta")),
                "vega": _f(m.get("vega")),
                "iv": _f(m.get("markIV")),
            }
            if infoway is not None:
                try:
                    infoway.ticks[sym] = tick
                except Exception:
                    pass
            try:
                await publish(f"infoway:tick:{sym}", tick)
            except Exception:
                pass
            # Cross-worker snapshot: write the same execution-safe shape
            # market_data_service uses, so get_quote() on ANY worker (not just
            # the feed's) returns this option's live price. mdlive = 30 s
            # execution snapshot; mdlast = 7-day display fallback.
            quote_shape = {
                "token": sym,
                "ltp": ltp,
                "bid": bid,
                "ask": ask,
                "open": tick["open"],
                "high": tick["high"],
                "low": tick["low"],
                "volume": tick["volume"],
                "change": tick["change"],
                "change_pct": tick["change_pct"],
                "source": "binance_options",
                "is_option": True,
                "strike": meta.get("strike"),
                "opt_type": meta.get("opt_type"),
                "delta": tick["delta"],
                "gamma": tick["gamma"],
                "theta": tick["theta"],
                "vega": tick["vega"],
                "iv": tick["iv"],
                "ts": now_ms,
            }
            try:
                await cache_set(_MDLIVE_KEY.format(token=sym), quote_shape, ttl_sec=_MDLIVE_TTL_SEC)
                await cache_set(_MDLAST_KEY.format(token=sym), quote_shape, ttl_sec=_MDLAST_TTL_SEC)
            except Exception:
                pass
            written += 1
        return written

    # ── Lifecycle ────────────────────────────────────────────────────────
    async def start(self) -> None:
        if self._task and not self._task.done():
            return
        if not settings.BINANCE_OPTIONS_ENABLED:
            logger.info("binance_options_skipped: BINANCE_OPTIONS_ENABLED is false")
            return
        self._stop = False
        self._task = asyncio.create_task(self._run_loop(), name="binance_options")
        logger.info("binance_options_started underlyings=%s", underlyings())

    async def stop(self) -> None:
        self._stop = True
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
        self._task = None
        self._connected = False

    async def _run_loop(self) -> None:
        # Build the universe + mirror instruments once, then poll prices. The
        # universe is refreshed every ~30 min (new expiries / spot drift).
        try:
            await self.refresh_universe()
            await self.mirror_options_to_instruments()
        except Exception:
            logger.warning("binance_options_initial_refresh_failed", exc_info=True)
        poll = max(1.0, float(settings.BINANCE_OPTIONS_POLL_SEC))
        refresh_every = max(1, int(1800 / poll))
        tick = 0
        while not self._stop:
            try:
                n = await self._poll_once()
                self._connected = n > 0
                self._last_error = None
            except asyncio.CancelledError:
                break
            except Exception as e:  # noqa: BLE001
                self._connected = False
                self._last_error = str(e)[:200]
                logger.warning("binance_options_poll_error: %s", str(e)[:200])
            tick += 1
            if tick % refresh_every == 0:
                try:
                    await self.refresh_universe()
                    await self.mirror_options_to_instruments()
                except Exception:
                    logger.debug("binance_options_refresh_failed", exc_info=True)
            try:
                await asyncio.sleep(poll)
            except asyncio.CancelledError:
                break

    # ── Instrument mirror ────────────────────────────────────────────────
    async def mirror_options_to_instruments(self) -> int:
        """Upsert an `Instrument` row per windowed option contract. token ==
        symbol (non-numeric) so it routes to the shared-symbol feed path, not
        Zerodha. Segment = CRYPTO_OPTION_BUY (both buy/sell resolve to the
        CRYPTO_OPT admin row; the segment string just needs to contain OPTION
        and start with CRYPTO for the option-validation + 24×7 + wallet paths)."""
        if not self._universe:
            return 0
        from bson import Decimal128

        from app.models._base import Exchange, InstrumentType, OptionType, SegmentType
        from app.models.instrument import Instrument

        upserts = 0
        for sym, meta in self._universe.items():
            root = meta["root"]
            opt_type = meta["opt_type"]  # CE/PE
            try:
                existing = await Instrument.find_one(Instrument.token == sym)
                fields = dict(
                    symbol=sym,
                    trading_symbol=sym,
                    name=f"{root} {meta['strike']:.0f} {opt_type} {meta['expiry']:%d%b%y}".upper(),
                    exchange=Exchange.CRYPTO,
                    segment=SegmentType.CRYPTO_OPTION_BUY.value,
                    instrument_type=InstrumentType.CE if opt_type == "CE" else InstrumentType.PE,
                    option_type=OptionType.CE if opt_type == "CE" else OptionType.PE,
                    strike=Decimal128(str(meta["strike"])),
                    expiry=meta["expiry"],
                    underlying_token=f"CRYPTO_{root}USD",
                    lot_size=1,
                    tick_size=Decimal128(str(meta.get("tick_size") or "0.1")),
                    is_active=True,
                    is_tradable=True,
                )
                if existing is None:
                    await Instrument(token=sym, **fields).insert()
                    upserts += 1
                else:
                    changed = False
                    for k, v in fields.items():
                        if getattr(existing, k, None) != v:
                            setattr(existing, k, v)
                            changed = True
                    if changed:
                        await existing.save()
                        upserts += 1
            except Exception:
                logger.debug("binance_option_mirror_failed sym=%s", sym, exc_info=True)
        # Deactivate any previously-mirrored option that is NO LONGER in the
        # windowed universe — spot drifted out of its strike, or it expired /
        # settled on Binance. Otherwise those rows linger in the marketwatch /
        # option chain showing 0.00 forever (the feed only prices the current
        # window, e.g. spot fell to ~49.9k so the old 61k–64k strikes stopped
        # being priced). Guarded on a non-empty universe so a transient empty
        # refresh never deactivates everything.
        try:
            keep = list(self._universe.keys())
            if keep:
                coll = Instrument.get_motor_collection()
                res = await coll.update_many(
                    {
                        "segment": SegmentType.CRYPTO_OPTION_BUY.value,
                        "token": {"$nin": keep},
                        "is_active": True,
                    },
                    {"$set": {"is_active": False, "is_tradable": False}},
                )
                if getattr(res, "modified_count", 0):
                    logger.info("binance_options_deactivated_stale=%s", res.modified_count)
        except Exception:
            logger.debug("binance_options_deactivate_stale_failed", exc_info=True)

        if upserts:
            logger.info("binance_options_mirror upserts=%s", upserts)
        return upserts


# Singleton
binance_options = BinanceOptionsService()
