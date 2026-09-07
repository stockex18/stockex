"""Real market-data service — Zerodha (Indian) + Infoway (forex/crypto/etc).

NO mock/random-walk price generation. When no real feed is connected for
a token (Zerodha WS not subscribed AND Infoway not subscribed AND REST
snapshot unavailable), this service returns a zero-valued quote so the
UI clearly shows "—" for bid/ask/LTP instead of inventing fake prices.

Background tick loop publishes ticks ONLY when a real overlay updates
the cached quote — the loop no longer steps prices itself.

The service exposes:
    • get_ltp(token) → current price (Decimal); returns 0 if no feed
    • get_quote(token) → full quote shape (zeros when no feed)
    • subscribe(tokens) / unsubscribe(tokens) — in-memory tracking
    • tick_loop — publishes per-token ticks to Redis pub/sub for WS fanout.
"""

from __future__ import annotations

import asyncio
import json
import logging
from decimal import Decimal
from typing import Any

from app.core.redis_client import cache_get, cache_set, publish
from app.models.instrument import Instrument  # noqa: F401 — kept for downstream imports
from app.utils.decimal_utils import quantize_money, to_decimal

logger = logging.getLogger(__name__)

# In-memory state: token → quote dict
_state: dict[str, dict[str, Any]] = {}
_subscribed: set[str] = set()


def prune_subscribed_numeric(keep_tokens: set) -> int:
    """Drop numeric (Zerodha) tokens from `_subscribed` / `_state` that are NOT
    in `keep_tokens`. Called by the Zerodha LRU trim.

    The trim caps the Zerodha WS subscription at `keep_count` (1500 here), but
    it never touched `_subscribed` / `_state` — and THOSE are the sets
    `tick_loop` actually iterates (`_state INTERSECT _subscribed`). So as
    traders browse option chains all day the two grow unbounded while the WS
    stays at the cap. The loop then overlays every one of them per pass on a
    single core, stretching one pass from ~1 s to many — and every published
    price (option chain, positions, the risk enforcer's `mdlive`) goes that
    stale. That is the "rate ruk jaate hain" report: not a dead feed, a loop
    that cannot finish its lap.

    Bounding these two to the SAME keep-set as the WS fixes the per-pass work
    no matter how long the session runs. Symbol-style (crypto / forex) tokens
    are left alone — they are the other feed's concern, and they are not what
    grows. `mdlive` keys for dropped tokens expire on their own 30 s TTL.
    """
    keep_str = {str(int(t)) for t in keep_tokens if str(t).lstrip("-").isdigit()}
    dropped = 0
    for t in list(_subscribed):
        ts = str(t)
        if ts.lstrip("-").isdigit() and ts not in keep_str:
            _subscribed.discard(t)
            _state.pop(t, None)
            dropped += 1
    return dropped
_running: bool = False

# Multi-worker: True only on the worker that owns the upstream feed (set by
# main.py's feed leader-gate). Non-leader workers leave this False, which is
# what makes them PUBLISH cross-worker `feed:subscribe` requests instead of
# trying to subscribe a feed they don't run. On a single worker this flips
# True at boot, so subscribe() never publishes → behaviour identical to the
# pre-multi-worker code.
_is_feed_leader: bool = False


def set_feed_leader(is_leader: bool) -> None:
    """Called by main.py when this worker (de)acquires the feed leader lock."""
    global _is_feed_leader
    _is_feed_leader = bool(is_leader)


def is_feed_leader() -> bool:
    """True on the worker currently holding the `leader:feed` lock (runs the
    upstream feed + tick fanout). Used by the risk-shard admission gate to keep
    risk shards OFF the already-saturated feed-leader worker."""
    return _is_feed_leader


# In-memory token → symbol cache (avoids MongoDB lookup on every tick)
_token_symbol_cache: dict[str, str | None] = {}
_TOKEN_CACHE_WARM = False


async def _warm_token_symbol_cache() -> None:
    """Pre-load token→symbol mapping from Instrument collection once."""
    global _TOKEN_CACHE_WARM
    if _TOKEN_CACHE_WARM:
        return
    try:
        instruments = await Instrument.find_all().to_list()
        for instr in instruments:
            if instr.token and instr.symbol:
                _token_symbol_cache[str(instr.token)] = instr.symbol.upper()
        _TOKEN_CACHE_WARM = True
        logger.info("token_symbol_cache_warmed count=%d", len(_token_symbol_cache))
    except Exception:
        logger.exception("token_symbol_cache_warm_failed")


def _get_cached_symbol(token: str) -> str | None:
    """O(1) in-memory lookup. Returns None if not cached."""
    return _token_symbol_cache.get(token)


async def _resolve_symbol(token: str) -> str | None:
    """Resolve token to Infoway symbol. Uses in-memory cache first, falls back to MongoDB."""
    cached = _token_symbol_cache.get(token)
    if cached is not None:
        return cached
    instr = await Instrument.find_one(Instrument.token == token)
    if instr is None or not instr.symbol:
        _token_symbol_cache[token] = None  # type: ignore[assignment]
        return None
    sym = instr.symbol.upper()
    _token_symbol_cache[token] = sym
    return sym


def _empty_quote(token: str) -> dict[str, Any]:
    """Zero-valued quote skeleton. Overlays (Zerodha / Infoway) fill in
    real numbers if the instrument is subscribed; otherwise the UI sees
    zeros and renders "—" placeholders instead of fake prices.
    """
    return {
        "token": token,
        "ltp": 0.0,
        "open": 0.0,
        "high": 0.0,
        "low": 0.0,
        "prev_close": 0.0,
        "change": 0.0,
        "change_pct": 0.0,
        "volume": 0,
        "bid": 0.0,
        "ask": 0.0,
        "depth": {"bids": [], "asks": []},
        "ts": 0,
    }


async def _ensure_quote(token: str) -> dict[str, Any]:
    """Return the in-memory quote slot for `token`, creating an empty one
    if needed. NEVER fabricates a price — the slot stays at zero until a
    real overlay (Zerodha tick / Infoway tick / Kite REST snapshot)
    fills it in."""
    if token in _state:
        return _state[token]
    _state[token] = _empty_quote(token)
    return _state[token]


