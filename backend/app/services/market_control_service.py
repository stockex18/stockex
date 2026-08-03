"""Enforcement helper for the super-admin MARKET CONTROL (per-segment hours)."""

from __future__ import annotations

import logging

from app.core.redis_client import cache_get, cache_set
from app.models.market_control import MarketControl
from app.utils.time_utils import now_ist, parse_hhmm

logger = logging.getLogger(__name__)


async def market_control_reason(admin_row: str | None) -> str | None:
    """If the SA has ENABLED market control for this segment AND the current IST
    time is OUTSIDE [open_time, close_time], return a human-readable block reason;
    otherwise None (trade allowed). Cached ~30 s per segment so the order path
    stays cheap; the cache is wiped when the SA saves a control row."""
    if not admin_row:
        return None
    ck = f"mktctl:{admin_row}"
    cfg = None
    try:
        cfg = await cache_get(ck)
    except Exception:
        cfg = None
    if not isinstance(cfg, dict):
        row = await MarketControl.find_one(MarketControl.segment_name == admin_row)
        cfg = {
            "enabled": bool(row.enabled) if row else False,
            "open": (row.open_time if row else "") or "",
            "close": (row.close_time if row else "") or "",
        }
        try:
            await cache_set(ck, cfg, ttl_sec=30)
        except Exception:
            pass
    if not cfg.get("enabled"):
        return None
    try:
        ot = parse_hhmm(cfg.get("open") or "")
        ct = parse_hhmm(cfg.get("close") or "")
    except Exception:
        return None
    now_t = now_ist().time()
    if ot is not None and now_t < ot:
        return f"Market opens at {cfg.get('open')} IST for this segment (admin control)."
    if ct is not None and now_t > ct:
        return f"Market closed at {cfg.get('close')} IST for this segment (admin control)."
    return None


async def closed_segments() -> set[str]:
    """Set of segment codes the SA has ENABLED market control on AND that are
    currently OUTSIDE their [open, close] window — i.e. closed right now. Used to
    FREEZE the live price feed for those segments (crypto / forex stream 24×7 from
    Infoway, so without this their price keeps moving on the platform even after
    the SA closes them). Cached ~15 s; wiped with the rest of `mktctl:*` on save."""
    ck = "mktctl:closed_set"
    try:
        cached = await cache_get(ck)
        if isinstance(cached, list):
            return set(cached)
    except Exception:
        pass
    closed: set[str] = set()
    try:
        rows = await MarketControl.find(MarketControl.enabled == True).to_list()  # noqa: E712
    except Exception:
        rows = []
    now_t = now_ist().time()
    for row in rows:
        try:
            ot = parse_hhmm(row.open_time or "")
            ct = parse_hhmm(row.close_time or "")
        except Exception:
            continue
        if (ot is not None and now_t < ot) or (ct is not None and now_t > ct):
            closed.add(row.segment_name)
    try:
        await cache_set(ck, list(closed), ttl_sec=15)
    except Exception:
        pass
    return closed
