"""Super-admin lot sizes (models/lot_size_override.py), looked up first.

Every place that decides "how many shares / units are in one lot" asks the
coded tables in index_lots.py / infoway_lots.py (or, for NSE / BSE F&O at
order time, the Zerodha CSV). Those lookups ask THIS module first, so a
super-admin row wins everywhere: order placement, the order panel's
/segment-settings, instrument auto-create, the startup backfill and the
repair endpoint.

The rows live in Mongo; each worker keeps an in-memory copy so the sync
lookups stay sync. `refresh()` reloads it when older than MAX_AGE_SEC and is
awaited at startup and on the paths that size an order, so another worker's
change is picked up within seconds. Saving or deleting a row also rewrites
the matching Instrument rows straight away (`apply_to_instruments`).

Open positions are not touched: each Position carries the instrument (and
its lot size) as it was at fill time, and its quantity is in units, so a
new lot size only changes new orders.
"""

from __future__ import annotations

import logging
import re
import time
from typing import Any

logger = logging.getLogger(__name__)

#: How stale a worker's copy may get before the next refresh reloads it.
MAX_AGE_SEC = 5.0
LOT_SIZE_MAX = 10_000_000

#: INDIAN keys are contract names before the expiry (M&M, BAJAJ-AUTO keep
#: their & and -; NIFTYNXT50 / SENSEX50 keep their digits). INTERNATIONAL
#: keys are feed symbols (SPX500, US30).
UNDERLYING_RE = {
    "INDIAN": re.compile(r"^[A-Z][A-Z0-9&\-]{0,29}$"),
    "INTERNATIONAL": re.compile(r"^[A-Z][A-Z0-9]{0,29}$"),
}
#: BTC options (Binance, e.g. BTC-261127-90000-C) are keyed "BTC".
BTC_OPTIONS_KEY = "BTC"

_INDIAN_ROOT_RE = re.compile(r"^([A-Z][A-Z&\-]*)")
_INDIAN_EXCHANGES = ("NSE", "BSE", "MCX", "NFO", "BFO")
_FNO_TYPES = ("FUT", "CE", "PE")

_indian: dict[str, int] = {}
_international: dict[str, int] = {}
_loaded_at = 0.0


def clean_underlying(underlying: str) -> str:
    return re.sub(r"\s+", "", str(underlying or "")).upper()


def indian_root(s: str | None) -> str:
    t = re.sub(r"\s+", "", str(s or "")).upper()
    m = _INDIAN_ROOT_RE.match(t)
    return m.group(1) if m else t


def _intl_key(symbol: str | None) -> str:
    key = str(symbol or "").strip().upper()
    # BTCUSDT → BTCUSD, the same trim infoway_lots does.
    return key[:-1] if key.endswith("USDT") else key


def indian_matches(key: str, candidate: str | None) -> bool:
    """Whether a contract symbol / name belongs to the underlying `key`.

    The root (letters before the expiry) decides, so GOLDM26DECFUT is GOLDM,
    not GOLD. A key with digits (NIFTYNXT50) has no clean root, so it matches
    a symbol that starts with it and then the expiry's digits.
    """
    t = re.sub(r"\s+", "", str(candidate or "")).upper()
    if not t:
        return False
    if t == key or indian_root(t) == key:
        return True
    return (
        any(ch.isdigit() for ch in key)
        and t.startswith(key)
        and t[len(key):len(key) + 1].isdigit()
    )


def indian_lot(*candidates: str | None) -> int | None:
    """Super-admin lot for an NSE / BSE / MCX contract, or None."""
    if not _indian:
        return None
    for c in candidates:
        if not c:
            continue
        if lot := _indian.get(indian_root(c)):
            return lot
        # Longest first: NIFTYNXT50 before anything shorter.
        for key in sorted(_indian, key=len, reverse=True):
            if indian_matches(key, c):
                return _indian[key]
    return None


def international_lot(symbol: str | None) -> int | None:
    """Super-admin lot for an Infoway symbol (or "BTC" for BTC options)."""
    if not _international or not symbol:
        return None
    return _international.get(_intl_key(symbol))


def set_local(market: str, underlying: str, lot_size: int | None) -> None:
    """Update this worker's copy at once (other workers catch up on refresh)."""
    table = _indian if market == "INDIAN" else _international
    if lot_size:
        table[underlying] = int(lot_size)
    else:
        table.pop(underlying, None)


async def refresh(max_age: float = MAX_AGE_SEC) -> None:
    global _indian, _international, _loaded_at
    if max_age and time.monotonic() - _loaded_at < max_age:
        return
    from app.models.lot_size_override import LotSizeOverride

    try:
        rows = await LotSizeOverride.find_all().to_list()
    except Exception:
        # Keep the last good copy; a DB blip must not drop the admin's sizes.
        logger.exception("lot_overrides_refresh_failed")
        return
    indian: dict[str, int] = {}
    intl: dict[str, int] = {}
    for r in rows:
        market = getattr(r.market, "value", r.market)
        if int(r.lot_size or 0) > 0:
            (indian if market == "INDIAN" else intl)[r.underlying] = int(r.lot_size)
    _indian, _international, _loaded_at = indian, intl, time.monotonic()


# ── Built-in values (what applies with no super-admin row) ──────────────