async def _zerodha_overlay(
    token: str, base_quote: dict[str, Any], *, allow_rest: bool = True
) -> dict[str, Any]:
    """If Zerodha is streaming this instrument, replace the mock LTP / bid /
    ask / OHLC / volume / depth with live exchange data. Falls through silently
    on any error so the UI stays usable in dev."""
    try:
        # Kite instrument tokens are always pure integers (e.g. 738561 for RELIANCE).
        # Non-integer tokens like "CRYPTO_BTCUSD" or "FOREX_EURUSD" belong to the
        # Infoway feed — sending them to Kite REST results in an "Invalid exchange"
        # error that takes up to 2 s to surface, causing zerodha_overlay_timeout and
        # risk_enforcer_tick_overrun on every tick where a crypto position is open.
        try:
            int(token)
        except (TypeError, ValueError):
            return base_quote

        from app.services.zerodha_service import zerodha

        # Circuit breaker: if no Zerodha WS connection is alive, skip the
        # entire overlay.  Without this, every quote request during a WS
        # outage (daily token rotation, Kite slot release delay) floods
        # the event loop with 2-second timeouts from DB lookups and REST
        # fallbacks, starving the self-heal loop and locking the WS in
        # CONNECTING forever.
        with zerodha._ticker_lock:
            _any_connected = any(e.get("connected") for e in zerodha._tickers)
        if not _any_connected and not zerodha.ticks_by_token:
            return base_quote

        # 1) Direct token lookup — mirrored Zerodha subscriptions store the
        #    Kite instrument_token as Instrument.token, so this is the fast path.
        live: dict[str, Any] | None = None
        try:
            live = zerodha.ticks_by_token.get(int(token))
        except (TypeError, ValueError):
            live = None

        # 2) Resolve symbol + exchange so we can hit symbol cache and REST fallback.
        instr = None
        sym: str | None = None
        ex_str: str | None = None
        if live is None:
            instr = await Instrument.find_one(Instrument.token == token)
            if instr is not None and instr.symbol:
                sym = instr.symbol
                ex_attr = getattr(instr, "exchange", None)
                if ex_attr is not None:
                    ex_str = ex_attr.value if hasattr(ex_attr, "value") else str(ex_attr)

            # If the local Instrument is missing (option contracts subscribed
            # before mirror existed, etc.), look the same token up in the
            # Zerodha subscribed list — it carries symbol + exchange too.
            if sym is None:
                from app.models.zerodha_settings import ZerodhaSettings

                zsettings = await ZerodhaSettings.find_one()
                if zsettings is not None:
                    try:
                        token_int = int(token)
                    except (TypeError, ValueError):
                        token_int = None
                    sub = None
                    if token_int is not None:
                        sub = next((i for i in zsettings.subscribedInstruments if i.token == token_int), None)
                    if sub is None:
                        sub = next(
                            (i for i in zsettings.subscribedInstruments if str(i.token) == token),
                            None,
                        )
                    if sub is not None:
                        sym = sub.symbol
                        ex_str = sub.exchange

            # Last-resort lookup: scan the Zerodha in-memory instruments
            # cache itself. This unlocks live data for EVERY Kite-listed
            # symbol the user can see in the instruments panel — without
            # needing an explicit admin subscribe or a MongoDB mirror. The
            # cache is keyed per exchange and is warmed at startup, so the
            # scan is in-process and fast. With sym + ex_str resolved here,
            # `get_quote_snapshot` (REST) and `subscribe_tokens_on_demand`
            # (WS) downstream do the rest.
            if sym is None:
                try:
                    token_int = int(token)
                except (TypeError, ValueError):
                    token_int = None
                if token_int is not None:
                    for ex_key, cache in zerodha._instruments_cache.items():
                        match = next(
                            (r for r in cache if int(r.get("token") or 0) == token_int),
                            None,
                        )
                        if match is not None:
                            sym = match.get("symbol")
                            ex_str = (match.get("exchange") or ex_key).upper()
                            break

        # 3) Symbol-keyed live tick (covers seeded NSE_EQ_RELIANCE-style tokens
        #    where the local token is text but the live tick is keyed by symbol).
        #
        # VERIFIED AGAINST THE TOKEN, not trusted on the symbol alone. This
        # cache is keyed by NAME, and a name is not unique here: the catalog
        # carries twelve symbols owned by three tokens each (BAJFINANCE lives
        # under 81153, 128008708 and NSE_EQ_BAJFINANCE). Whichever of them
        # ticks last owns the entry, and the other two would then be served
        # its price — one instrument showing another's rate, appearing and
        # disappearing as the feed decides who ticked last.
        #
        # Only enforced when this token is NUMERIC. A synthetic token
        # (NSE_EQ_RELIANCE) is exactly the case this fallback exists for and
        # can never match the Kite token in the tick, so requiring it would
        # switch the fallback off for the instruments that need it.
        if live is None and sym:
            _cand = zerodha.ticks_by_symbol.get(sym)
            if _cand is not None:
                _mine = str(token).lstrip("-").isdigit()
                if not _mine or str(_cand.get("token") or "") == str(token):
                    live = _cand
                else:
                    logger.warning(
                        "symbol_tick_token_mismatch",
                        extra={
                            "token": token,
                            "symbol": sym,
                            "tick_token": _cand.get("token"),
                        },
                    )

        # 4) REST `/quote` fallback — when the ticker has no recent push for
        #    this instrument (weekends, pre-open, fresh subscribe before the
        #    first tick arrives) we still want real exchange data, not mock.
        if not live and sym and ex_str and allow_rest:
            snap = await zerodha.get_quote_snapshot(ex_str, sym)
            if snap:
                # Same check. The snapshot is fetched BY SYMBOL, so it is only
                # this token's price if the symbol we resolved really belongs
                # to this token.
                _mine = str(token).lstrip("-").isdigit()
                if not _mine or str(snap.get("token") or "") in ("", "0", str(token)):
                    live = snap
                else:
                    logger.warning(
                        "rest_snapshot_token_mismatch",
                        extra={
                            "token": token,
                            "symbol": sym,
                            "snap_token": snap.get("token"),
                        },
                    )

        if not live:
            return base_quote

        merged = dict(base_quote)
        # LTP: a 0 is "this packet carried no price", never "the price is
        # zero". A traded instrument cannot print 0, and every normaliser in
        # zerodha_service builds `ltp` as `float(... or 0)` — so a thin packet,
        # a REST snapshot with no `last_price`, or a symbol that has not traded
        # yet all arrive as a hard 0. The plain merge below USED to write that
        # straight over a perfectly good live price: the screen blanked to 0
        # for a second, `mdlive` mirrored the 0 to every other worker, and the
        # order gate saw "no live price" on a contract that was quoting fine.
        # Same rule the OHLC block below has always used — hold the last real
        # value until a real one replaces it.
        try:
            _live_ltp = float(live.get("ltp") or 0)
        except (TypeError, ValueError):
            _live_ltp = 0.0
        if _live_ltp > 0:
            merged["ltp"] = live.get("ltp")

        # OHLC/volume: keep the previous value unless the tick carries a REAL
        # one. `.get(k, default)` is not enough here — the key is always
        # PRESENT, it is the VALUE that is 0.
        #
        # Kite's LTP-mode packet is 8 bytes and carries no `ohlc` block at all
        # (see zerodha_service._parse_binary: `if length == 8: ... return`).
        # The normalizer turns that missing block into `high: 0, low: 0,
        # open: 0, close: 0, volume: 0`, so the plain merge above USED to
        # overwrite a perfectly good day-high with 0 every time one of those
        # packets arrived — and it stayed wrong until the next 44-byte quote
        # packet restored it. That is the "NSE/MCX high-low goes wrong for a
        # bit, then fixes itself" report: purely a display corruption from a
        # thinner packet, never bad exchange data.
        #
        # A genuine 0 is meaningless for all six fields (a traded instrument
        # cannot have a 0 high, and 0 volume is what an LTP packet reports for
        # everything), so treating 0 as "not supplied" is safe and is what
        # keeps the value stable across mixed packet modes.
        def _keep(key: str, src_key: str | None = None) -> None:
            try:
                v = float(live.get(src_key or key) or 0)
            except (TypeError, ValueError):
                return
            if v > 0:
                merged[key] = live.get(src_key or key)

        _keep("open")
        _keep("high")
        _keep("low")
        _keep("prev_close", "close")
        _keep("volume")
        # Carry the exchange's own packet time through to `_state` → mdlive →
        # the published tick, so EVERY worker (esp. non-leaders that only see
        # mdlive) can gate order freshness on the live-session signal rather
        # than the snapshot-fooled frame-arrival time.
        if live.get("exchange_timestamp"):
            merged["exchange_timestamp"] = live.get("exchange_timestamp")

        # 5-level depth — Kite ticks expose depth.buy/depth.sell when
        # subscribed in MODE_FULL. Translate to our schema (bids/asks) and
        # ALSO derive top-of-book bid/ask from it.
        depth = live.get("depth")
        best_bid_from_depth: float | None = None
        best_ask_from_depth: float | None = None
        if isinstance(depth, dict):
            bids = depth.get("buy") or []
            asks = depth.get("sell") or []
            if bids or asks:
                merged["depth"] = {
                    "bids": [
                        {
                            "price": float(b.get("price") or 0),
                            "qty": int(b.get("quantity") or 0),
                            "orders": int(b.get("orders") or 0),
                        }
                        for b in bids[:5]
                    ],
                    "asks": [
                        {
                            "price": float(a.get("price") or 0),
                            "qty": int(a.get("quantity") or 0),
                            "orders": int(a.get("orders") or 0),
                        }
                        for a in asks[:5]
                    ],
                }
                try:
                    if bids and float(bids[0].get("price") or 0) > 0:
                        best_bid_from_depth = float(bids[0]["price"])
                    if asks and float(asks[0].get("price") or 0) > 0:
                        best_ask_from_depth = float(asks[0]["price"])
                except (TypeError, ValueError, KeyError):
                    pass

        # Bid / ask resolution — ONLY real exchange data:
        #   1. Explicit `live.bid` / `live.ask` (set by REST snapshot
        #      or MODE_FULL pushes)
        #   2. Top of Kite depth book (MODE_FULL ticks)
        #   No synthesised fallback — when no real bid/ask is available,
        #   leave the field at 0 so downstream code (order panel, limit-
        #   away validator) can detect "no live quote" and refuse to
        #   accept opening trades on illiquid contracts. The admin
        #   segment-spread overlay that runs LATER in this chain still
        #   gets to synthesise bid/ask from LTP ± half-spread for
        #   segments with `spread_pips > 0` — only instruments with
        #   neither real depth NOR an admin spread end up at 0.
        #
        # Operator-flagged 22-May: deep-OTM options like GOLD150000CE
        # had no real depth and no admin spread, so bid/ask were quietly
        # mirrored to the (stale) LTP and the order panel showed a
        # "tradeable" price on contracts that physically can't fill.
        # Trade would either reject mid-flight or fill at a junk price.
        live_bid = float(live.get("bid") or 0)
        live_ask = float(live.get("ask") or 0)
        if live_bid > 0:
            merged["bid"] = live_bid
        elif best_bid_from_depth and best_bid_from_depth > 0:
            merged["bid"] = best_bid_from_depth
        else:
            merged["bid"] = 0.0
        if live_ask > 0:
            merged["ask"] = live_ask
        elif best_ask_from_depth and best_ask_from_depth > 0:
            merged["ask"] = best_ask_from_depth
        else:
            merged["ask"] = 0.0

        if merged["prev_close"]:
            merged["change"] = round(merged["ltp"] - merged["prev_close"], 2)
            merged["change_pct"] = round((merged["change"] / merged["prev_close"]) * 100, 2)
        merged["source"] = "zerodha"
        return merged
    except Exception:
        return base_quote


