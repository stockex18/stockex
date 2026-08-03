"""Authoritative market-price resolvers for games settlement.

NIFTY  → Kite 15m historical candle (open/close) with live-LTP fallback.
BTC    → Binance public 15m klines (private copy of the kline fetch to avoid a
         service→router import) with Infoway live-tick fallback.

Number-result digit extractors also live here.
"""

from __future__ import annotations

import logging
from datetime import datetime
from decimal import ROUND_FLOOR, Decimal

import httpx

from app.utils.decimal_utils import quantize_money, to_decimal

logger = logging.getLogger(__name__)

# Standard Kite instrument token for the NIFTY 50 index.
NIFTY_TOKEN = 256265
BINANCE_KLINES = "https://api.binance.com/api/v3/klines"


# ── NIFTY ────────────────────────────────────────────────────────────
_NIFTY_LAST_KEY = "games:nifty:last"
_NIFTY_LAST_TTL = 259200  # 3 days — survives a weekend gap
_BTC_LAST_KEY = "games:btc:last"


async def games_price_mirror_loop(interval_sec: float = 0.2) -> None:
    """LEADER-ONLY: fan the fresh NIFTY + BTC LTP out to Redis every ~200 ms.

    NIFTY ticks ~9×/s but only the feed-leader worker has it in-process
    (`get_ltp_instant`). The games `/price` endpoint round-robins across all 4
    workers, so a non-leader served a STALE cached value → the games price
    looked frozen for 3–4 s even though the feed was live. Writing the live
    value to Redis here makes `nifty_ltp_display()` (which reads
    `games:nifty:last`) return fresh on EVERY worker, so the 250 ms client poll
    actually shows ~4 fresh updates/s."""
    import asyncio

    from app.core.redis_client import cache_set

    logger.info("games_price_mirror_loop_started interval=%.2fs", interval_sec)
    while True:
        try:
            n = await nifty_ltp()
            if n and n > 0:
                await cache_set(_NIFTY_LAST_KEY, str(n), ttl_sec=_NIFTY_LAST_TTL)
            b = await btc_ltp()
            if b and b > 0:
                await cache_set(_BTC_LAST_KEY, str(b), ttl_sec=_NIFTY_LAST_TTL)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.debug("games_price_mirror_failed", exc_info=True)
        try:
            await asyncio.sleep(interval_sec)
        except asyncio.CancelledError:
            raise


async def nifty_ltp() -> Decimal | None:
    """LIVE NIFTY LTP (None when no live price). Used by SETTLEMENT — must
    never return a stale price, or a game could settle at a wrong number."""
    from app.services import market_data_service

    v = market_data_service.get_ltp_instant(str(NIFTY_TOKEN))
    if v and v > 0:
        return v
    try:
        q = await market_data_service.get_quote(str(NIFTY_TOKEN))
        ltp = to_decimal(q.get("ltp") or 0)
        if ltp > 0:
            return ltp
    except Exception:
        logger.debug("nifty_ltp_quote_failed", exc_info=True)
    return None


