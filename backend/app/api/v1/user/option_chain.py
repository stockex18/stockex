"""Option chain endpoint — given an underlying (token OR symbol), return the
strikes × expiries grid with live LTPs.

Uses Zerodha's in-memory instrument cache for instant lookups — no MongoDB
round-trips for option data. Prices come from live KiteTicker ticks first,
falling back to a single batch REST /quote call.

Performance: the picker re-fetches every 2 s. Without caching, each call
would (a) re-scan the 50k-row NFO CSV, (b) issue a Kite REST /quote on
100+ keys, and (c) on-demand-subscribe every visible leg — easily 5-15 s
of work per request and a hard freeze when Kite is slow. Two layers of
cache below keep the hot path ≪ 100 ms:

    _CHAIN_CACHE     : full response, keyed by (und, expiry), TTL 2.5 s.
                       Sized for the picker's 2 s polling cadence so back-
                       to-back requests usually hit the cache.
    _CATALOG_FILTER  : the (filtered options + expiries) tuple from
                       get_option_chain_fast, keyed by underlying, TTL
                       300 s. The CSV catalog itself doesn't change
                       intraday so this is safe.
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import date, datetime
from typing import Any

from fastapi import APIRouter, Query

from app.core.dependencies import CurrentUser
from app.models.platform_setting import PlatformSetting
from app.schemas.common import APIResponse

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/option-chain", tags=["user-option-chain"])


# Fallback defaults if settings are missing (first-run before seed).
_DEFAULT_UNDERLYINGS = [
    {"label": "Nifty", "symbol": "NIFTY", "color": "emerald"},
    {"label": "BankNifty", "symbol": "BANKNIFTY", "color": "violet"},
    {"label": "Sensex", "symbol": "SENSEX", "color": "rose"},
]
_DEFAULT_STRIKES_AROUND_ATM = 15
_DEFAULT_MAX_EXPIRIES = 6

# Hard cap on the Kite REST batch quote — prevents a slow / hung Kite call
# from blocking the picker. On timeout we serve whatever live ticks are
# already in the in-memory map and the frontend's next 2 s poll picks up
# the rest.
_KITE_BATCH_QUOTE_TIMEOUT_SEC = 3.0

# Settings cache (60s)
_settings_cache: dict[str, tuple[Any, float]] = {}
_SETTINGS_TTL = 60.0

# Full-response cache (2.5s) — sized just above the picker's 2s polling
# cadence so each request lands a hit on the next poll.
_CHAIN_CACHE: dict[str, tuple[dict[str, Any], float]] = {}
_CHAIN_TTL = 1.0

# Catalog filter cache (5 min) — the heavy 50k-row scan. CSV doesn't change
# intraday so this can sit much longer than the price cache.
_CATALOG_FILTER: dict[str, tuple[tuple[list[dict[str, Any]], list[date]], float]] = {}
_CATALOG_TTL = 300.0


async def _read_setting(key: str, default: Any) -> Any:
    cached = _settings_cache.get(key)
    now = time.time()
    if cached and (now - cached[1]) < _SETTINGS_TTL:
        return cached[0]
    s = await PlatformSetting.find_one(PlatformSetting.setting_key == key)
    val = s.setting_value if s is not None else default
    _settings_cache[key] = (val, now)
    return val


def _exchange_bucket(exchange: str | None) -> str:
    """Map an instrument exchange onto the NSE / BSE / MCX fallback bucket."""
    ex = (exchange or "").upper()
    if ex in ("NSE", "NFO"):
        return "NSE"
    if ex in ("BSE", "BFO"):
        return "BSE"
    if ex == "MCX":
        return "MCX"
    return ""


# Super-admin can size "strikes around ATM" per option segment (index / stock /
# MCX / crypto). Stored as a JSON map; each entry falls back to the global scalar
# `option_chain.strikes_around_atm` when unset.
_STRIKES_BY_SEGMENT_KEY = "option_chain.strikes_around_atm_by_segment"
STRIKES_SEGMENTS = ["NSE_IDX_OPT", "NSE_STK_OPT", "MCX_OPT", "CRYPTO_OPT"]


def _strikes_seg_key(exchange: str | None, underlying: str | None) -> str:
    """Classify an option chain into one of the 4 independently-sizable segments
    (index option / stock option / MCX option). Crypto is passed explicitly."""
    from app.services.netting_service import _INDEX_UNDERLYING_PREFIXES

    ex = (exchange or "").upper()
    if ex == "MCX":
        return "MCX_OPT"
    su = (underlying or "").upper()
    if su.startswith(tuple(_INDEX_UNDERLYING_PREFIXES)):
        return "NSE_IDX_OPT"
    return "NSE_STK_OPT"


async def _strikes_around_atm_for(seg_key: str) -> int:
    """Per-segment 'strikes around ATM' set by the super-admin, falling back to
    the global scalar when the segment isn't configured."""
    try:
        scalar = int(await _read_setting("option_chain.strikes_around_atm", _DEFAULT_STRIKES_AROUND_ATM) or _DEFAULT_STRIKES_AROUND_ATM)
    except (TypeError, ValueError):
        scalar = _DEFAULT_STRIKES_AROUND_ATM
    by_seg = await _read_setting(_STRIKES_BY_SEGMENT_KEY, {})
    if isinstance(by_seg, dict) and seg_key in by_seg:
        try:
            v = int(by_seg.get(seg_key))
            if v > 0:
                return v
        except (TypeError, ValueError):
            pass
    return scalar