async def _infoway_overlay(token: str, base_quote: dict[str, Any]) -> dict[str, Any]:
    """Overlay live Infoway tick (forex / crypto / metals / energy). Infoway
    is keyed by SYMBOL (BTCUSDT, EURUSD, XAUUSD…); we resolve via the
    Instrument doc.

    Don't gate on `infoway.is_connected` — that property reaches into the
    websockets client object whose API changed between library versions and
    can throw / return False even while ticks are still in the cache. The
    cache itself is the source of truth: if there's a fresh tick keyed by
    this symbol, use it.
    """
    try:
        from app.services.infoway_service import infoway

        sym = await _resolve_symbol(token)
        if not sym:
            return base_quote
        live = infoway.get_tick(sym) or infoway.get_tick(sym + "T")
        if not live:
            return base_quote
        ltp = float(live.get("ltp") or 0)
        if ltp <= 0:
            return base_quote
        merged = dict(base_quote)
        merged["ltp"] = ltp
        # Real best-bid / best-ask from Infoway depth book. When the feed
        # publishes no bid/ask (dead / illiquid symbol), leave the side at
        # 0 instead of collapsing to LTP — the order panel reads a 0 here
        # as "no live quote" and disables that side of the trade. The
        # admin segment-spread overlay still runs AFTER this; segments
        # with `spread_pips > 0` will synthesise bid/ask from LTP, so
        # only symbols with neither real depth NOR an admin spread end
        # up at 0.
        live_bid = float(live.get("bid") or 0)
        live_ask = float(live.get("ask") or 0)
        merged["bid"] = live_bid if live_bid > 0 else 0.0
        merged["ask"] = live_ask if live_ask > 0 else 0.0
        merged["volume"] = float(live.get("volume") or merged.get("volume") or 0)
        if live.get("close_24h"):
            merged["prev_close"] = float(live["close_24h"])
        merged["change"] = float(live.get("change") or merged.get("change") or 0)
        merged["change_pct"] = float(live.get("change_pct") or merged.get("change_pct") or 0)
        # Running intraday OHLC synthesised from tick stream — overlay only
        # when the Infoway service has seen at least one tick for this symbol.
        if live.get("open"):
            merged["open"] = float(live["open"])
        if live.get("high"):
            merged["high"] = float(live["high"])
        if live.get("low"):
            merged["low"] = float(live["low"])
        # Overlay real depth too if Infoway has a book for this symbol
        depth = infoway.depth.get(sym) or infoway.depth.get(sym + "T")
        if depth and depth.get("bids") and depth.get("asks"):
            merged["depth"] = {"bids": depth["bids"], "asks": depth["asks"]}
        merged["source"] = "infoway"
        # USD/INR snapshot so the frontend can show margin in real INR
        # rather than displaying the USD number with a 🪙 symbol (which is
        # how users end up trying to place orders worth 80× their wallet).
        merged["fx_rate"] = get_usd_inr_rate()
        return merged
    except Exception:
        logger.exception("infoway_overlay_failed token=%s", token)
        return base_quote


async def _overlay_all(
    token: str, base: dict[str, Any], *, allow_rest: bool = True
) -> dict[str, Any]:
    """Apply Infoway first (forex/crypto/metals/energy), then Zerodha (Indian).
    Whichever provider has live data wins.

    Both overlays may hit external services — Infoway reads from a local
    in-memory tick map (fast) but the Zerodha fallback issues a Kite REST
    `/quote` call that can stall when Kite is slow / TCP RST'd. We hard-cap
    each overlay at 2 seconds so a hung external service can NEVER freeze
    callers like `order_service.place_order` → `matching_engine.execute_market_order`
    → `get_ltp`. On timeout the overlay falls back to the cached base quote
    (last-known real value or zero) — never a fabricated price.

    After both feed overlays run, the admin's per-segment spread (Fixed /
    Floating + spread_pips) is applied as the final pass. This is the
    "money changer" markup — bid moves down half-spread, ask moves up
    half-spread, around the live LTP. Cached resolution per
    `(segment, symbol)` for 30 s so the 250 ms WS pump doesn't go to
    Mongo on every tick.
    """
    try:
        after_infoway = await asyncio.wait_for(_infoway_overlay(token, base), timeout=2.0)
    except asyncio.TimeoutError:
        logger.warning("infoway_overlay_timeout", extra={"token": token})
        after_infoway = base
    except Exception:
        logger.exception("infoway_overlay_failed", extra={"token": token})
        after_infoway = base
    if after_infoway.get("source") == "infoway":
        return await _apply_admin_spread(token, after_infoway)
    # Per-token negative cache: a token with no live WS tick whose Kite REST
    # `/quote` snapshot just timed out is almost certainly illiquid / beyond
    # the WS cap / not pushing. Re-issuing the 2 s REST on every 5 s pump tick
    # froze the event loop for nothing (the timeout already falls back to
    # `base`). Skip ONLY the REST fallback for a short window; the fast
    # in-memory `ticks_by_token` / `ticks_by_symbol` checks inside
    # `_zerodha_overlay` STILL run, so the instant a token starts ticking
    # again it is served live (the warm path is reached before this gate).
    # A Kite REST call belongs to the FEED, never to a user's request. Warming
    # a token that has no websocket tick yet is the feed loop's job; doing it
    # while somebody waits for a quote put a ~2 s Kite round-trip inside the
    # request, and production logged 6,078 `zerodha_overlay_timeout` — 2 s of
    # a two-core event loop, each, for a price the mirror already held.
    #
    # Reads are served from what the feed stored: the in-memory tick cache,
    # `_state`, `mdlive`, and `mdlast` behind them. The feed loop still calls
    # REST, so a newly-added instrument still warms within a tick or two — the
    # user just is not made to wait for it.
    _now = _t.time()
    _allow_rest = allow_rest and _now >= _zerodha_rest_skip.get(token, 0.0)
    try:
        zerodha_quote = await asyncio.wait_for(
            _zerodha_overlay(token, base, allow_rest=_allow_rest), timeout=2.0
        )
    except asyncio.TimeoutError:
        logger.warning("zerodha_overlay_timeout", extra={"token": token})
        _zerodha_rest_skip[token] = _now + _ZERODHA_REST_SKIP_TTL_SEC
        zerodha_quote = base
    except Exception:
        logger.exception("zerodha_overlay_failed", extra={"token": token})
        zerodha_quote = base
    return await _apply_admin_spread(token, zerodha_quote)


# Token → segment cache so the spread step doesn't re-fetch the Instrument
# doc on every tick. Segment is essentially immutable for a token (changes
# only via admin edit), so a 5-min TTL is plenty. Misses fall through to
# Mongo and re-cache. Falsy values aren't cached (an instrument that doesn't
# exist yet might be mirrored on the next call).
_SEGMENT_FOR_TOKEN_TTL = 300
_SEGMENT_FOR_TOKEN_PREFIX = "spread_seg:"


async def _segment_for_token(token: str) -> tuple[str, str] | None:
    """Return `(segment_type, symbol_upper)` for a token, or None if the
    instrument isn't in our collection."""
    cache_key = f"{_SEGMENT_FOR_TOKEN_PREFIX}{token}"
    try:
        from app.core.redis_client import cache_get, cache_set

        cached = await cache_get(cache_key)
        if cached is not None:
            return (cached.get("seg") or "", cached.get("sym") or "")
    except Exception:
        cache_set = None  # type: ignore[assignment]

    instr = await Instrument.find_one(Instrument.token == token)
    if instr is None:
        return None
    seg_value = getattr(instr.segment, "value", instr.segment)
    sym = (instr.symbol or "").upper()
    payload = {"seg": str(seg_value), "sym": sym}
    try:
        if cache_set is not None:
            await cache_set(cache_key, payload, ttl_sec=_SEGMENT_FOR_TOKEN_TTL)
    except Exception:
        pass
    return (str(seg_value), sym)


async def get_segment_for_token(token: str) -> tuple[str, str] | None:
    """Public wrapper — return ``(segment_type, symbol_upper)`` for an
    instrument token, or ``None`` when not found. Results are cached in
    Redis for ~5 min so repeated calls during subscribe are cheap."""
    return await _segment_for_token(token)


async def _apply_admin_spread(token: str, quote: dict[str, Any]) -> dict[str, Any]:
    """Final overlay: apply the admin-configured spread to the live quote.

    Fixed mode  → bid = ltp − pips/2, ask = ltp + pips/2 every tick. The
                  exchange spread is ignored entirely (broker-set markup).
    Floating    → keep the live (ask − bid), but widen symmetrically around
                  ltp when it falls below `spread_pips`. Implements the
                  "real spread, but never less than minimum" rule.

    `spread_pips` is interpreted as PRICE UNITS for that instrument (admin
    sees the same units they'd see on the chart — 0.0002 for EURUSD,
    0.50 for XAUUSD, 5 for NIFTY). Zero or negative → no spread mod.

    Skipped when `spread_pips <= 0` so admin can opt out by leaving the
    field blank.
    """
    try:
        ltp = float(quote.get("ltp") or 0)
        if ltp <= 0:
            return quote

        seg_sym = await _segment_for_token(token)
        if seg_sym is None:
            return quote
        seg_type, symbol = seg_sym

        # Translate instrument segment → admin row name (NSE_EQ / FOREX /
        # CRYPTO / …) the way the rest of the resolver stack does.
        from app.services.netting_service import _SEGMENT_NAME_MAP, resolve_spread

        admin_row = _SEGMENT_NAME_MAP.get(seg_type, seg_type)
        cfg = await resolve_spread(admin_row, symbol)
        pips = float(cfg.get("spread_pips") or 0)
        if pips <= 0:
            return quote
        mode = str(cfg.get("spread_type") or "fixed").lower()

        half = pips / 2.0
        live_bid = float(quote.get("bid") or 0)
        live_ask = float(quote.get("ask") or 0)
        live_spread = (live_ask - live_bid) if (live_bid > 0 and live_ask > 0) else 0.0

        if mode == "fixed":
            merged = dict(quote)
            merged["bid"] = ltp - half
            merged["ask"] = ltp + half
            return merged

        # Floating: keep market spread until it's tighter than the minimum,
        # then widen to the minimum around the LTP midpoint.
        if live_spread < pips:
            merged = dict(quote)
            merged["bid"] = ltp - half
            merged["ask"] = ltp + half
            return merged
        return quote
    except Exception:
        logger.exception("admin_spread_overlay_failed", extra={"token": token})
        return quote