def builtin_lot(market: str, underlying: str) -> int | None:
    """The coded value for an underlying, ignoring super-admin rows. None
    for NSE / BSE stock F&O, which follow the exchange's (Zerodha) lot."""
    from app.services import index_lots
    from app.services.infoway_lots import BTC_OPTION_LOT_SIZE, INFOWAY_LOT_SIZES

    if market == "INDIAN":
        coded = dict(index_lots.INDEX_LOT_SIZES) | dict(index_lots.MCX_LOT_SIZES)
        return coded.get(underlying)
    if underlying == BTC_OPTIONS_KEY:
        return BTC_OPTION_LOT_SIZE
    return INFOWAY_LOT_SIZES.get(underlying)


def builtin_table() -> list[dict[str, Any]]:
    """Every coded lot size, for the admin page's reference list."""
    from app.services import index_lots
    from app.services.infoway_lots import BTC_OPTION_LOT_SIZE, INFOWAY_LOT_SIZES

    out: list[dict[str, Any]] = [
        {"market": "INDIAN", "group": "NSE / BSE index F&O", "underlying": u, "lot_size": n}
        for u, n in index_lots.INDEX_LOT_SIZES
    ]
    out += [
        {"market": "INDIAN", "group": "MCX", "underlying": u, "lot_size": n}
        for u, n in index_lots.MCX_LOT_SIZES
    ]
    out.append({
        "market": "INTERNATIONAL", "group": "BTC options",
        "underlying": BTC_OPTIONS_KEY, "lot_size": BTC_OPTION_LOT_SIZE,
    })
    out += [
        {"market": "INTERNATIONAL", "group": "International", "underlying": u, "lot_size": n}
        for u, n in INFOWAY_LOT_SIZES.items()
    ]
    return out


# ── Rewriting the stored Instrument rows ────────────────────────────────


def _indian_target(inst: Any, csv_by_token: dict[int, dict]) -> int | None:
    from app.services.index_lots import get_canonical_lot_size

    ex = getattr(inst.exchange, "value", inst.exchange)
    it = getattr(inst.instrument_type, "value", inst.instrument_type)
    target = get_canonical_lot_size(inst.symbol, inst.name, exchange=ex, instrument_type=it)
    if target or ex == "MCX":
        return target
    # Stock F&O with no row: back to the exchange's lot.
    try:
        row = csv_by_token.get(int(inst.token))
    except (TypeError, ValueError):
        row = None
    lot = int((row or {}).get("lotSize") or 0)
    return lot or None


async def _indian_targets(underlying: str) -> dict[int, list]:
    from app.models.instrument import Instrument
    from app.services.zerodha_service import zerodha as _zerodha

    csv_by_token: dict[int, dict] = {}
    for ex_key in ("NFO", "BFO"):
        for r in _zerodha._instruments_cache.get(ex_key, []):
            try:
                csv_by_token[int(r.get("token"))] = r
            except (TypeError, ValueError):
                continue
    rows = await Instrument.find({
        "instrument_type": {"$in": list(_FNO_TYPES)},
        "exchange": {"$in": list(_INDIAN_EXCHANGES)},
        "$or": [
            {"symbol": {"$regex": f"^{re.escape(underlying)}(?![A-Z&-])"}},
            {"name": underlying},
        ],
    }).to_list()
    by_target: dict[int, list] = {}
    for inst in rows:
        # The regex is a first cut; the root decides (M&M vs MM…).
        if not (indian_matches(underlying, inst.symbol) or indian_matches(underlying, inst.name)):
            continue
        t = _indian_target(inst, csv_by_token)
        if t and int(inst.lot_size or 0) != t:
            by_target.setdefault(t, []).append(inst.id)
    return by_target


async def _international_targets(underlying: str) -> dict[int, list]:
    from app.models.instrument import Instrument
    from app.services.infoway_lots import btc_option_lot_size, get_infoway_lot_size
    from app.services.market_data_service import is_infoway_lot_segment

    if underlying == BTC_OPTIONS_KEY:
        q: dict[str, Any] = {"symbol": {"$regex": r"^BTC-\d{6}-\d+-[CP]$"}}
    else:
        q = {"symbol": {"$in": [underlying, underlying + "T"]}}
    by_target: dict[int, list] = {}
    for inst in await Instrument.find(q).to_list():
        if not is_infoway_lot_segment(inst.segment):
            continue
        t = btc_option_lot_size(inst.symbol, inst.segment) or get_infoway_lot_size(inst.symbol, inst.segment)
        if t and int(inst.lot_size or 0) != t:
            by_target.setdefault(t, []).append(inst.id)
    return by_target


async def apply_to_instruments(market: str, underlying: str) -> int:
    """Rewrite `lot_size` on every Instrument of this underlying to what now
    applies (the super-admin row, or the built-in value once it is deleted).
    Returns how many rows changed."""
    from app.models.instrument import Instrument

    if market == "INDIAN":
        by_target = await _indian_targets(underlying)
    else:
        by_target = await _international_targets(underlying)
    changed = 0
    for t, ids in by_target.items():
        await Instrument.find({"_id": {"$in": ids}}).update({"$set": {"lot_size": t}})
        changed += len(ids)
    return changed