async def nifty_ltp_display() -> Decimal | None:
    """DISPLAY NIFTY price for the games UI — ALWAYS returns a number once one
    has ever been seen. On a live tick it refreshes a persistent last-known
    cache; when the feed is down / market closed / this is a cold non-leader
    worker, it returns that last-known price so the price never blanks to
    "Waiting for feed". NOT for settlement (see `nifty_ltp`)."""
    from app.core.redis_client import cache_get, cache_set
    from app.utils.time_utils import is_market_open

    live = await nifty_ltp()
    market_open = is_market_open()

    # DURING market hours a live tick is the truth — show it and refresh the
    # persistent last-known so it's available once the feed goes quiet.
    if live and live > 0 and market_open:
        try:
            await cache_set(_NIFTY_LAST_KEY, str(live), ttl_sec=_NIFTY_LAST_TTL)
        except Exception:
            logger.debug("nifty_ltp_cache_set_failed", exc_info=True)
        return live

    # MARKET CLOSED: do NOT trust the live `_state` tick — it's frozen at
    # whatever the WS feed last streamed before close, which can sit ~20 pts
    # BELOW the OFFICIAL Zerodha close (2026-07-09: streamed 23,962.80 vs the
    # official 23,981.90). Settlement writes the official close into
    # `_NIFTY_LAST_KEY`, so prefer that here — this keeps the games "live spot"
    # matching the declared result + the admin terminal. Critically we must NOT
    # overwrite `_NIFTY_LAST_KEY` with the stale streamed tick while closed (the
    # old code did, on every 3 s display poll, clobbering the official close).
    try:
        last = await cache_get(_NIFTY_LAST_KEY)
        if last:
            lv = to_decimal(last)
            if lv > 0:
                return lv
    except Exception:
        logger.debug("nifty_ltp_last_cache_failed", exc_info=True)

    # Fallback — the market-data service's persistent last-quote (`mdlast`).
    try:
        md = await cache_get(f"mdlast:{NIFTY_TOKEN}")
        if isinstance(md, dict):
            lv = to_decimal(md.get("ltp") or 0)
            if lv > 0:
                return lv
    except Exception:
        logger.debug("nifty_ltp_mdlast_failed", exc_info=True)

    # Last resort — a stale live tick is still better than a blank screen.
    if live and live > 0:
        return live
    return None


async def resolve_nifty_window(
    open_dt: datetime, close_dt: datetime
) -> tuple[Decimal, Decimal, str] | None:
    """Return (open_price, close_price, source) for the 15m NIFTY candle that
    covers [open_dt, close_dt) IST. Returns None if unresolvable (settlement
    is then skipped and retried next tick — never settled at a bogus price)."""
    from app.services.zerodha_service import zerodha

    try:
        candles = await zerodha.get_historical(
            NIFTY_TOKEN, open_dt, close_dt, "15minute"
        )
    except Exception:
        logger.debug("nifty_historical_failed", exc_info=True)
        candles = []
    if candles:
        c = candles[0]
        o = to_decimal(c["open"])
        cl = to_decimal(c["close"])
        if o > 0 and cl > 0:
            return quantize_money(o), quantize_money(cl), "kite_15m"
    return None


# ── BTC ──────────────────────────────────────────────────────────────
async def btc_ltp() -> Decimal | None:
    try:
        from app.services.infoway_service import infoway

        tick = infoway.get_tick("BTCUSDT")
        if tick:
            v = to_decimal(tick.get("ltp") or 0)
            if v > 0:
                return v
    except Exception:
        logger.debug("btc_ltp_infoway_failed", exc_info=True)
    # REST fallback — Binance spot price.
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(
                "https://api.binance.com/api/v3/ticker/price",
                params={"symbol": "BTCUSDT"},
            )
            if r.status_code == 200:
                v = to_decimal(r.json().get("price") or 0)
                if v > 0:
                    return v
    except Exception:
        logger.debug("btc_ltp_binance_failed", exc_info=True)
    return None


async def _binance_klines(start_ms: int, end_ms: int) -> list[list]:
    """Private copy of the 15m Binance kline fetch (public, no auth)."""
    try:
        async with httpx.AsyncClient(timeout=6.0) as client:
            r = await client.get(
                BINANCE_KLINES,
                params={
                    "symbol": "BTCUSDT",
                    "interval": "15m",
                    "startTime": start_ms,
                    "endTime": end_ms,
                    "limit": 2,
                },
            )
            if r.status_code == 200:
                return r.json() or []
    except Exception:
        logger.debug("binance_klines_failed", exc_info=True)
    return []


async def resolve_btc_window(
    open_dt: datetime, close_dt: datetime
) -> tuple[Decimal, Decimal, str] | None:
    """Return (open, close, source) for the 15m BTC candle covering the
    window. Binance kline [openTime, open, high, low, close, ...]."""
    start_ms = int(open_dt.timestamp() * 1000)
    end_ms = int(close_dt.timestamp() * 1000) - 1
    klines = await _binance_klines(start_ms, end_ms)
    if klines:
        k = klines[0]
        o = to_decimal(k[1])
        cl = to_decimal(k[4])
        if o > 0 and cl > 0:
            return quantize_money(o), quantize_money(cl), "binance_15m"
    return None