# ── USD → INR conversion (forex / crypto P&L is reported in INR) ─────
USD_INR_FALLBACK = 83.0  # used only if Infoway hasn't pushed a USDINR tick yet


def get_usd_inr_rate() -> float:
    """Live USD/INR conversion rate. Infoway subscribes to USDINR by default,
    so this is the rate at which crypto / forex P&L gets translated for
    Indian wallets. Falls back to a sensible constant on a cold start."""
    try:
        from app.services.infoway_service import infoway

        for sym in ("USDINR", "USDINR=X", "USD/INR"):
            tick = infoway.get_tick(sym)
            if tick:
                ltp = float(tick.get("ltp") or 0)
                if ltp > 0:
                    return ltp
    except Exception:  # noqa: BLE001
        pass
    return USD_INR_FALLBACK


def is_infoway_lot_segment(segment: str | None) -> bool:
    """Whether the segment is sourced from the Infoway feed for lot-table
    resolution purposes. STOCKS / INDICES / CRYPTO / FOREX / COMMODITIES /
    CDS — every segment that does NOT come from the Zerodha-fed NSE / BSE
    / MCX / NFO / BFO lot tables.

    This is the segment classifier the ORDER PLACEMENT path uses to pick
    between `infoway_lots.get_infoway_lot_size` and the canonical Indian
    lot tables. It is intentionally separate from `is_usd_quoted_segment`
    below: that flag now governs *FX conversion* of P&L / margin only, and
    has been disabled per the broker's spec ("treat the Infoway feed price
    as INR directly"). Without this split, disabling FX conversion would
    also break lot-size resolution for forex/crypto/etc.
    """
    s = (segment or "").upper()
    if s in ("STOCKS", "INDICES"):
        return True
    return (
        "CRYPTO" in s
        or "FOREX" in s
        or "FX" in s
        or "CDS" in s
        or "COMMODITIES" in s
    )


def is_usd_quoted_segment(segment: str | None) -> bool:
    """Whether the segment's P&L / margin needs USD→INR conversion.

    Per the broker's spec, Infoway-feed prices (forex / crypto / spot
    metals / energy / international stocks & indices) are now treated as
    INR directly — there is no live USD→INR multiplication on P&L, no
    margin scaling, and the UI renders these prices with 🪙 rather than $.
    So this helper always returns False; every legacy call site that gated
    FX conversion on it becomes a no-op without further changes.

    For Infoway lot-table selection use ``is_infoway_lot_segment`` above.
    """
    # Reference the parameter so linters don't flag it unused — the
    # signature is kept stable for every existing caller.
    _ = segment
    return False


# Short in-process overlay cache (token → (timestamp_ms, payload)). The
# overlay pipeline blocks on Zerodha + Infoway sequentially with a 2 s
# timeout each — when the chart datafeed, the OrderPanel, the
# MobileQuickTradeBar, and the positions overlay all call get_quote for
# the same token within ~500 ms, the user paid for that overlay 4 times.
# A 700 ms TTL is short enough that a stale price never lingers visibly
# (the WS pump runs every 1 s anyway) but kills the duplicate-fanout cost.
import time as _t

# 200 ms, not 700. Each worker caches quotes independently, so this window is
# ALSO the worst-case disagreement BETWEEN workers: two workers whose caches
# filled at different moments can serve prices this far apart, and the REST
# quote path (`/instruments/quotes/batch` → positions, order panel) is load
# balanced across them — so the same instrument appeared to jump backwards
# between polls. The WS path is unaffected (leader-published, already
# consistent). Measured feed lag from the exchange is ~1 s, so 700 ms of extra
# cache staleness was a large share of what the user saw.
_QUOTE_CACHE_TTL_MS = 200
_quote_cache: dict[str, tuple[int, dict[str, Any]]] = {}

# Per-token negative cache for the Zerodha REST `/quote` fallback. A token
# that has no live WS tick AND whose REST snapshot times out is marked here
# so subsequent get_quote calls skip the (useless, 2 s) REST for this window
# instead of re-freezing the pump every tick. Short TTL + the fact that a
# revived token is served by the in-memory tick path BEFORE the REST gate
# means a recovering symbol is never held back. Bounded by the count of
# distinct dead tokens (a few hundred at most); entries self-expire by time.
_ZERODHA_REST_SKIP_TTL_SEC = 30.0
_zerodha_rest_skip: dict[str, float] = {}


# ── Last-known price (DISPLAY-ONLY fallback) ─────────────────────────
# When a market is closed (e.g. spot gold XAUUSD over the weekend) or the
# Infoway/Zerodha feed has no live tick, the overlay yields ltp = 0 and the
# UI shows a dead "0.00 / feed unavailable" panel. To still show the trader
# a reference, we persist the LAST good quote per token to Redis and, when
# the live overlay produces no price, attach it as a SEPARATE `last_ltp`
# field (plus the last OHLC for the header).
#
# SAFETY: we deliberately do NOT revive the live `ltp` / `bid` / `ask`.
# Those stay 0 so (a) the matching engine keeps rejecting fills on a dead
# feed (`get_ltp` returns 0 → STALE_FEED guard) and (b) the order panel's
# BUY/SELL stay disabled. `last_ltp` is for display only — never execution.
_LAST_QUOTE_KEY = "mdlast:{token}"
_LAST_QUOTE_TTL_SEC = 7 * 86400  # a week — covers weekend / holiday feed gaps


async def _persist_last_quote(token: str, q: dict[str, Any]) -> None:
    try:
        if float(q.get("ltp") or 0) > 0:
            await cache_set(
                _LAST_QUOTE_KEY.format(token=token),
                {
                    "ltp": float(q["ltp"]),
                    "open": float(q.get("open") or 0),
                    "high": float(q.get("high") or 0),
                    "low": float(q.get("low") or 0),
                    "prev_close": float(q.get("prev_close") or 0),
                    "source": q.get("source"),
                    "ts": int(_t.time() * 1000),
                },
                ttl_sec=_LAST_QUOTE_TTL_SEC,
            )
    except Exception:  # pragma: no cover - cache write must never break a quote
        pass


async def _attach_last_quote(token: str, q: dict[str, Any]) -> dict[str, Any]:
    # Live price present → nothing to do.
    if float(q.get("ltp") or 0) > 0:
        return q
    try:
        last = await cache_get(_LAST_QUOTE_KEY.format(token=token))
    except Exception:  # pragma: no cover
        last = None
    if not last or float(last.get("ltp") or 0) <= 0:
        return q
    out = dict(q)
    out["last_ltp"] = float(last["ltp"])
    out["last_ts"] = last.get("ts")
    out["stale"] = True
    # Fill the header OHLC so the chart strip shows the last session's
    # numbers instead of "—". Does NOT touch ltp/bid/ask (kept at 0).
    for k in ("open", "high", "low", "prev_close"):
        if not out.get(k) and last.get(k):
            out[k] = float(last[k])
    return out


# ── Live cross-worker price snapshot (multi-worker, execution-safe) ──
# Only the LEADER worker runs the upstream feed + tick_loop, so non-leader
# workers have a permanently-cold `_state`. The leader mirrors each live
# overlaid quote into Redis (`mdlive:{token}`) every tick; a non-leader's
# `get_quote` reads it BEFORE `_overlay_all` (which would otherwise fire a
# ~2 s Kite REST per cold quote). Unlike the display-only `mdlast`, `mdlive`
# carries live ltp/bid/ask exactly as the leader served it and IS safe for
# execution — short TTL so a dead leader can't feed stale fills. On a single
# warm worker `_state` is always warm, so the cold-path read never runs and
# behaviour is unchanged.
_MDLIVE_KEY = "mdlive:{token}"
_MDLIVE_TTL_SEC = 30

#: A quote whose EXCHANGE stamp is older than this is not a live price. Same
#: threshold the order validator blocks opens at, so what the screen calls
#: stale is exactly what the server refuses to fill against.
_QUOTE_STALE_SEC = 2.0

