"""Super-admin settings for crypto option expiry.

Two knobs, both asked for by the operator:

    max_expiries how many expiries to list, nearest first — the same count
                 the NSE / BSE / MCX boxes take, so one number means one thing
                 across the platform. 1 = the nearest expiry only.

                 It is a COUNT and not a number of days on purpose. Crypto
                 expires daily, so the two agree right up until the moment
                 today's contract settles: after 13:30 IST Binance drops it,
                 the nearest expiry becomes tomorrow's, and a day-based cap
                 would quietly list nothing for the rest of the day. 0 / unset
                 keeps the platform default.

    settle_time  the IST clock time on the expiry date when open positions on
                 that contract are closed. Was hardcoded at 08:00 UTC, which
                 is 13:30 IST, and that is the default here so nothing moves
                 for anyone who never touches the setting.

Read on a 60 s cache: the settlement sweep asks once a minute and the universe
refresh every few minutes, and neither needs a database round-trip each time.
"""

from __future__ import annotations

import time as _t
from datetime import time as _time
from typing import Any

from app.models.platform_setting import PlatformSetting

#: Binance settles its options at 08:00 UTC = 13:30 IST. Keeping that as the
#: default means an operator who never opens the setting sees no change.
DEFAULT_SETTLE_IST = "13:30"

MAX_EXPIRIES_KEY = "crypto_expiry.max_expiries"
#: The first name this setting shipped under, read as a fallback so a value
#: saved before the rename keeps working — it was always the same intent.
LEGACY_MAX_DAYS_KEY = "crypto_expiry.max_days"
SETTLE_TIME_KEY = "crypto_expiry.settle_time"

_CACHE_TTL = 60.0
_cache: dict[str, tuple[Any, float]] = {}


async def _read(key: str, default: Any) -> Any:
    hit = _cache.get(key)
    now = _t.monotonic()
    if hit and (now - hit[1]) < _CACHE_TTL:
        return hit[0]
    try:
        row = await PlatformSetting.find_one(PlatformSetting.setting_key == key)
        val = row.setting_value if row is not None else default
    except Exception:  # noqa: BLE001 — a settings read must never break a sweep
        return default
    _cache[key] = (val, now)
    return val


def invalidate() -> None:
    """Drop the cache so a save is visible on the next sweep, not a minute on."""
    _cache.clear()


async def max_expiries() -> int:
    """How many expiries to list, nearest first. 0 = use the platform default."""
    raw = await _read(MAX_EXPIRIES_KEY, 0)
    if not raw:
        raw = await _read(LEGACY_MAX_DAYS_KEY, 0)
    try:
        n = int(raw or 0)
    except (TypeError, ValueError):
        return 0
    return n if n > 0 else 0


async def settle_time_ist() -> _time:
    """IST clock time on the expiry date when open positions are closed."""
    raw = str(await _read(SETTLE_TIME_KEY, DEFAULT_SETTLE_IST) or DEFAULT_SETTLE_IST)
    try:
        hh, mm = raw.strip().split(":")[:2]
        return _time(int(hh) % 24, int(mm) % 60)
    except Exception:  # noqa: BLE001 — a typo must not stop settlement
        hh, mm = DEFAULT_SETTLE_IST.split(":")
        return _time(int(hh), int(mm))