# Canonical game key whose admin-typed manual result carries the day's OFFICIAL
# NIFTY close for ALL nifty games (Number + Jackpot + Bracket). The super-admin
# types it in the Number game's manual-result panel; one value fixes all three.
_MANUAL_NIFTY_CLOSE_KEY = "niftyNumber"


async def manual_nifty_close(ist_day: str, game_key: str = _MANUAL_NIFTY_CLOSE_KEY) -> Decimal | None:
    """Super-admin-typed official NIFTY close for `ist_day` (IST YYYY-MM-DD), or
    None if none typed. PER-GAME: each of Number / Jackpot / Bracket reads its OWN
    GameManualResult row (`game_key`), so the operator can declare a DIFFERENT
    close per game and the results stay independent — no cross-game leak. "Declare
    all 3" writes the same value to all three rows. Its mere presence signals
    operator intent (feed-down safety), no toggle required."""
    try:
        from app.models.games.bets import GameManualResult

        mr = await GameManualResult.find_one(
            GameManualResult.game_key == game_key,
            GameManualResult.day == ist_day,
        )
        if mr is not None and mr.close_price is not None:
            v = to_decimal(mr.close_price)
            if v > 0:
                return v
    except Exception:
        logger.debug("manual_nifty_close_read_failed", exc_info=True)
    return None