def _mirrorable(q: dict[str, Any]) -> bool:
    """Whether this quote may go into the cross-worker `mdlive` mirror.

    The mirror must not resurrect a price from a PREVIOUS session: the tick
    loop rewrites the key every second, so its 30 s TTL would never lapse and
    an expired or never-opened contract would look live for ever.

    This used to be a flat 10-minute age cap, which threw out the wrong thing.
    A contract that has not printed for eleven minutes is not dead - it is
    ILLIQUID, and most of the option chain is. The leader kept serving its held
    price out of `_state` while the mirror dropped it, so the four non-leader
    workers fell through to `mdlast` and answered with the PREVIOUS DAY'S
    CLOSE. The favourites list polls every 2 s and lands on a different worker
    each time, so the two alternated on screen:

        operator: "last ka closing show ho raha kuch time ke liye ...
                   achanak se flicker se clearing aa rahi, last day ki"

    Measured mid-session: 49 of 372 subscribed instruments passed the 10-minute
    gate. The other 323 were flickering.

    The real question was never "how old" but "is this from TODAY'S session",
    so that is what it asks now - no threshold to tune, and a held intraday
    price is served identically by every worker. It stays marked with its
    `age_sec`, so a consumer can still tell a held price from a fresh one.

    A feed with no exchange clock at all (Infoway crypto / forex) has nothing
    to judge and is always mirrored, exactly as before.
    """
    try:
        ets = float(q.get("exchange_timestamp") or 0)
    except (TypeError, ValueError):
        return True
    if ets <= 0:
        return True
    try:
        from datetime import datetime as _dt

        from app.utils.time_utils import IST, now_ist

        return _dt.fromtimestamp(ets, IST).date() == now_ist().date()
    except Exception:  # noqa: BLE001 - never let a clock problem blank the feed
        return True


def _mark_freshness(q: dict[str, Any]) -> dict[str, Any]:
    """Stamp `age_sec` / `stale` from the EXCHANGE's own clock.

    Deliberately not `ts`: the tick loop rewrites that every second whether or
    not the price moved, which is precisely why a frozen quote looked live.

    A feed with no exchange clock (Infoway crypto / forex) reports `age_sec =
    None` and `stale = False` — there is nothing to measure it against, and
    calling it stale would blank those segments.
    """
    try:
        ets = float(q.get("exchange_timestamp") or 0)
    except (TypeError, ValueError):
        ets = 0.0
    if ets > 0:
        age = _t.time() - ets
        q["age_sec"] = round(age, 1)
        q["stale"] = age > _QUOTE_STALE_SEC
    else:
        q["age_sec"] = None
        # Do NOT clear a flag that was set deliberately. `_attach_last_quote`
        # marks a LAST-SESSION fallback price stale, and such a quote carries no
        # exchange clock — so it lands in exactly this branch and used to have
        # the mark wiped. The screen then showed Friday's close on Saturday with
        # nothing saying so, while `get_quotes` (which skips this stamp) still
        # reported it stale: the same price, two answers.
        # Nothing could TRADE on it either way — ltp/bid/ask stay 0 and the
        # engine's stale-feed guard holds — but a price with no session on it is
        # exactly the kind of quiet wrongness this feed rework exists to stop.
        q["stale"] = bool(q.get("stale"))
    return q

# Cross-worker feed-subscription channel (see subscribe / feed_subscribe_listener).
FEED_SUBSCRIBE_CHANNEL = "feed:subscribe"


# token(str) → market-control segment, cached in-process (segment never changes).
_TOKEN_MC_SEG: dict[str, str | None] = {}


async def _mc_seg_for_token(token) -> str | None:
    """Market-control segment code for a feed token, or None.

    Feed tokens are inconsistent: some carry a class prefix ('CRYPTO_BTCUSD',
    'FOREX_EURUSD'), others are bare ('BTCUSDT' — a crypto perpetual — or an
    integer Zerodha token). So the fast prefix path is backed by an instrument
    lookup that resolves the real admin-row segment (netting_service._seg_name_for)
    for bare tokens, cached forever in-process."""
    t = str(token)
    if t in _TOKEN_MC_SEG:
        return _TOKEN_MC_SEG[t]
    seg: str | None = None
    if "_" in t and not t.replace("_", "").isdigit():
        seg = t.split("_", 1)[0].upper()  # CRYPTO_BTCUSD → CRYPTO
    else:
        try:
            from app.models.instrument import Instrument
            from app.services import netting_service

            coll = Instrument.get_motor_collection()
            doc = await coll.find_one({"token": t}, {"segment": 1, "symbol": 1})
            if doc is None and t.isdigit():
                doc = await coll.find_one({"token": int(t)}, {"segment": 1, "symbol": 1})
            if doc:
                seg = netting_service._seg_name_for(doc.get("segment"), doc.get("symbol"))
        except Exception:
            seg = None
    _TOKEN_MC_SEG[t] = seg
    return seg


async def _write_mdlive_batch(items: list[tuple[str, dict[str, Any]]]) -> None:
    """Leader-only: mirror this tick's live quotes to Redis in ONE pipeline.

    Writes BOTH keys for the same quote:

      mdlive:{token}   30 s   execution-safe live snapshot
      mdlast:{token}    7 d   display fallback for when the live one is gone

    `mdlast` used to be written only by `_persist_last_quote`, which sits on
    the SLOW quote path. Once a token started being served from the mirror that
    path stopped running for it and its `mdlast` simply froze. Measured
    mid-session, against tokens the mirror was actively serving:

        median staleness   2,202 min   (36.7 hours)
        worst              8,403 min   (5.8 days)

        BANKNIFTY26SEP56800CE   mdlast 1148.25   live 980.10
        CRUDEOIL26SEP8500PE     mdlast  280.70   live 222.10

    So the moment the mirror missed a token for even one read - a key expiring
    a beat before the next tick rewrote it - the fallback handed back a price
    from DAYS ago. That is the operator's "same like closing price for 2
    seconds" on EICHERMOT: not a closing price, a days-old one, and gone again
    before anyone could screenshot it.

    Keeping them together is what makes the fallback safe: it is now at worst
    one tick behind rather than one session, and `_attach_last_quote` still
    refuses to put it in `ltp`/`bid`/`ask`, so nothing can execute against it.

    Best-effort — a cache write must never break the tick loop.
    """
    if not items:
        return
    try:
        from app.core.redis_client import get_redis

        pipe = get_redis().pipeline(transaction=False)
        for token, payload in items:
            blob = json.dumps(payload, default=str)
            pipe.set(
                _MDLIVE_KEY.format(token=token),
                blob,
                ex=_MDLIVE_TTL_SEC,
            )
            try:
                if float(payload.get("ltp") or 0) > 0:
                    pipe.set(
                        _LAST_QUOTE_KEY.format(token=token),
                        json.dumps(
                            {
                                "ltp": float(payload["ltp"]),
                                "open": float(payload.get("open") or 0),
                                "high": float(payload.get("high") or 0),
                                "low": float(payload.get("low") or 0),
                                "prev_close": float(payload.get("prev_close") or 0),
                                "source": payload.get("source"),
                                "ts": int(_t.time() * 1000),
                            },
                            default=str,
                        ),
                        ex=_LAST_QUOTE_TTL_SEC,
                    )
            except (TypeError, ValueError):
                pass
        await pipe.execute()
    except Exception:  # pragma: no cover - never break the tick on a cache hiccup
        logger.debug("mdlive_write_failed", exc_info=True)


async def _read_mdlive(token: str) -> dict[str, Any] | None:
    """Read the leader's live snapshot. Returns None when absent / non-positive
    so the caller falls back to the normal overlay path."""
    try:
        data = await cache_get(_MDLIVE_KEY.format(token=token))
    except Exception:  # pragma: no cover
        return None
    if not isinstance(data, dict):
        return None
    try:
        if float(data.get("ltp") or 0) <= 0:
            return None
    except Exception:
        return None
    return data


async def get_ltp_batch_mdlive(tokens: list[str]) -> dict[str, Decimal | None]:
    """Batch LTP read from the leader's `mdlive` snapshot — ONE Redis MGET.

    Used by the risk_enforcer in SHARDED mode (RISK_SHARDS > 1): a shard runs
    on a NON-feed-leader worker whose in-process `_state` is cold, so it can't
    use `get_ltp_instant`. The feed leader mirrors every live quote to
    `mdlive:{token}` (30 s TTL, execution-safe); this reads them back in bulk.
    Mirrors `_read_mdlive`'s guard: ltp <= 0 / missing → None (the risk loop's
    zero-LTP guard then SKIPS that position safely — never a wrong close).
    """
    out: dict[str, Decimal | None] = {t: None for t in tokens}
    if not tokens:
        return out
    try:
        from app.core.redis_client import get_redis

        raw = await get_redis().mget([_MDLIVE_KEY.format(token=t) for t in tokens])
    except Exception:  # pragma: no cover - never break the sweep on a cache hiccup
        return out
    for t, val in zip(tokens, raw):
        if not val:
            continue
        try:
            ltp = float(json.loads(val).get("ltp") or 0)
            if ltp > 0:
                out[t] = quantize_money(to_decimal(ltp))
        except Exception:
            continue
    return out


async def get_quote_batch_mdlive(tokens: list[str]) -> dict[str, dict[str, Any]]:
    """Batch full-quote read from the leader's `mdlive` snapshot — ONE Redis
    MGET. Sharded-mode counterpart of `get_quote_instant`. Returns the same
    execution-safe quote dict the feed leader wrote (ltp / bid / ask / OHLC /
    `exchange_timestamp`). Missing / non-positive-ltp tokens map to ``{}`` so
    callers (refresh_unrealized_pnl) fall back to the LTP gracefully, exactly
    like `get_quote_instant`.
    """
    out: dict[str, dict[str, Any]] = {t: {} for t in tokens}
    if not tokens:
        return out
    try:
        from app.core.redis_client import get_redis

        raw = await get_redis().mget([_MDLIVE_KEY.format(token=t) for t in tokens])
    except Exception:  # pragma: no cover
        return out
    for t, val in zip(tokens, raw):
        if not val:
            continue
        try:
            data = json.loads(val)
            if float(data.get("ltp") or 0) > 0:
                out[t] = data
        except Exception:
            continue
    return out