async def _crypto_ladder(root: str, expiry) -> tuple[list[float], float | None]:
    """(strike ladder, spot) for a crypto option expiry, from the Mongo mirror.

    Crypto options come from Binance (`binance_options_service`), never from the
    Zerodha CSV, so the catalog path finds nothing for them. Returns an empty
    ladder for a non-crypto root, which leaves the caller failing open.
    """
    if _crypto_option_root(root) is None:
        return ([], None)
    from app.models._base import SegmentType
    from app.models.instrument import Instrument

    try:
        rows = await Instrument.find(
            Instrument.segment == SegmentType.CRYPTO_OPTION_BUY.value,
            Instrument.is_active == True,  # noqa: E712
        ).to_list()
    except Exception:  # noqa: BLE001
        return ([], None)

    prefix = f"{root.upper()}-"
    strikes: set[float] = set()
    for r in rows:
        if not (r.symbol or "").upper().startswith(prefix) or r.strike is None:
            continue
        exp = r.expiry.date() if hasattr(r.expiry, "date") else r.expiry
        if exp != expiry:
            continue
        try:
            strikes.add(float(str(r.strike)))
        except (TypeError, ValueError):
            continue

    spot: float | None = None
    try:
        from app.services.binance_options_service import _spot_for

        spot = float(_spot_for(root.upper())) or None
    except Exception:  # noqa: BLE001
        spot = None
    return (sorted(strikes), spot)


async def allowed_strike_set(
    root: str, expiry, exchange: str
) -> tuple[set[float] | None, int]:
    """The strikes inside ATM ± N for one (underlying, expiry) ladder.

    Returns ``(allowed, window)``. ``allowed is None`` means "no opinion" —
    every caller must then let the strike through. That happens when the
    window is off (0), the catalog is cold, the ladder already fits inside
    the window, or the underlying spot is unavailable. Failing OPEN matters:
    a feed hiccup must never blank out an instrument list or block an order.

    Single source of truth for "is this strike tradeable", shared by the
    order validator's `STRIKE_OUT_OF_RANGE` gate and `/instruments/search`,
    so a strike can never be listed in search yet rejected on order — or
    vice versa. Distance is counted in LADDER POSITIONS, never price steps:
    NIFTY is 50-wide near ATM and 100-wide in the wings, so any fixed step
    size mis-measures one end or the other.
    """
    if not root or expiry is None:
        return (None, 0)
    window = int(await _strikes_around_atm_for(_strikes_seg_key(exchange, root)))
    if window <= 0:
        return (None, 0)

    options, _ = await _cached_catalog(root)
    strikes = sorted(
        {
            float(o["strike"])
            for o in options
            if o.get("strike") is not None and o.get("_expiry_date") == expiry
        }
    )
    spot: float | None = None
    if not strikes:
        # Crypto options never appear in the Zerodha catalog — they are mirrored
        # from Binance into Mongo — so fall back to the Instrument rows and to
        # the crypto spot. Without this the CRYPTO OPT browse chip stayed
        # unfiltered no matter what CRYPTO_OPT was set to.
        strikes, spot = await _crypto_ladder(root, expiry)

    if len(strikes) <= 2 * window + 1:
        return (None, window)  # whole ladder fits — nothing is ever outside

    if spot is None:
        spot = await _underlying_spot(root)
    if not spot or spot <= 0:
        return (None, window)

    atm_idx = min(range(len(strikes)), key=lambda i: abs(strikes[i] - spot))
    lo = max(0, atm_idx - window)
    hi = min(len(strikes), atm_idx + window + 1)
    return (set(strikes[lo:hi]), window)


async def _underlying_spot(und_key: str) -> float | None:
    """The REAL underlying spot (NIFTY / BANKNIFTY / stock …) from the live feed,
    in-memory + non-blocking. Used to CENTER the option-chain window on the true
    ATM. Without it the window fell back to put-call parity on the option legs —
    which needs both-side LTPs and, worse, could STICK at a wrong strike: the
    window is trimmed first, only those strikes get subscribed, so parity can
    never see a true ATM that sits outside the (wrong) window. Anchoring on the
    real spot fixes the 'strikes on one side of ATM missing' bug. None → callers
    fall back to the old parity/median guess."""
    try:
        import asyncio as _aio

        from app.services.zerodha_service import zerodha as _z

        inst = await _aio.wait_for(_z.find_instrument_by_symbol(und_key), timeout=1.0)
        tok = (inst or {}).get("token") or (inst or {}).get("instrument_token")
        if tok:
            px = await _price_for_token(tok)
            if px:
                return px
        # MCX commodities (CRUDEOIL, GOLD, SILVER…) have NO spot instrument on
        # Kite — `find_instrument_by_symbol("CRUDEOIL")` returns nothing, so this
        # used to give up and every ATM calculation for MCX silently fell back to
        # a median guess (and the strike-window gates fell open entirely). The
        # front-month FUTURE is the reference price for those, so try it.
        fut_tok = await _nearest_future_token(und_key)
        if fut_tok:
            return await _price_for_token(fut_tok)
    except Exception:
        return None
    return None


async def _price_for_token(tok) -> float | None:
    """Last price for a Kite token: in-process tick → feed-leader cache → Redis.

    The Redis `mdlast` step is load-bearing on a multi-worker deploy: the first
    two are only warm on the feed leader, so 3 of 4 workers would otherwise see
    nothing and centre the chain on a guess.
    """
    from app.core.redis_client import cache_get
    from app.services import market_data_service
    from app.services.zerodha_service import zerodha as _z

    try:
        live = _z.ticks_by_token.get(int(tok))
        if live and float(live.get("ltp") or 0) > 0:
            return float(live["ltp"])
    except (TypeError, ValueError):
        pass
    v = market_data_service.get_ltp_instant(str(tok))
    if v and float(v) > 0:
        return float(v)
    md_row = await cache_get(f"mdlast:{tok}")
    if isinstance(md_row, dict):
        mv = float(md_row.get("ltp") or 0)
        if mv > 0:
            return mv
    return None


