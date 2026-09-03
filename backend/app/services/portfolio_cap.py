"""Where the portfolio leverage cap comes from.

The cap bounds a WALLET's TOTAL open exposure at `balance x cap`, regardless of
what leverage each individual instrument is allowed. It exists because the
plain per-order funds check cannot see blended drift: a high-leverage leg locks
little margin for large notional, freeing room a low-leverage leg then spends,
so the book's combined leverage creeps past the intended maximum even though
every single order passed its own check.

It lived only in `config.py` as a hardcoded 33.33 for NSE/BSE. That number was
invisible: it appears nowhere in the admin panel, and an admin who had set 50x
per-instrument margin had no way to discover why orders were being refused at
33.33x, let alone change it. Two rules that contradict each other and only one
of them on screen.

So it is a platform setting now, with the environment value as the fallback.
The admin edits it; nothing has to be redeployed.

    portfolio.max_leverage.NSE_BSE      admin-editable, wins
    PORTFOLIO_MAX_LEVERAGE_NSE_BSE      env / config default, fallback

0 means NO CAP for that wallet — which is what MCX, CRYPTO and FOREX ship as.
CRYPTO and FOREX quote notional in USD against an INR wallet balance, so a cap
there would compare two different currencies; they stay 0 until that is
normalised.

READ THIS BEFORE CHANGING A VALUE: the cap is not only an order gate. The risk
enforcer reads it every tick and FORCE-CLOSES positions, oldest first, while
the book is over it. LOWERING it can therefore close somebody's open position
on the next tick. Raising it only ever closes fewer.
"""

from __future__ import annotations

import logging
import time
from typing import Any

logger = logging.getLogger(__name__)

KEY_PREFIX = "portfolio.max_leverage."

#: The wallet kinds the cap is defined for. Same keys as
#: `config.portfolio_leverage_caps`.
WALLET_KINDS: tuple[str, ...] = ("NSE_BSE", "MCX", "CRYPTO", "FOREX")

#: Read on the order path and on every risk tick, so it is cached. Short enough
#: that an admin edit takes effect within a minute without a restart.
_TTL = 30.0
_cache: dict[str, tuple[Any, float]] = {}


def setting_key(kind: str) -> str:
    return KEY_PREFIX + kind


def invalidate() -> None:
    """Drop the cache so the next read sees a fresh value."""
    _cache.clear()


async def caps() -> dict[str, float]:
    """Effective cap per wallet kind: the platform setting where one exists,
    otherwise the configured default.

    Never raises. A database hiccup falls back to config, which is the value
    the deployment was running before this existed — the safe direction, since
    the alternative is treating every cap as 0 (no limit at all) on a blip.
    """
    from app.core.config import settings as cfg

    out = dict(cfg.portfolio_leverage_caps)
    now = time.time()
    try:
        from app.models.platform_setting import PlatformSetting

        for kind in WALLET_KINDS:
            key = setting_key(kind)
            hit = _cache.get(key)
            if hit and (now - hit[1]) < _TTL:
                val = hit[0]
            else:
                # Dict query, not `PlatformSetting.setting_key == key`: the
                # class-attribute form only resolves once Beanie has been
                # initialised, so it cannot be exercised without a database.
                row = await PlatformSetting.find_one({"setting_key": key})
                val = row.setting_value if row is not None else None
                _cache[key] = (val, now)
            if val is None:
                continue
            try:
                # A negative cap is meaningless and would block every order;
                # treat it as "unset" rather than as a very small limit.
                num = float(val)
            except (TypeError, ValueError):
                logger.warning(
                    "portfolio_cap_unreadable", extra={"key": key, "value": val}
                )
                continue
            if num >= 0:
                out[kind] = num
    except Exception:  # noqa: BLE001
        logger.debug("portfolio_cap_read_failed", exc_info=True)
    return out


async def cap_for(kind: str) -> float:
    return float((await caps()).get(kind, 0) or 0)
