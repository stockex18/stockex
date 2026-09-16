"""Is this exchange actually open today? The calendar the admin maintains.

The `trading_holidays` collection had an admin screen and CRUD endpoints from
day one, but nothing in the trading path ever read it: `is_weekend` was the
only "is the market shut" signal anywhere. So on a holiday the platform ran a
full day — the risk enforcer stopped positions out against the previous
session's frozen tick, the 15:41 sweep squared off intraday positions, and any
contract expiring that day settled at a price the exchange never printed.

One helper, read from the three places that decide whether a session exists.
Half-days and Muhurat sessions are NOT holidays — the market does open — so
only `is_full_day` rows count here.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, time, timedelta

logger = logging.getLogger(__name__)

# The collection keeps one calendar per exchange. A position's segment name is
# what we have at the call sites, so map it here rather than at each of them.
_NSE_PREFIXES = ("NSE", "BSE", "NFO", "BFO")

# (exchange, iso date) -> (answered_at, is a full-day holiday). Short TTL
# because each gunicorn worker caches separately: the admin's edit lands in one
# worker, so the others must age their answer out rather than wait for a
# message that never crosses the process boundary.
_CACHE_TTL_SEC = 60.0
_cache: dict[tuple[str, str], tuple[float, bool]] = {}


def clear_cache() -> None:
    """Called by the admin holiday endpoints so the edit lands at once in the
    worker that served the request; the rest follow within the TTL."""
    _cache.clear()


def exchange_for_segment(segment: str | None) -> str | None:
    """NSE / MCX for the Indian exchanges, None for the 24x7 and 24x5 feeds
    (crypto, forex) — those never have a holiday to observe."""
    if not segment:
        return None
    seg = str(segment).upper()
    if seg.startswith("MCX"):
        return "MCX"
    if seg.startswith(_NSE_PREFIXES):
        return "NSE"
    return None


async def is_market_holiday(exchange: str | None, d: date | None = None) -> bool:
    """True when `exchange` has a FULL-day holiday on `d` (default: today IST).

    Returns False for an unknown exchange, and False on any lookup error — a
    database hiccup must not silently freeze trading for everyone.
    """
    if not exchange:
        return False
    if d is None:
        from app.utils.time_utils import now_ist

        d = now_ist().date()

    import time as _t

    key = (exchange, d.isoformat())
    hit = _cache.get(key)
    if hit is not None and (_t.monotonic() - hit[0]) < _CACHE_TTL_SEC:
        return hit[1]

    try:
        from app.models.holiday import TradingHoliday

        # Stored as a BSON datetime at midnight; match the whole day rather
        # than relying on how a `date` is encoded at query time.
        lo = datetime.combine(d, time.min)
        # NSE / BSE / NFO / BFO share one calendar in practice, and the admin
        # screen lets either name be picked — so a row filed under BSE must
        # still close an NSE position. MCX keeps its own.
        names = ["MCX"] if exchange == "MCX" else ["NSE", "BSE", "NFO", "BFO"]
        row = await TradingHoliday.find_one(
            {
                "exchange": {"$in": names},
                "holiday_date": {"$gte": lo, "$lt": lo + timedelta(days=1)},
                "is_full_day": True,
            }
        )
        out = row is not None
    except Exception:
        logger.warning("holiday_lookup_failed", exc_info=True)
        return False

    _cache[key] = (_t.monotonic(), out)
    return out


async def is_segment_holiday(segment: str | None, d: date | None = None) -> bool:
    """Segment-flavoured wrapper for call sites that hold a position/instrument."""
    return await is_market_holiday(exchange_for_segment(segment), d)