_FUT_TOKEN_CACHE: dict[str, tuple[int | None, float]] = {}
_FUT_TOKEN_TTL = 300.0


async def _nearest_future_token(root: str) -> int | None:
    """Kite token of the nearest unexpired FUTURES contract for an underlying.

    The price reference for anything with no spot listing — MCX commodities
    above all. Cached for 5 min because it scans the exchange catalog.
    """
    key = (root or "").strip().upper()
    if not key:
        return None
    now = time.time()
    hit = _FUT_TOKEN_CACHE.get(key)
    if hit and (now - hit[1]) < _FUT_TOKEN_TTL:
        return hit[0]

    from app.services.zerodha_service import zerodha as _z

    today = date.today()
    best: tuple[date, int] | None = None
    for ex in ("MCX", "NFO", "BFO"):
        try:
            catalog = await _z.fetch_instruments(ex)
        except Exception:  # noqa: BLE001
            continue
        for row in catalog:
            if (row.get("instrumentType") or "").upper() != "FUT":
                continue
            if (row.get("name") or "").upper().replace(" ", "") != key:
                continue
            raw = row.get("expiry")
            if not raw:
                continue
            try:
                exp = datetime.fromisoformat(str(raw).replace("Z", "+00:00")).date()
                tok = int(row.get("token") or row.get("instrument_token") or 0)
            except (TypeError, ValueError):
                continue
            if exp < today or not tok:
                continue
            if best is None or exp < best[0]:
                best = (exp, tok)
        if best is not None:
            break  # nearest listing exchange wins; don't scan the rest

    result = best[1] if best else None
    _FUT_TOKEN_CACHE[key] = (result, now)
    return result


def _effective_max_expiries(resolved: dict[str, Any], underlying: str | None, exchange: str | None) -> int:
    """Effective expiry cap for ONE instrument:
        1) the underlying's per-script "Show expiry month" (if set),
        2) else the per-exchange fallback (NSE / BSE / MCX),
        3) else the legacy single fallback,
        4) else 6.
    """
    und = (underlying or "").strip().upper()
    for u in (resolved.get("underlyings") or []):
        if isinstance(u, dict) and str(u.get("symbol") or "").strip().upper() == und:
            mx = u.get("max_expiries")
            if mx not in (None, "", 0):
                try:
                    return max(1, int(mx))
                except (TypeError, ValueError):
                    pass
            break
    bucket = _exchange_bucket(exchange)
    by_ex = resolved.get("max_expiries_by_exchange") or {}
    if bucket and by_ex.get(bucket) not in (None, "", 0):
        try:
            return max(1, int(by_ex[bucket]))
        except (TypeError, ValueError):
            pass
    return max(1, int(resolved.get("max_expiries") or 6))


def _limit_to_expiry_months(expiries: list, months: int) -> list:
    """Keep every expiry that falls inside the nearest `months` expiry MONTHS.

    The setting is called "Show expiry month" and the admin sets it expecting
    months — 1 means "this month's expiries". It used to be applied as a count
    of expiry DATES, which is the same thing only for monthly contracts. NIFTY
    expires weekly, so an admin asking for 1 month of NIFTY got a single
    Tuesday instead of the four in September.

    Counts distinct months that actually have contracts rather than doing
    calendar arithmetic from today, so late in a month - when nothing is left
    to expire - "1 month" means the next month that has expiries instead of an
    empty list.

    `expiries` must be sorted ascending; entries may be `date` objects or
    "YYYY-MM-DD" strings (both stringify to a sortable YYYY-MM prefix).
    """
    n = max(1, int(months or 1))
    seen: list[str] = []
    for e in expiries:
        m = str(e)[:7]
        if m not in seen:
            seen.append(m)
        if len(seen) > n:
            break
    allowed = set(seen[:n])
    return [e for e in expiries if str(e)[:7] in allowed]