async def get_ltp_quote_batch_mdlive(
    tokens: list[str],
) -> tuple[dict[str, Decimal | None], dict[str, dict[str, Any]]]:
    """ONE Redis MGET → BOTH the LTP map and the full-quote map.

    The sharded risk loop needs both every tick. Fetching them via the two
    SEPARATE helpers (`get_ltp_batch_mdlive` + `get_quote_batch_mdlive`) did
    TWO MGETs over the SAME `mdlive:{token}` keys and parsed each JSON value
    TWICE every tick — on 4 shards that doubled the Redis round-trips + parse
    work and showed up as correlated `ltp_ms` spikes (1-2 s) when all shards
    hit Redis at once. This does a single MGET and one parse per value, then
    derives the LTP from the same dict. Guards are identical: ltp <= 0 /
    missing → None / {} so the risk loop's zero-LTP guard still skips safely.
    """
    ltp_out: dict[str, Decimal | None] = {t: None for t in tokens}
    quote_out: dict[str, dict[str, Any]] = {t: {} for t in tokens}
    if not tokens:
        return ltp_out, quote_out
    try:
        from app.core.redis_client import get_redis

        raw = await get_redis().mget([_MDLIVE_KEY.format(token=t) for t in tokens])
    except Exception:  # pragma: no cover - never break the sweep on a cache hiccup
        return ltp_out, quote_out
    for t, val in zip(tokens, raw):
        if not val:
            continue
        try:
            data = json.loads(val)
            ltp = float(data.get("ltp") or 0)
            if ltp > 0:
                quote_out[t] = data
                ltp_out[t] = quantize_money(to_decimal(ltp))
        except Exception:
            continue
    return ltp_out, quote_out


async def _sym_map_for(tokens: list[int]) -> dict[int, dict[str, str]]:
    """Resolve {token: {symbol, exchange}} for a cross-worker subscribe.

    A non-leader worker can only put TOKENS on the `feed:subscribe` channel, so
    the leader used to re-subscribe them with no symbol at all — and
    `subscribe_tokens_on_demand` then stores `symbol = str(token)` and
    `exchange = "NSE"`. Production carried 1,237 such rows out of 1,500, every
    MCX contract among them labelled NSE. Three things break on that:

      * the dual-account router reads `exchange` — MCX tokens marked NSE never
        move to account B, so the second socket buys nothing
      * a token with no symbol never gets re-asserted into FULL mode, so no
        OHLC arrives and the day high/low the order gates read stays 0
      * the admin panel shows a wall of bare numbers

    The catalog already knows all of this, so look it up here — one indexed
    query for the whole batch, on a path that runs a few times a minute.
    Anything not found is simply omitted: the old behaviour for that token.
    """
    if not tokens:
        return {}
    out: dict[int, dict[str, str]] = {}
    try:
        from app.models.instrument import Instrument

        rows = await Instrument.find(
            {"token": {"$in": [str(t) for t in tokens]}}
        ).to_list()
        for r in rows:
            sym = getattr(r, "symbol", None)
            if not sym:
                continue
            ex = getattr(r, "exchange", None)
            out[int(r.token)] = {
                "symbol": sym,
                "exchange": (ex.value if hasattr(ex, "value") else str(ex or "NSE")),
            }
    except Exception:  # noqa: BLE001 — a lookup miss must never block a subscribe
        logger.debug("feed_forward_sym_map_failed", exc_info=True)
    return out


async def _forward_feed_subscription(tokens: list[str]) -> None:
    """Leader-side: subscribe cross-worker-requested tokens on the real feeds.
    Numeric tokens → Zerodha ticker; symbol-style tokens → Infoway. Adds them
    to `_subscribed` so the tick_loop mirrors them into `mdlive` + pub/sub."""
    if not tokens:
        return
    _subscribed.update(tokens)
    infoway_codes = [t for t in tokens if t and not str(t).lstrip("-").isdigit()]
    numeric: list[int] = []
    for t in tokens:
        try:
            numeric.append(int(t))
        except (TypeError, ValueError):
            pass
    if infoway_codes:
        try:
            from app.services.infoway_service import infoway

            await infoway.subscribe(infoway_codes)
        except Exception:  # pragma: no cover
            logger.debug("feed_forward_infoway_failed", exc_info=True)
    if numeric:
        try:
            from app.services.zerodha_service import zerodha

            await zerodha.subscribe_tokens_on_demand(numeric, await _sym_map_for(numeric))
        except Exception:  # pragma: no cover
            logger.debug("feed_forward_zerodha_failed", exc_info=True)


async def feed_subscribe_listener() -> None:
    """LEADER-ONLY loop: consume cross-worker `feed:subscribe` requests and
    forward them to the upstream feeds. Started under the feed leader-gate in
    main.py (same gate as the feed + tick_loop, so it co-locates with them).
    Reconnects on a dropped Redis connection; exits cleanly on cancel."""
    from app.core.redis_client import pubsub

    backoff = 1.0
    ps: Any = None
    try:
        while True:
            try:
                if ps is None:
                    ps = pubsub()
                    await ps.subscribe(FEED_SUBSCRIBE_CHANNEL)
                    logger.info("feed_subscribe_listener_started")
                async for msg in ps.listen():
                    if msg.get("type") != "message":
                        continue
                    raw = msg.get("data")
                    if isinstance(raw, bytes):
                        raw = raw.decode("utf-8", "ignore")
                    if not raw:
                        continue
                    try:
                        data = json.loads(raw)
                    except Exception:
                        continue
                    toks = [str(t) for t in (data.get("tokens") or []) if t]
                    if toks:
                        await _forward_feed_subscription(toks)
                backoff = 1.0
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.warning("feed_subscribe_listener_error", exc_info=True)
                if ps is not None:
                    try:
                        await ps.close()
                    except Exception:
                        pass
                    ps = None
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30.0)
    finally:
        if ps is not None:
            try:
                await ps.unsubscribe(FEED_SUBSCRIBE_CHANNEL)
                await ps.close()
            except Exception:
                pass


async def get_quote(token: str) -> dict[str, Any]:
    now_ms = int(_t.time() * 1000)
    cached = _quote_cache.get(token)
    if cached and (now_ms - cached[0]) < _QUOTE_CACHE_TTL_MS:
        return cached[1]
    # Cold-path (non-leader) short-circuit: when THIS worker has no live
    # in-process price for the token, serve the leader's `mdlive` snapshot
    # BEFORE `_overlay_all` (which would otherwise issue a ~2 s Kite REST on
    # every cold quote). On a warm worker (leader / single-process) `_state`
    # always carries the price, so this branch never runs and the original
    # path below is taken unchanged.
    st = _state.get(str(token))
    st_cold = True
    if st:
        try:
            st_cold = float(st.get("ltp") or 0) <= 0
        except Exception:
            st_cold = True
    if st_cold:
        live = await _read_mdlive(token)
        if live is not None:
            out = _mark_freshness(dict(live))
            out["ts"] = now_ms
            _quote_cache[token] = (now_ms, out)
            return out
    q = await _ensure_quote(token)
    out = await _overlay_all(token, q, allow_rest=False)
    await _persist_last_quote(token, out)
    out = _mark_freshness(await _attach_last_quote(token, out))
    _quote_cache[token] = (now_ms, out)
    return out


async def get_ltp(token: str) -> Decimal:
    q = await get_quote(token)
    return quantize_money(to_decimal(q["ltp"]))


#: Tokens whose segment the super-admin has closed right now. Rebuilt by
#: `tick_loop` every pass. A frozen token must keep serving its HELD price —
#: the websocket keeps streaming crypto/forex through a closure.
_frozen_tokens: set[str] = set()


def get_ltp_live(token: str) -> Decimal | None:
    """The freshest LTP available, with zero network calls.

    `_state` is only as new as the last `tick_loop` pass (1 s). The raw
    websocket tick cache is written on EVERY tick, so anything that must react
    at feed speed — a parked LIMIT / SL-M waiting on its trigger — reads that
    first and falls back to `_state`.

    Not for display: the chart publishes off `tick_loop`, so a price read here
    can lead what is on screen by up to a second. That is the point.
    """
    tok = str(token)
    if tok not in _frozen_tokens:
        try:
            from app.services.zerodha_service import zerodha as _zs

            live = _zs.ticks_by_token.get(int(tok))
            if live:
                v = to_decimal(live.get("ltp") or 0)
                if v > 0:
                    return v
        except Exception:  # noqa: BLE001 — no WS on this worker / bad token
            pass
    return get_ltp_instant(tok)