async def resolve_nifty_price_at(dt: datetime, strict: bool = False, game_key: str = "niftyNumber") -> Decimal | None:
    """NIFTY settlement price for a result that lands at / after market close.

    ``strict`` (used by the Number game): accept ONLY the authoritative official
    close — the pinned value or the post-close REST quote. Do NOT fall back to
    the last-traded historical candle (its DECIMALS differ from the official
    close, so the winning digit would be wrong) or the stale display cache (a
    flaky feed at result time otherwise settles on YESTERDAY's number — the
    07-14/07-15 duplicate bug). When the official close isn't available yet,
    return None so settlement WAITS (retries next tick) rather than declaring a
    wrong number. Non-strict callers (bracket / live spot) keep every fallback.

    Uses Zerodha's OFFICIAL closing candle — the last 1-minute historical candle
    of the session (15:29→15:30) — which is the authoritative daily close the
    admin terminal shows (e.g. 23,981.90 → number .90). This is what the
    operator treats as the "real" clearing value.

    Deliberately NOT the WS feed's last STREAMED tick (`mdlast`, via
    `nifty_ltp_display`): when the live feed drops before the final print it can
    sit ~20 pts below the official close (2026-07-09 it was 23,962.80 → .80,
    while the true Zerodha close was 23,981.90 → .90). It's also NOT a literal
    15:00–15:30 mean (that came to ~23,962.36 → .36) — the operator's "clearing
    price" is the official close candle, not the arithmetic average.

    During market hours the exact live LTP is returned. A 6-hour lookback makes
    a post-close result still find the session's final candle; a persisted
    fallback keeps settlement from ever stalling if historical is unavailable.
    On resolve it also refreshes the games display cache so the bracket / number
    "live spot" converges onto the same official value the admin shows."""
    from datetime import timedelta

    from app.core.redis_client import cache_get, cache_set
    from app.services.zerodha_service import zerodha
    from app.utils.time_utils import is_market_open, now_ist

    # Per-DAY official-close key. The REST quote only carries the official NSE
    # close for a short window right after 15:30; once it goes to 0 the resolver
    # would fall back to the (wrong) last-traded candle. So the FIRST time we get
    # the official close for a day we PIN it here (3-day TTL) and every later
    # resolve for that day reuses it — a re-settlement hours later stays correct.
    try:
        ist_day = (dt if dt.tzinfo is None else dt.astimezone(now_ist().tzinfo)).strftime("%Y-%m-%d")
    except Exception:
        ist_day = now_ist().strftime("%Y-%m-%d")
    day_key = f"games:nifty:close:{ist_day}"

    async def _converge(val: Decimal, *, pin_day: bool = False) -> Decimal:
        # Converge the games UI onto the settled value after market shut so the
        # bracket / number "live spot" matches settlement + the broker terminal.
        try:
            if dt.date() == now_ist().date():
                await cache_set(_NIFTY_LAST_KEY, str(val), ttl_sec=_NIFTY_LAST_TTL)
            if pin_day:
                await cache_set(day_key, str(val), ttl_sec=259200)  # 3 days
        except Exception:
            pass
        return val

    # -1) ADMIN MANUAL OVERRIDE (feed-down safety). When the Zerodha feed is down
    #     at close there is NO authoritative official close, so auto-resolution
    #     would settle every nifty game on a STALE cached value (the exact bug the
    #     operator hit: all 3 games settled at 23,991.25 while the feed was
    #     disconnected). If the super-admin has typed the day's official close, it
    #     WINS — for Number, Jackpot AND Bracket alike — over any pinned/quoted
    #     auto value. Applies when the market is closed, OR whenever the day being
    #     resolved is a PAST day (a manual re-declare of an earlier session must
    #     use the typed value even if today's market happens to be open). During
    #     TODAY's live hours the manual override is skipped so the live LTP below
    #     drives the live spot.
    _resolve_is_past_day = ist_day < now_ist().strftime("%Y-%m-%d")
    if not is_market_open() or _resolve_is_past_day:
        # PER-GAME manual close — read THIS game's own row so a different manual
        # value per game stays independent. Do NOT pin to the shared day key
        # (that would let one game's manual leak into another's auto-resolve);
        # the DB row is re-read fresh each time so no pin is needed.
        manual = await manual_nifty_close(ist_day, game_key)
        if manual is not None and manual > 0:
            return await _converge(quantize_money(manual), pin_day=False)

    # 1) Live LTP ONLY while the market is OPEN — the exact price right now.
    if is_market_open():
        live = await nifty_ltp()
        if live and live > 0:
            return live

    # 2) OFFICIAL NSE CLOSE = the Zerodha REST QUOTE's ltp after the session.
    #    NSE computes an index's official close as the WEIGHTED AVERAGE of the
    #    last 30 min (15:00–15:30) — the "clearing" price every broker terminal
    #    shows — and it lands in the REST quote's `ltp` a short while after close.
    #    We read this FRESH quote BEFORE the pin so the games converge onto the
    #    real clearing the moment it publishes, even if an EARLIER resolve pinned
    #    a pre-clearing tick while the feed was still catching up (the 22-Jul bug:
    #    pinned 23,991.25 while the clearing was 23,996.25). Re-pins on success so
    #    a later re-settle (quote gone → 0) still reads the correct value.
    try:
        from app.services import market_data_service

        q = await market_data_service.get_quote(str(NIFTY_TOKEN))
        qltp = quantize_money(to_decimal(q.get("ltp") or 0))
        fresh = qltp > 0 and not q.get("stale")
        if fresh and not strict:
            # Live-display / bracket-live path — use the fresh value immediately.
            return await _converge(qltp, pin_day=True)
        if fresh and strict:
            # SETTLEMENT stability gate: only lock the clearing once the fresh
            # quote has held the SAME value for `stable_window` seconds. NSE
            # publishes the clearing (last-30-min VWAP) a little after 15:30 and
            # the quote keeps updating until it lands on it — settling on the
            # first tick can catch a PRE-clearing value (22-Jul: 23,991.25 before
            # 23,996.25). So we wait for it to stop moving, however long the feed
            # takes to connect properly. Feed down / stale (ltp 0) → not `fresh`,
            # so the candidate is left untouched and we keep waiting.
            # Guard: only trust the value when the Zerodha SESSION is actually
            # live. A disconnected session returns a FROZEN last value (non-zero,
            # NOT flagged stale) that would otherwise look "stable" and settle on
            # the wrong close (23-Jul: session down → frozen 23,869.60 locked
            # instead of the real clearing). Session down → don't touch the
            # candidate, keep waiting; the operator declares via Manual Game Entry.
            try:
                from app.services.zerodha_service import zerodha as _zs

                # CROSS-WORKER FIX: the games settlement loop runs on the leader
                # worker, which is NOT necessarily the worker that ran the Kite
                # OAuth login. The Kite token lives in the ZerodhaSettings DB row
                # (`s.accessToken`), NOT as an in-memory attribute on the service
                # object — `getattr(_zs, "access_token", None)` was ALWAYS None, so
                # `session_live` was ALWAYS False and this whole clearing-lock block
                # NEVER ran → Number/Jackpot could never settle and got auto-
                # cancelled at 5 PM every day. Read the DB token instead: it is the
                # cross-process source of truth and the self-heal probe wipes it the
                # moment Kite says the session is dead, so its presence == alive.
                _zs_settings = await _zs._get_settings()
                session_live = bool(getattr(_zs_settings, "accessToken", None))
            except Exception:
                session_live = False

            if session_live:
                import time as _time

                from app.core.config import settings as _cfg

                stable_window = int(_cfg.GAMES_NIFTY_CLEARING_DELAY_SEC or 0)
                stab_key = f"games:nifty:candidate:{ist_day}"
                nowt = _time.time()
                try:
                    rec = await cache_get(stab_key)
                except Exception:
                    rec = None
                same = bool(rec) and to_decimal(rec.get("v") or 0) == qltp
                if same and (nowt - float(rec.get("t") or 0)) >= stable_window:
                    return await _converge(qltp, pin_day=True)  # stable → the clearing
                if not same:
                    try:
                        await cache_set(stab_key, {"v": str(qltp), "t": nowt}, ttl_sec=21600)
                    except Exception:
                        pass
                # else: same value but not stable long enough yet → wait
    except Exception:
        logger.debug("nifty_price_at_quote_failed", exc_info=True)

    # 0) Pinned official close — FALLBACK once the REST quote is gone (goes to 0
    #    later in the evening / next day). Preserves the last good clearing.
    if not is_market_open():
        try:
            pinned = await cache_get(day_key)
            if pinned:
                pv = to_decimal(pinned)
                if pv > 0:
                    return pv
        except Exception:
            logger.debug("nifty_day_pin_read_failed", exc_info=True)

    # STRICT (Number game): no last-traded / stale fallbacks — a wrong winning
    # digit is worse than a delayed result. Wait for the real official close.
    if strict:
        return None

    # 3) Fallback — last historical minute candle (last-traded close). Only used
    #    if the REST quote is unavailable (cold worker / API hiccup).
    try:
        candles = await zerodha.get_historical(
            NIFTY_TOKEN, dt - timedelta(hours=6), dt + timedelta(minutes=1), "minute"
        )
        if candles:
            cl = to_decimal(candles[-1]["close"])
            if cl > 0:
                return await _converge(quantize_money(cl))
    except Exception:
        logger.debug("nifty_price_at_failed", exc_info=True)

    # 4) Final fallback — persisted last-known so settlement never stalls.
    return await nifty_ltp_display()