async def _resolve_expiry_settings_for_user(
    user_id: Any,
) -> dict[str, Any]:
    """USER → BROKER → ADMIN → GLOBAL, field-by-field, for `underlyings`,
    `max_expiries` (legacy single fallback) and `max_expiries_by_exchange`
    (per NSE / BSE / MCX). A None field on an override row inherits from the
    parent tier. Falls back to the global PlatformSetting + seed defaults.
    """
    from beanie import PydanticObjectId
    from app.models.expiry_override import ExpiryOverride, ExpiryOverrideActor
    from app.models.user import User as _User

    cache_key = f"_resolved:{user_id or 'global'}"
    cached = _settings_cache.get(cache_key)
    now = time.time()
    if cached and (now - cached[1]) < _SETTINGS_TTL:
        return cached[0]

    underlyings: list[dict[str, Any]] | None = None
    fallback: int | None = None
    by_exchange: dict[str, Any] | None = None
    # Super-admin pool = a user with NO assigned admin (assigned_admin_id null;
    # see admin/users.py create-user: "SUPER_ADMIN → platform pool"). The
    # GLOBAL PlatformSetting holds THIS pool's expiry config. Admin-pool users
    # (and anyone under a broker, whose assigned_admin_id is the parent admin)
    # must NOT inherit it — a super-admin expiry change must never touch an
    # admin's users — so they fall to the hard seed default unless their own
    # user / broker / admin tier set an expiry override.
    is_super_pool = True

    def _absorb_und(ov) -> None:
        nonlocal underlyings
        if ov is not None and underlyings is None and ov.underlyings is not None:
            underlyings = ov.underlyings

    def _absorb_exp(ov) -> None:
        nonlocal fallback, by_exchange
        if ov is None:
            return
        if fallback is None and ov.max_expiries_fallback is not None:
            fallback = ov.max_expiries_fallback
        if by_exchange is None and getattr(ov, "max_expiries_by_exchange", None):
            by_exchange = ov.max_expiries_by_exchange

    def _absorb(ov) -> None:
        _absorb_und(ov)
        _absorb_exp(ov)

    def _done() -> bool:
        return underlyings is not None and fallback is not None and by_exchange is not None

    if user_id is not None:
        try:
            uid = PydanticObjectId(str(user_id))
        except Exception:
            uid = None
        if uid is not None:
            _absorb(await ExpiryOverride.find_one(
                ExpiryOverride.actor_kind == ExpiryOverrideActor.USER,
                ExpiryOverride.actor_id == uid,
            ))
            # Always load the user — assigned_admin_id decides super-pool vs
            # admin-pool, which gates GLOBAL inheritance for the expiry fields.
            user_doc = await _User.get(uid)
            if user_doc is not None:
                # Closest broker first (sub-broker shadows top broker).
                for bid in reversed(list(getattr(user_doc, "broker_ancestry", None) or [])):
                    if _done():
                        break
                    _absorb(await ExpiryOverride.find_one(
                        ExpiryOverride.actor_kind == ExpiryOverrideActor.BROKER,
                        ExpiryOverride.actor_id == bid,
                    ))
                aid = getattr(user_doc, "assigned_admin_id", None)
                if aid is not None:
                    is_super_pool = False
                    _absorb(await ExpiryOverride.find_one(
                        ExpiryOverride.actor_kind == ExpiryOverrideActor.ADMIN,
                        ExpiryOverride.actor_id == aid,
                    ))

    # Stock LIST (symbols / labels / colours): platform-wide — always falls to
    # GLOBAL when no override set it. For admin-pool users we keep the list but
    # STRIP the super-admin's per-script "Show expiry month", so an expiry
    # choice made at GLOBAL can't leak into an admin's users via the array.
    if underlyings is None:
        underlyings = await _read_setting("option_chain.underlyings", _DEFAULT_UNDERLYINGS) or []
        if not is_super_pool and isinstance(underlyings, list):
            underlyings = [
                {**u, "max_expiries": None}
                for u in underlyings
                if isinstance(u, dict)
            ]

    # Expiry fallbacks: GLOBAL is the SUPER-ADMIN POOL's config. Only super-
    # admin-pool users inherit it; admin-pool users that reached here without
    # their own expiry override use the hard seed default (never GLOBAL).
    if fallback is None:
        if is_super_pool:
            fallback = int(await _read_setting("option_chain.max_expiries", _DEFAULT_MAX_EXPIRIES))
        else:
            fallback = _DEFAULT_MAX_EXPIRIES
    if by_exchange is None:
        if is_super_pool:
            by_exchange = await _read_setting("option_chain.max_expiries_by_exchange", {}) or {}
        else:
            by_exchange = {}

    out = {
        "underlyings": underlyings if isinstance(underlyings, list) else [],
        "max_expiries": max(1, int(fallback)),
        "max_expiries_by_exchange": by_exchange if isinstance(by_exchange, dict) else {},
    }
    _settings_cache[cache_key] = (out, now)
    return out


def invalidate_settings_cache(key: str | None = None) -> None:
    """Empty the option-chain settings cache. Called by the admin
    override save/delete paths so a change is visible to users on the
    next poll instead of lagging by up to `_SETTINGS_TTL`."""
    global _settings_cache
    if key is None:
        _settings_cache.clear()
    else:
        _settings_cache.pop(key, None)


async def _cached_catalog(und_key: str):
    """get_option_chain_fast wrapper with a 5-minute cache.

    Why we DON'T cache empty results: if a request lands before Zerodha is
    authenticated (or before the NFO/BFO catalog finishes warming), the
    underlying yields no options and we'd otherwise pin "TCS = []" for the
    next 5 minutes — even after the operator authenticates. By only caching
    non-empty hits, the next call retries the catalog scan and picks up
    fresh data on the same poll the picker is already running.
    """
    now = time.time()
    cached = _CATALOG_FILTER.get(und_key)
    if cached and (now - cached[1]) < _CATALOG_TTL and cached[0][0]:
        return cached[0]
    from app.services.zerodha_service import zerodha as _zerodha
    result = await _zerodha.get_option_chain_fast(und_key)
    if result[0]:
        _CATALOG_FILTER[und_key] = (result, now)
    else:
        # Surface this so operators can see WHY a stock (e.g. TCS) returns
        # no chain — usually Zerodha not authenticated or NFO not yet warmed.
        try:
            status = await _zerodha.get_status()
            logger.warning(
                "option_chain_empty_catalog",
                extra={
                    "underlying": und_key,
                    "zerodha_connected": status.get("isConnected"),
                    "zerodha_configured": status.get("isConfigured"),
                    "ws_status": status.get("wsStatus"),
                },
            )
        except Exception:
            logger.warning("option_chain_empty_catalog", extra={"underlying": und_key})
    return result


# NSE index tradingsymbols (with spaces) → NFO/BFO option-chain underlying keys.
# When the user opens the terminal on e.g. "NIFTY 50" (NSE index) and taps
# "Option chain", the instrument.symbol sent from the frontend is "NIFTY 50".
# After stripping spaces it becomes "NIFTY50" which doesn't match the NFO
# catalog's `name = "NIFTY"`, leaving the chain empty. This map bridges the gap.
_UNDERLYING_ALIASES: dict[str, str] = {
    "NIFTY50": "NIFTY",
    "NIFTYBANK": "BANKNIFTY",
    "NIFTYFINSERVICE": "FINNIFTY",
    "NIFTYMIDSELECT": "MIDCPNIFTY",
    "NIFTYMIDCAP150": "MIDCPNIFTY",
    "NIFTYNEXT50": "NIFTYNXT50",
}