def get_ltp_instant(token: str) -> Decimal | None:
    """Read LTP from the in-memory WS state with ZERO network calls.

    Used by the risk enforcer's per-tick LTP batch so that the 700 ms
    ``_quote_cache`` expiry no longer triggers concurrent Zerodha REST
    calls every 3rd tick (which caused 125-460 ms ltp_ms spikes).

    Returns ``None`` when the token has no WS price yet — the risk
    enforcer's existing zero-LTP guard skips those positions safely.
    """
    q = _state.get(str(token))
    if q:
        try:
            v = to_decimal(q.get("ltp") or 0)
            if v > 0:
                return v
        except Exception:
            pass
    # _state-miss fallback → raw Zerodha WS tick cache. `_state` is only
    # seeded for tokens someone called get_quote() on (watchlist / order
    # panel / positions view). An open-position token nobody is actively
    # viewing never enters `_state`, so the risk enforcer got None and
    # SKIPPED its SL/TP/stop-out EVERY tick (raw_ltp=null in
    # risk_ltp_fetch_failed — observed for dozens of FUT/CE/equity legs,
    # 2026-06-24). The tick handler keeps `ticks_by_token` fresh for every
    # subscribed token on the feed-leader worker, where the enforcer
    # co-locates (see main.py), so this restores a live price with zero
    # network. Empty on a cold/non-leader worker → None (no worse than before).
    try:
        from app.services.zerodha_service import zerodha as _zs
        live = _zs.ticks_by_token.get(int(token))
        if live:
            v = to_decimal(live.get("ltp") or 0)
            return v if v > 0 else None
    except Exception:
        pass
    return None


def get_quote_instant(token: str) -> dict[str, Any]:
    """Return a shallow copy of the in-memory WS state for *token*.

    Used by the risk enforcer to pass a pre-fetched quote dict directly to
    ``refresh_unrealized_pnl``, bypassing ``get_quote`` / ``_overlay_all`` /
    ``_quote_cache`` entirely. This eliminates the REST fallback that caused
    sweep_ms to cascade when the 700 ms _quote_cache TTL expired mid-sweep
    (position checked at t=0 got the cached quote; position checked at t=750 ms
    saw an expired cache and triggered a Zerodha REST, extending the sweep past
    the next TTL boundary and cascading further).

    Returns an empty dict when the token has no WS state yet — callers must
    fall back gracefully (use LTP as-is) when bid/ask are absent.
    """
    q = _state.get(str(token))
    if q:
        return dict(q)
    # Same _state-miss fallback as get_ltp_instant: read the live WS tick
    # cache so the risk enforcer's close-side (bid/ask) mark works for
    # open-position tokens that were never get_quote()'d into `_state`.
    try:
        from app.services.zerodha_service import zerodha as _zs
        live = _zs.ticks_by_token.get(int(token))
        if live:
            return dict(live)
    except Exception:
        pass
    return {}


async def get_quotes(tokens: list[str]) -> list[dict[str, Any]]:
    # Previously this looped serially — each token's `_overlay_all` blocked
    # on Zerodha + Infoway timeouts (~2 s each) BEFORE moving to the next
    # token. With 5 instruments on the OrderPanel that was a ~10 s worst-
    # case for a single batch request. asyncio.gather fans them out in
    # parallel so the total wait drops to the slowest single overlay.
    #
    # ── Read the leader's mirror first ────────────────────────────────
    # `get_quote` (singular) short-circuits on `mdlive` for exactly this
    # reason and this function never learned to. Only the LEADER worker runs
    # the feed, so on every OTHER worker `_state` is permanently cold and the
    # path below returns ltp 0 — `_attach_last_quote` then fills in the last
    # SESSION's price, which is not a live rate.
    #
    # This is what the two REST calls the terminal makes on open both go
    # through (`/marketwatch/{id}/quotes` for the favourite list, and
    # `/instruments/quotes-batch` for the panel seed). Production runs 5
    # gunicorn workers, so 4 requests in 5 were answered with no live price at
    # all and the screen had nothing to show until a websocket tick arrived —
    # the reported "rate 10-20 second baad dikhta hai".
    #
    # One MGET for the whole batch (measured: 0.2 ms for 32 tokens). Only the
    # tokens the mirror does not hold take the slow path.
    mirror = await get_quote_batch_mdlive(tokens)
    now_ms = int(_t.time() * 1000)

    async def _one(t: str) -> dict[str, Any]:
        live = mirror.get(t)
        if live:
            out = _mark_freshness(dict(live))
            out["ts"] = now_ms
            return out
        q = await _ensure_quote(t)
        out = await _overlay_all(t, q, allow_rest=False)
        await _persist_last_quote(t, out)
        return await _attach_last_quote(t, out)

    return list(await asyncio.gather(*[_one(t) for t in tokens]))


def subscribe(tokens: list[str]) -> None:
    _subscribed.update(tokens)

    # Multi-worker cross-worker propagation: when THIS worker doesn't own the
    # upstream feed (non-leader), announce the tokens on `feed:subscribe` so
    # the leader's `feed_subscribe_listener` subscribes them on the real
    # Zerodha/Infoway feeds. Gated on `not _is_feed_leader` so a single worker
    # (always its own leader) never publishes → behaviour identical to before.
    if not _is_feed_leader and tokens:
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(
                publish(FEED_SUBSCRIBE_CHANNEL, {"tokens": [str(t) for t in tokens]}),
                name="feed_subscribe_publish",
            )
        except RuntimeError:
            pass
        except Exception:  # pragma: no cover
            logger.debug("feed_subscribe_publish_failed", exc_info=True)

    # Propagate Infoway-class tokens (forex / crypto / metals / energy) to
    # the Infoway WS ON DEMAND. Without this, only the symbols listed in
    # INFOWAY_DEFAULT_* (subscribed once at startup) ever received ticks —
    # opening ANY other forex chart showed a perpetual "loading" because
    # Infoway was never told to stream that symbol, and (unlike Zerodha)
    # Infoway has no REST snapshot fallback to bridge the gap.
    #
    # Infoway instrument tokens ARE the symbol string (token == symbol, see
    # infoway_service.mirror_subscribed_to_instruments). Zerodha tokens are
    # always pure integers and are handled by the Kite on-demand path
    # elsewhere — so we forward only the non-numeric (symbol-style) tokens.
    infoway_codes = [
        t for t in tokens if t and not str(t).lstrip("-").isdigit()
    ]
    if infoway_codes:
        try:
            from app.services.infoway_service import infoway

            loop = asyncio.get_running_loop()
            loop.create_task(
                infoway.subscribe(infoway_codes),
                name="infoway_on_demand_subscribe",
            )
        except RuntimeError:
            # No running event loop (called from a sync context) — skip;
            # the WS subscribe path always runs inside the loop so this
            # only guards rare non-async callers.
            pass
        except Exception:
            logger.debug("infoway_on_demand_subscribe_failed", exc_info=True)


def unsubscribe(tokens: list[str]) -> None:
    for t in tokens:
        _subscribed.discard(t)

    # NOTE: we deliberately do NOT propagate unsubscribe to Infoway. There
    # is no cross-connection ref-count here, so if user A closes a EURUSD
    # chart while user B still has it open, unsubscribing from Infoway would
    # kill B's live ticks too. An idle Infoway subscription is cheap (one
    # extra symbol in the feed), so we leave it streaming. A periodic
    # reaper can prune genuinely-unwatched symbols later if needed.


async def ensure_open_position_subscriptions() -> dict[str, int]:
    """Guarantee every OPEN-position token is on the live feed AND in
    ``_subscribed`` — the gate ``tick_loop`` uses to mirror quotes into
    ``mdlive:{token}``.

    Why this exists: the boot/reconnect warm in ``zerodha_service`` subscribed
    held tokens on the Kite WS (so ``_state`` warms) but never added them to
    ``_subscribed``, so ``tick_loop`` skipped mirroring them into ``mdlive``.
    The sharded risk loop reads ``mdlive`` — so any held token nobody was
    independently watching (no watchlist entry / open chart) had NO live price
    and the risk enforcer silently SKIPPED SL/TP/stop-out for it every tick
    (the ``risk_ltp_fetch_failed`` flood). This reconciles BOTH registries.

    Idempotent: ``subscribe_tokens_on_demand`` skips already-subscribed Kite
    tokens and ``_subscribed`` is a set. Numeric tokens → Kite WS (warms
    ``_state``); symbol-style synthetic (Infoway forex/crypto) tokens are
    forwarded to the Infoway WS by ``subscribe`` below.
    """
    from app.models.position import Position, PositionStatus

    open_positions = await Position.find(
        Position.status == PositionStatus.OPEN
    ).to_list()

    all_tokens: list[str] = []
    numeric: list[int] = []
    sym_map: dict[int, dict[str, str]] = {}
    for p in open_positions:
        tok_raw = getattr(getattr(p, "instrument", None), "token", None)
        if tok_raw is None:
            continue
        all_tokens.append(str(tok_raw))
        try:
            tok = int(tok_raw)
        except (TypeError, ValueError):
            continue  # synthetic Infoway token — handled via subscribe() below
        ex = getattr(p.instrument, "exchange", None)
        ex_str = ex.value if hasattr(ex, "value") else str(ex or "NSE")
        numeric.append(tok)
        sym_map[tok] = {
            "symbol": getattr(p.instrument, "symbol", "") or str(tok),
            "exchange": ex_str,
        }

    if not all_tokens:
        return {"positions": 0, "kite": 0, "newly_subscribed": 0}

    # 1) Kite WS — warm `_state` for numeric tokens (no-op if already subbed).
    if numeric:
        try:
            from app.services.zerodha_service import zerodha

            await zerodha.subscribe_tokens_on_demand(numeric, sym_map)
        except Exception:  # noqa: BLE001
            logger.exception("ensure_open_position_kite_subscribe_failed")

    # 2) `_subscribed` set — so `tick_loop` mirrors them into `mdlive`. Also
    #    forwards synthetic (Infoway) tokens to the Infoway WS on demand.
    before = len(_subscribed)
    subscribe(all_tokens)
    added = len(_subscribed) - before

    logger.info(
        "open_position_subscriptions_reconciled",
        extra={
            "positions": len(open_positions),
            "kite_tokens": len(numeric),
            "newly_added_to_subscribed": added,
            "total_subscribed": len(_subscribed),
        },
    )
    return {
        "positions": len(open_positions),
        "kite": len(numeric),
        "newly_subscribed": added,
    }