async def resolve_nifty_last_candle_close(dt: datetime, game_key: str = "niftyBracket") -> Decimal | None:
    """CLOSE of the LAST 1-minute session candle at/just before `dt` — the exact
    "C" value the Zerodha chart shows for the final candle (the 15:29→15:30 print).
    Used by the BRACKET game (operator spec: "settle on the last candle's close").

    Why this and not the official-VWAP strict path the Number/Jackpot games use:
    the operator verifies the bracket result against the chart's last-candle close,
    and this value is drawn from the SAME Kite historical candles the chart is. It
    is also robust to a dropped WS LIVE feed — `get_historical` is a REST call,
    independent of the streaming session, so a frozen live tick can't skew it.

    Order of trust:
      1. Super-admin manual close (feed-down safety) — always wins when typed.
      2. Last 1-minute historical candle close (the chart's "C"). Pinned per-day.
      3. Pinned close from an earlier resolve today (REST hiccup right now).
    Returns None when nothing authoritative is available yet → the caller WAITS
    and retries next tick; it never settles on a stale / bogus price.
    """
    from datetime import timedelta

    from app.core.redis_client import cache_get, cache_set
    from app.services.zerodha_service import zerodha
    from app.utils.time_utils import now_ist

    try:
        ist_day = (dt if dt.tzinfo is None else dt.astimezone(now_ist().tzinfo)).strftime("%Y-%m-%d")
    except Exception:
        ist_day = now_ist().strftime("%Y-%m-%d")
    # BRACKET-ONLY pin key. MUST be distinct from the strict clearing key
    # `games:nifty:close:{day}` that resolve_nifty_price_at (Number/Jackpot) reads
    # as its fallback — otherwise the bracket's LAST-CANDLE close would overwrite
    # the official VWAP CLEARING and Number/Jackpot would settle on the closing.
    # Also do NOT touch `_NIFTY_LAST_KEY` (the shared display cache) here.
    day_key = f"games:nifty:lastcandle:{ist_day}"

    # 1) Manual SA override (feed-down safety) — always wins when typed. PER-GAME:
    #    read the bracket's own manual row so it's independent of Number/Jackpot.
    manual = await manual_nifty_close(ist_day, game_key)
    if manual is not None and manual > 0:
        return quantize_money(manual)  # DB re-read each time — no per-day pin needed

    # 2) LAST 1-minute historical candle close (the chart's "C"). REST call, so
    #    it's immune to a frozen WS tick and matches the chart exactly.
    try:
        candles = await zerodha.get_historical(
            NIFTY_TOKEN, dt - timedelta(hours=6), dt + timedelta(minutes=1), "minute"
        )
        if candles:
            cl = to_decimal(candles[-1]["close"])
            if cl > 0:
                v = quantize_money(cl)
                try:
                    await cache_set(day_key, str(v), ttl_sec=259200)
                except Exception:
                    pass
                return v
    except Exception:
        logger.debug("nifty_last_candle_close_failed", exc_info=True)

    # 3) Pinned close from an earlier resolve today (REST unavailable right now).
    try:
        pinned = await cache_get(day_key)
        if pinned:
            pv = to_decimal(pinned)
            if pv > 0:
                return pv
    except Exception:
        logger.debug("nifty_last_candle_pin_read_failed", exc_info=True)

    # Nothing authoritative yet → wait (retry next tick), never a bogus value.
    return None