def _norm_underlying(s: str) -> str:
    normed = (s or "").strip().upper().replace(" ", "")
    return _UNDERLYING_ALIASES.get(normed, normed)


# ── Crypto options chain (Binance eapi mirror) ──────────────────────────
def _crypto_option_root(und_key: str) -> str | None:
    """Return the crypto option root (e.g. "BTC") if `und_key` names a crypto
    underlying we have options for, else None. Accepts BTC / BTCUSD / BTCUSDT."""
    from app.core.config import settings

    roots = {
        r.strip().upper()
        for r in (settings.BINANCE_OPTIONS_UNDERLYINGS or "").split(",")
        if r.strip()
    }
    if not roots:
        return None
    k = (und_key or "").upper().replace(" ", "")
    for suffix in ("USDT", "USD"):
        if k.endswith(suffix):
            k = k[: -len(suffix)]
            break
    return k if k in roots else None


async def _crypto_option_chain(user: CurrentUser, root: str, expiry: str | None) -> APIResponse:
    """Build the crypto option chain from Mongo Instrument rows + live prices."""
    from app.models._base import SegmentType
    from app.models.instrument import Instrument
    from app.services import market_data_service

    rows = await Instrument.find(
        Instrument.segment == SegmentType.CRYPTO_OPTION_BUY.value,
        Instrument.is_active == True,  # noqa: E712
    ).to_list()
    # Keep only this root's contracts (symbol like "BTC-260925-145000-C").
    rows = [r for r in rows if (r.symbol or "").upper().startswith(f"{root}-")]

    # Distinct expiries (date) sorted ascending.
    def _exp_date(r):
        e = r.expiry
        return e.date() if hasattr(e, "date") else e

    expiries = sorted({_exp_date(r) for r in rows if r.expiry is not None})
    expiry_iso = [d.isoformat() for d in expiries]

    target = None
    if expiry:
        try:
            target = datetime.strptime(expiry[:10], "%Y-%m-%d").date()
        except Exception:
            target = None
    if target is None and expiries:
        target = expiries[0]

    # strike → {ce, pe} for the chosen expiry.
    by_strike: dict[float, dict[str, Any]] = {}
    legs: list[Instrument] = []
    for r in rows:
        if target is not None and _exp_date(r) != target:
            continue
        try:
            strike = float(str(r.strike)) if r.strike is not None else None
        except (TypeError, ValueError):
            strike = None
        if strike is None:
            continue
        side = "ce" if (r.option_type and r.option_type.value == "CE") else "pe"
        cell = by_strike.setdefault(strike, {"strike": strike, "ce": None, "pe": None})
        cell[side] = r
        legs.append(r)

    # Batch live quotes (mdlive/mdlast carry ltp/bid/ask + greeks per token).
    quotes: dict[str, dict] = {}
    if legs:
        results = await asyncio.gather(
            *[market_data_service.get_quote(l.token) for l in legs],
            return_exceptions=True,
        )
        for leg, q in zip(legs, results):
            if isinstance(q, dict):
                quotes[leg.token] = q

    def _leg_out(r: Instrument | None) -> dict[str, Any] | None:
        if r is None:
            return None
        q = quotes.get(r.token) or {}
        ltp = float(q.get("ltp") or 0)
        return {
            "token": r.token,
            "symbol": r.symbol,
            "exchange": "CRYPTO",
            "ltp": ltp,
            "bid": float(q.get("bid") or 0),
            "ask": float(q.get("ask") or 0),
            "change_pct": float(q.get("change_pct") or 0),
            "volume": float(q.get("volume") or 0),
            "delta": q.get("delta"),
            "theta": q.get("theta"),
            "iv": q.get("iv"),
            "source": q.get("source") or ("last" if ltp > 0 else "none"),
        }

    enriched_rows = [
        {"strike": cell["strike"], "ce": _leg_out(cell["ce"]), "pe": _leg_out(cell["pe"])}
        for cell in sorted(by_strike.values(), key=lambda c: c["strike"])
    ]

    # ATM: strike where |CE − PE| is smallest (put-call parity proxy); else the
    # strike nearest the live spot.
    atm_strike = None
    atm_spot = None
    both = [r for r in enriched_rows if r["ce"] and r["pe"] and r["ce"]["ltp"] and r["pe"]["ltp"]]
    if both:
        best = min(both, key=lambda r: abs(r["ce"]["ltp"] - r["pe"]["ltp"]))
        atm_strike = best["strike"]
        atm_spot = best["strike"] + best["ce"]["ltp"] - best["pe"]["ltp"]
    elif enriched_rows:
        spot = 0.0
        try:
            sq = await market_data_service.get_quote(f"CRYPTO_{root}USD")
            spot = float(sq.get("ltp") or 0)
        except Exception:
            spot = 0.0
        if spot > 0:
            atm_strike = min(enriched_rows, key=lambda r: abs(r["strike"] - spot))["strike"]
            atm_spot = spot
        else:
            atm_strike = enriched_rows[len(enriched_rows) // 2]["strike"]

    # Window to ATM ± N (super-admin CRYPTO_OPT setting) — the crypto chain
    # otherwise returns every listed strike.
    _crypto_window = await _strikes_around_atm_for("CRYPTO_OPT")
    if enriched_rows and _crypto_window > 0:
        _atm_idx = len(enriched_rows) // 2
        if atm_strike is not None:
            for _i, _r in enumerate(enriched_rows):
                if _r["strike"] == atm_strike:
                    _atm_idx = _i
                    break
        _lo = max(0, _atm_idx - _crypto_window)
        _hi = min(len(enriched_rows), _atm_idx + _crypto_window + 1)
        enriched_rows = enriched_rows[_lo:_hi]

    data_source = "live" if any(
        (cell.get(side) or {}).get("source") == "binance_options"
        for cell in enriched_rows for side in ("ce", "pe")
    ) else ("last" if enriched_rows else "none")

    return APIResponse(
        data={
            "underlying": root,
            "expiries": expiry_iso,
            "selected_expiry": target.isoformat() if target else None,
            "atm_strike": atm_strike,
            "atm_spot": atm_spot,
            "rows": enriched_rows,
            "data_source": data_source,
            "data_source_error": None,
            "market_open": True,  # crypto is 24×7
            "is_crypto": True,
        }
    )


@router.get("/config", response_model=APIResponse[dict])
async def option_chain_config(user: CurrentUser):
    """Public option-chain settings consumed by the picker UI."""
    # underlyings + max_expiries flow through the override hierarchy
    # (USER → BROKER → ADMIN → GLOBAL). strikes_around_atm stays global —
    # it's not part of the per-actor override surface.
    resolved = await _resolve_expiry_settings_for_user(user.id)
    underlyings = resolved["underlyings"]
    strikes_around_atm = int(await _read_setting("option_chain.strikes_around_atm", _DEFAULT_STRIKES_AROUND_ATM))
    max_expiries = int(resolved["max_expiries"])
    return APIResponse(
        data={
            "underlyings": underlyings,
            "strikes_around_atm": strikes_around_atm,
            "max_expiries": max_expiries,
            "max_expiries_by_exchange": resolved.get("max_expiries_by_exchange", {}),
        }
    )


@router.get("", response_model=APIResponse[dict])
async def option_chain(
    user: CurrentUser,
    underlying: str = Query(..., description="Symbol like NIFTY / BANKNIFTY / RELIANCE"),
    expiry: str | None = Query(default=None, description="ISO date; if omitted, nearest expiry"),
):
    und_key = _norm_underlying(underlying)

    # ── Crypto options branch ──────────────────────────────────────────
    # Crypto option data lives in Mongo (Binance eapi mirror), NOT the Zerodha
    # CSV catalog, so it takes a separate, simpler path: strikes/expiries from
    # the Instrument rows, live prices + greeks from get_quote (mdlive/mdlast).
    _crypto_root = _crypto_option_root(und_key)
    if _crypto_root is not None:
        return await _crypto_option_chain(user, _crypto_root, expiry)

    # ── Response cache hit? Bail out fast (matches the picker's 2 s poll). ──
    # Cache key includes user.id so each user's per-symbol block set
    # produces a distinct cached payload — otherwise a row blocked
    # for user A could be served from cache to user B who has access
    # to it.
    cache_key = f"{user.id}|{und_key}|{(expiry or '').strip()}"
    now_t = time.time()
    cached_resp = _CHAIN_CACHE.get(cache_key)
    if cached_resp and (now_t - cached_resp[1]) < _CHAIN_TTL:
        return APIResponse(data=cached_resp[0])

    # ── Catalog filter (cached 5 min — CSV doesn't change intraday) ──
    options, all_expiry_dates = await _cached_catalog(und_key)
    from app.services.zerodha_service import zerodha as _zerodha

    # Distinct expiries (sorted asc) — capped to the configured max for THIS
    # user. A per-script max_expiries (set on the underlying chip) wins over
    # the resolved fallback; both flow through the override hierarchy.
    # Per-underlying value wins; else the per-exchange (NSE/BSE/MCX) fallback
    # picked from this underlying's option exchange; else the legacy single.
    _resolved_exp = await _resolve_expiry_settings_for_user(user.id)
    _sample_ex = (options[0].get("exchange") if options else "") or ""
    max_expiries = _effective_max_expiries(_resolved_exp, und_key, _sample_ex)
    # MONTHS, not a count of dates — see `_limit_to_expiry_months`. Identical
    # for monthly contracts (MCX, futures); the difference shows on weeklies.
    expiries = _limit_to_expiry_months(all_expiry_dates, max_expiries)
    expiry_iso = [d.isoformat() for d in expiries]

    # Pick effective expiry
    target: date | None = None
    if expiry:
        try:
            target = datetime.strptime(expiry[:10], "%Y-%m-%d").date()
        except Exception:
            target = None
    if target is None and expiries:
        target = expiries[0]

    # Build strike → {ce, pe} grid for the chosen expiry
    by_strike: dict[float, dict[str, Any]] = {}
    for o in options:
        if target is not None and o.get("_expiry_date") != target:
            continue
        strike = float(o["strike"]) if o.get("strike") is not None else None
        if strike is None:
            continue
        cell = by_strike.setdefault(strike, {"strike": strike, "ce": None, "pe": None})
        cell["ce" if o["option_type"] == "CE" else "pe"] = o

    all_rows = sorted(by_strike.values(), key=lambda r: r["strike"])

    # REAL underlying spot (feed) — anchors both the strike-far filter and the
    # ATM window so the chain is symmetric around the true ATM (fixes strikes on
    # one side going missing). None → fall back to parity/median below.
    real_spot = await _underlying_spot(und_key)

    # ── Strike-far cap (admin matrix → Options → Max % from underlying) ──
    # Hide every strike outside ±strikeFarPercent of the underlying's spot
    # so the chain dialog only shows tradeable strikes (the validator
    # rejects anything farther anyway). Underlying admin row is derived
    # from the option exchange — NFO → NSE_OPT, BFO → BSE_OPT, MCX → MCX_OPT.
    # Zero from admin = no cap, full chain renders.
    if all_rows:
        sample = all_rows[0].get("ce") or all_rows[0].get("pe") or {}
        opt_exch = (sample.get("exchange") or "").upper()
        admin_row = {
            # Option chains here are index underlyings (NIFTY/BANKNIFTY/…),
            # so NFO strike-far reads the Index Option settings row.
            "NFO": "NSE_IDX_OPT",
            "BFO": "BSE_OPT",
            "MCX": "MCX_OPT",
        }.get(opt_exch)
        if admin_row:
            from app.services.netting_service import resolve_strike_far

            far_pct = await resolve_strike_far(admin_row)
            if far_pct > 0:
                # Underlying spot: take from any cached LTP on the option
                # legs (CE − PE parity gives a working spot proxy for the
                # ATM row), fall back to the median strike. Avoids a
                # blocking Kite REST call on the chain hot path.
                # Prefer the REAL underlying spot; parity/median only as fallback.
                spot_guess: float | None = real_spot if (real_spot and real_spot > 0) else None
                # Quick proxy: scan rows for both-side LTPs and pick the
                # parity-derived spot at the strike with smallest CE−PE.
                with_both = []
                for idx, r in (enumerate(all_rows) if spot_guess is None else []):
                    ce_ltp = _row_cached_ltp(r, "ce") if False else None  # see below
                    # _row_cached_ltp is defined further down in this file;
                    # inline a tiny version here to avoid forward-reference.
                    cell_ce = r.get("ce")
                    cell_pe = r.get("pe")
                    if not (cell_ce and cell_pe):
                        continue
                    try:
                        tc = int(cell_ce.get("token") or 0)
                        tp = int(cell_pe.get("token") or 0)
                    except (TypeError, ValueError):
                        continue
                    ce_live = _zerodha.ticks_by_token.get(tc) if tc else None
                    pe_live = _zerodha.ticks_by_token.get(tp) if tp else None
                    ce_ltp = float(ce_live.get("ltp") or 0) if ce_live else 0.0
                    pe_ltp = float(pe_live.get("ltp") or 0) if pe_live else 0.0
                    if ce_ltp > 0 and pe_ltp > 0:
                        with_both.append((idx, ce_ltp - pe_ltp, r["strike"]))
                if with_both:
                    # ATM = smallest |CE−PE|; spot ≈ strike + (CE−PE).
                    best = min(with_both, key=lambda x: abs(x[1]))
                    spot_guess = best[2] + best[1]
                if spot_guess is None and all_rows:
                    spot_guess = float(all_rows[len(all_rows) // 2]["strike"])

                if spot_guess and spot_guess > 0:
                    lo_bound = spot_guess * (1 - far_pct / 100.0)
                    hi_bound = spot_guess * (1 + far_pct / 100.0)
                    all_rows = [
                        r for r in all_rows
                        if lo_bound <= float(r["strike"]) <= hi_bound
                    ]

    # ── Trim BEFORE we touch Kite ────────────────────────────────────
    # Two-stage ATM detection so we can shrink the work BEFORE doing the
    # expensive subscribe + quote step:
    #   1. Use any cached LTP from the in-memory ticker map to find a real
    #      ATM (parity-derived spot ≈ strike where |CE-PE| is smallest).
    #   2. If no LTPs are cached yet (cold start), fall back to the median
    #      strike — close enough for the first paint; the next 2 s poll
    #      will have real LTPs and recentre.
    strikes_around_atm = await _strikes_around_atm_for(_strikes_seg_key(_sample_ex, und_key))

    def _row_cached_ltp(row: dict[str, Any], side: str) -> float | None:
        cell = row.get(side)
        if not cell:
            return None
        try:
            tok_int = int(cell.get("token") or 0)
        except (TypeError, ValueError):
            tok_int = 0
        live = _zerodha.ticks_by_token.get(tok_int) if tok_int else None
        if live is None:
            sym = cell.get("symbol")
            if sym:
                live = _zerodha.ticks_by_symbol.get(sym)
        if live is None:
            return None
        try:
            return float(live.get("ltp") or 0) or None
        except (TypeError, ValueError):
            return None

    pre_atm_idx = len(all_rows) // 2
    if all_rows and real_spot and real_spot > 0:
        # Anchor on the TRUE spot — the robust, symmetric center. Nearest strike.
        pre_atm_idx = min(
            range(len(all_rows)),
            key=lambda i: abs(float(all_rows[i]["strike"]) - real_spot),
        )
    elif all_rows:
        with_both = [
            (i, abs(c - p))
            for i, r in enumerate(all_rows)
            if (c := _row_cached_ltp(r, "ce")) is not None
            and (p := _row_cached_ltp(r, "pe")) is not None
        ]
        if with_both:
            pre_atm_idx = min(with_both, key=lambda x: x[1])[0]

    if all_rows and strikes_around_atm > 0:
        lo = max(0, pre_atm_idx - strikes_around_atm)
        hi = min(len(all_rows), pre_atm_idx + strikes_around_atm + 1)
        rows = all_rows[lo:hi]
    else:
        rows = all_rows

    # ── Enrich ONLY the visible window with live prices ──────────────
    batch_keys: list[str] = []
    tokens_for_ws: list[int] = []
    sym_map_for_ws: dict[int, dict[str, str]] = {}
    for r in rows:
        for side in ("ce", "pe"):
            cell = r.get(side)
            if cell and cell.get("exchange") and cell.get("symbol"):
                batch_keys.append(f"{cell['exchange']}:{cell['symbol']}")
                try:
                    t = int(cell["token"])
                    tokens_for_ws.append(t)
                    sym_map_for_ws[t] = {"symbol": cell["symbol"], "exchange": cell["exchange"]}
                except (TypeError, ValueError):
                    pass

    # On-demand subscribe ONLY the visible window. Don't await on it (fire-
    # and-forget) so a slow WS spawn can't block the response.
    if tokens_for_ws:
        try:
            asyncio.create_task(
                _zerodha.subscribe_tokens_on_demand(tokens_for_ws, sym_map_for_ws)
            )
        except Exception:
            pass

    # Hard timeout on Kite REST batch — at worst the user sees stale or
    # missing prices for one tick; the picker re-polls in 2 s and tries again.
    batch_snapshots: dict[str, dict[str, Any]] = {}
    batch_error: str | None = None
    if batch_keys:
        try:
            batch_snapshots, batch_error = await asyncio.wait_for(
                _zerodha.get_quotes_batch_snapshot(batch_keys),
                timeout=_KITE_BATCH_QUOTE_TIMEOUT_SEC,
            )
        except asyncio.TimeoutError:
            batch_error = f"Kite /quote timed out after {_KITE_BATCH_QUOTE_TIMEOUT_SEC}s"
        except Exception as e:
            batch_error = str(e)

    def enrich(leg: dict[str, Any] | None) -> dict[str, Any] | None:
        if leg is None:
            return None

        token = leg.get("token")
        symbol = leg.get("symbol")
        exchange = leg.get("exchange")

        # 1) Live tick (KiteTicker push)
        live: dict[str, Any] | None = None
        source: str | None = None
        try:
            live = _zerodha.ticks_by_token.get(int(token)) if token else None
            if live is not None:
                source = "live"
        except (TypeError, ValueError):
            live = None
        if live is None and symbol:
            sym_live = _zerodha.ticks_by_symbol.get(symbol)
            if sym_live is not None:
                live = sym_live
                source = "live"

        # 2) REST batch snapshot pre-fetched above
        if live is None and exchange and symbol:
            key = f"{exchange}:{symbol}"
            snap = batch_snapshots.get(key)
            if snap is not None:
                live = snap
                source = "rest"

        if not live:
            return {
                **leg,
                "ltp": None, "bid": None, "ask": None,
                "change_pct": None, "volume": None, "source": None,
            }

        ltp = live.get("ltp")
        prev_close = live.get("close") or live.get("prev_close")
        change_pct = None
        try:
            if ltp is not None and prev_close:
                change_pct = round(((float(ltp) - float(prev_close)) / float(prev_close)) * 100, 2)
        except (TypeError, ValueError, ZeroDivisionError):
            change_pct = None

        return {
            **leg,
            "ltp": float(ltp) if ltp is not None else None,
            "bid": float(live["bid"]) if live.get("bid") is not None else None,
            "ask": float(live["ask"]) if live.get("ask") is not None else None,
            "change_pct": change_pct,
            "volume": int(live["volume"]) if live.get("volume") is not None else None,
            "source": source,
        }

    # Per-symbol block — drop strikes whose CE / PE symbol is blocked
    # for this user by an admin / broker / user-level override. If
    # both legs are blocked the strike row disappears entirely; if
    # only one side is blocked it's nulled so the chain still shows
    # the remaining leg.
    from app.services.netting_service import (
        get_user_blocked_symbols,
        is_symbol_blocked_for,
    )

    blocked = await get_user_blocked_symbols(user.id)

    def _filter_leg(leg: dict[str, Any] | None) -> dict[str, Any] | None:
        if leg is None:
            return None
        sym = leg.get("symbol") or ""
        if is_symbol_blocked_for(sym, blocked):
            return None
        return leg

    enriched_rows = []
    for r in rows:
        ce_leg = _filter_leg(r["ce"])
        pe_leg = _filter_leg(r["pe"])
        if ce_leg is None and pe_leg is None:
            continue
        enriched_rows.append(
            {
                "strike": r["strike"],
                "ce": enrich(ce_leg),
                "pe": enrich(pe_leg),
            }
        )

    # ATM: strike where |CE LTP - PE LTP| is smallest
    atm_strike = None
    atm_spot = None
    if enriched_rows:
        with_both = [r for r in enriched_rows if r["ce"] and r["pe"] and r["ce"].get("ltp") and r["pe"].get("ltp")]
        if with_both:
            best = min(with_both, key=lambda r: abs(r["ce"]["ltp"] - r["pe"]["ltp"]))
            atm_strike = best["strike"]
            atm_spot = best["strike"] + best["ce"]["ltp"] - best["pe"]["ltp"]
        else:
            atm_strike = enriched_rows[len(enriched_rows) // 2]["strike"]

    # No second trim — we already trimmed BEFORE enrichment (above).

    # Aggregate data source
    leg_sources = [
        cell.get("source")
        for r in enriched_rows
        for side in ("ce", "pe")
        if (cell := r.get(side)) and cell.get("source")
    ]
    data_source = "live" if "live" in leg_sources else ("rest" if "rest" in leg_sources else "none")

    from app.utils.time_utils import is_market_open as _is_market_open
    response_data = {
        "underlying": und_key,
        "expiries": expiry_iso,
        "selected_expiry": target.isoformat() if target else None,
        "atm_strike": atm_strike,
        "atm_spot": atm_spot,
        "rows": enriched_rows,
        "data_source": data_source,
        "data_source_error": batch_error,
        # The picker drops the day-change pill when this is False so the
        # strip looks clean after-hours (no big red −20 % numbers on stale
        # ticks). LTP itself is still the last traded price from REST/WS.
        "market_open": _is_market_open(),
    }
    # Cache the full response — next call within _CHAIN_TTL hits the early
    # return above and skips all this work.
    _CHAIN_CACHE[cache_key] = (response_data, time.time())
    return APIResponse(data=response_data)