async def open_position_subscription_loop(interval_sec: float = 120.0) -> None:
    """Leader-only: periodically reconcile OPEN-position subscriptions so a
    held token can never silently fall off the live feed mid-session — which
    would make the risk enforcer skip its SL/TP/stop-out. A 2-min cadence
    self-heals within a couple of risk ticks; the call is cheap + idempotent.
    First pass runs immediately on start."""
    import asyncio as _asyncio

    logger.info("open_position_subscription_loop_started interval_sec=%s", interval_sec)
    while True:
        try:
            await ensure_open_position_subscriptions()
        except Exception:  # noqa: BLE001
            logger.exception("open_position_subscription_loop_iter_failed")
        await _asyncio.sleep(interval_sec)


# ── Background tick loop ────────────────────────────────────────────
def _feed_tokens() -> set[str]:
    """Every token the upstream feeds are actually streaming right now.

    `_state` is demand-driven - an entry appears only when somebody ASKS for
    that token (`_ensure_quote`) - and so is `_subscribed`, which fills from
    browser websocket subscribes. The tick loop mirrored the intersection of
    the two, so `mdlive` only ever held what a browser happened to have open
    at that second: 14 of 372 measured mid-session.

    That is the whole flicker. Opening an F&O contract fires the REST quote
    BEFORE the websocket subscribe has landed, so the mirror has nothing, a
    cold worker falls through to `mdlast`, and the screen shows the PREVIOUS
    DAY'S CLOSE until the first tick corrects it. Large caps and index futures
    hid it because somebody else always had them open already.

    The feed is subscribed to the whole fixed list regardless, so the prices
    are sitting right there in the ticker caches. This is what makes the mirror
    cover them.
    """
    out: set[str] = set()
    try:
        from app.services.zerodha_service import zerodha

        out.update(str(t) for t in zerodha.ticks_by_token)
    except Exception:  # noqa: BLE001 - a cold ticker just contributes nothing
        pass
    try:
        from app.services.infoway_service import infoway

        out.update(str(t) for t in (infoway.ticks or {}))
    except Exception:  # noqa: BLE001
        pass
    return out


async def tick_loop(interval_sec: float = 1.0) -> None:
    """Fan out subscribed instrument ticks to Redis pub/sub.

    No price generation here — the loop only mirrors whatever the real
    overlays (Zerodha WS / Infoway WS / Kite REST snapshot) have already
    written into `_state`. Tokens with LTP = 0 are skipped so we don't
    spam consumers with zero-priced ticks for instruments that have no
    real feed yet.
    """
    global _running
    if _running:
        return
    _running = True
    logger.info("market_tick_loop_started")
    await _warm_token_symbol_cache()
    try:
        import time

        while _running:
            try:
                now_ms = int(time.time() * 1000)
                # Collect subscribed (token, base) pairs first so we can
                # fan the overlays out in parallel. The old code awaited
                # `_overlay_all` per-token in a serial for-loop — with
                # N subscribed instruments each taking the worst-case
                # Zerodha REST overlay (~200-2000 ms), one iteration
                # could stretch into multiple seconds and starve the
                # 250 ms tick-loop cadence.
                # Everything the feed carries, plus anything a browser asked
                # for. `_ensure_quote` creates the `_state` row so a token the
                # ticker is streaming but nobody has opened yet still gets
                # overlaid and mirrored - which is the point: a cold worker has
                # to be able to answer for ANY instrument on the fixed list the
                # moment it is opened, not a second later.
                for _tok in _feed_tokens():
                    await _ensure_quote(_tok)
                pending = list(_state.items())
                if pending:
                    results = await asyncio.gather(
                        *(_overlay_all(token, base) for token, base in pending),
                        return_exceptions=True,
                    )
                    # Multi-worker: mirror each live quote to Redis so the
                    # non-leader workers (cold `_state`) can serve quotes +
                    # fills from `mdlive:{token}` without running their own feed.
                    mdlive_items: list[tuple[str, dict[str, Any]]] = []
                    # SA market-control freeze: segments the admin has closed right
                    # now (crypto/forex would otherwise keep ticking 24×7).
                    from app.services import market_control_service as _mcs

                    try:
                        _closed_segs = await _mcs.closed_segments()
                    except Exception:
                        _closed_segs = set()
                    _frozen_now: set[str] = set()
                    for (token, base), overlaid in zip(pending, results):
                        # FREEZE FIRST: if the SA has closed this token's segment
                        # via market control, hold the LAST value EVERYWHERE — skip
                        # the _state refresh, the mdlive mirror AND the WS tick — so
                        # the list, order panel AND floating PnL all stop moving
                        # (crypto/forex stream 24×7, so they'd otherwise keep
                        # ticking with trading closed). Frozen until it reopens.
                        if _closed_segs:
                            _seg = await _mc_seg_for_token(token)
                            if _seg and _seg in _closed_segs:
                                _frozen_now.add(token)
                                # Frozen: keep the LAST value alive in mdlive so
                                # get_ltp / floating PnL / Avl margin HOLD at the
                                # frozen price (they'd otherwise drop to 0 once the
                                # mdlive TTL lapses). Do NOT publish a WS tick and
                                # do NOT refresh _state — the display stays static.
                                _last = _state.get(token) or base
                                if _last and float(_last.get("ltp") or 0) > 0:
                                    _held = dict(_last)
                                    _held["ts"] = now_ms
                                    mdlive_items.append((token, _held))
                                continue
                        if isinstance(overlaid, Exception):
                            q = base
                        else:
                            q = overlaid
                            _state[token] = q
                        q["ts"] = now_ms
                        # Skip tokens that still have no real feed — don't
                        # broadcast zero-priced ticks.
                        if float(q.get("ltp") or 0) <= 0:
                            continue
                        _mark_freshness(q)
                        # A price from a PREVIOUS session must not be mirrored
                        # — the key is rewritten every second, so its TTL never
                        # lapses and a dead contract would look live for ever.
                        # An illiquid one that simply has not printed for a
                        # while IS mirrored: the leader serves its held price
                        # either way, and the workers have to agree.
                        if not _mirrorable(q):
                            continue
                        mdlive_items.append((token, q))
                        # The MIRROR covers the whole feed; the pub/sub fanout
                        # still only carries what a browser is watching, so
                        # widening the mirror costs no extra websocket traffic.
                        if token not in _subscribed:
                            continue
                        await publish(
                            f"market:tick:{token}",
                            {
                                "token": token,
                                "ltp": q["ltp"],
                                "change": q["change"],
                                "change_pct": q["change_pct"],
                                "volume": q["volume"],
                                "bid": q["bid"],
                                "ask": q["ask"],
                                "ts": q["ts"],
                                # The session range travels with the tick.
                                # Without these the stream carried only the
                                # price, so a screen's high/low was whatever
                                # the one-off REST seed said when the page
                                # loaded and never moved again - the range
                                # went stale within minutes of opening, and on
                                # a cold worker the seed itself had been the
                                # PREVIOUS day's range.
                                "high": q.get("high"),
                                "low": q.get("low"),
                                "open": q.get("open"),
                                "prev_close": q.get("prev_close"),
                                # Age of the EXCHANGE stamp, so every consumer
                                # can tell a live price from a held one.
                                "age_sec": q.get("age_sec"),
                                "stale": q.get("stale"),
                            },
                        )
                    await _write_mdlive_batch(mdlive_items)
                    # Fold the SAME leader-only live quotes into per-minute
                    # bid/ask high-low buckets for the admin "Rate History"
                    # view. Pure in-memory and synchronous, so it cannot slow
                    # the tick; the leader-gated flush loop persists completed
                    # minutes. Best-effort — a bad tick must never break fanout.
                    try:
                        from app.services import tick_aggregator

                        tick_aggregator.record(mdlive_items, now_ms)
                    except Exception:  # pragma: no cover
                        logger.warning("tick_aggregator_record_failed", exc_info=True)
                    # Same quotes, buffered for the two-day tick store. A list
                    # append and nothing more — the write happens in its own
                    # loop so the tick never waits on Mongo.
                    try:
                        from app.services import tick_store

                        tick_store.record(mdlive_items, now_ms)
                    except Exception:  # pragma: no cover
                        logger.warning("tick_store_record_failed", exc_info=True)
                    # Publish the freeze to `get_ltp_live` in one assignment —
                    # a reader never sees a half-built set.
                    global _frozen_tokens
                    _frozen_tokens = _frozen_now
                await asyncio.sleep(interval_sec)
            except Exception as e:  # pragma: no cover
                logger.exception("market_tick_loop_iter_failed", extra={"error": str(e)})
                await asyncio.sleep(2.0)
    finally:
        _running = False
        logger.info("market_tick_loop_stopped")


def stop_tick_loop() -> None:
    global _running
    _running = False