async def resolve_btc_price_at(dt: datetime) -> Decimal | None:
    """BTC price AT the exact IST minute `dt` — the CLOSE of the 1-minute
    Binance candle that ENDS at `dt` (i.e. the last trade just before `dt`).

    This is the number Binance itself shows as the candle close at `dt`
    (e.g. the 15m 22:45 candle closes at 23:00 with the same value), so the
    game result matches Binance exactly. The old code took the candle that
    OPENS at `dt` (closing at dt+1m), which read the price a minute LATE and
    drifted ~10-40 pts on a fast tick. Live fallback for the current minute.
    """
    dt_ms = int(dt.timestamp() * 1000)
    target_open = dt_ms - 60_000  # the 1m candle whose close time == dt
    try:
        async with httpx.AsyncClient(timeout=6.0) as client:
            r = await client.get(
                BINANCE_KLINES,
                params={"symbol": "BTCUSDT", "interval": "1m",
                        "startTime": dt_ms - 180_000, "endTime": dt_ms + 60_000, "limit": 5},
            )
            if r.status_code == 200:
                data = r.json() or []
                # Exact candle closing at dt (openTime == dt − 1 min).
                for k in data:
                    if int(k[0]) == target_open:
                        cl = to_decimal(k[4])
                        if cl > 0:
                            return quantize_money(cl)
                # Fallback — the most recent candle that closed at/before dt.
                closed = [k for k in data if int(k[0]) <= target_open]
                if closed:
                    cl = to_decimal(closed[-1][4])
                    if cl > 0:
                        return quantize_money(cl)
    except Exception:
        logger.debug("btc_price_at_failed", exc_info=True)
    return await btc_ltp()


# ── Number-result digit extractors ───────────────────────────────────
def nifty_number_from_close(close) -> int:
    """Fractional two digits of the close, e.g. 23123.65 → 65."""
    c = to_decimal(close)
    frac = c - c.to_integral_value(rounding=ROUND_FLOOR)
    return int((frac * to_decimal(100)).to_integral_value(rounding=ROUND_FLOOR)) % 100


def btc_number_from_close(close) -> int:
    """Last two digits of the integer part, e.g. 75242.89 → 42."""
    c = to_decimal(close)
    return int(c.to_integral_value(rounding=ROUND_FLOOR)) % 100
