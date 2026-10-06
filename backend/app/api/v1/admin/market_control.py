"""Super-admin MARKET CONTROL — per-segment trading hours.

The SA opens/closes any segment at will (including 24×7 crypto / 24×5 forex).
When a segment is `enabled`, trading is allowed ONLY between open_time and
close_time IST; outside that the order validator rejects new opening orders
(closing / square-off is always allowed). Keyed by the admin-row segment code.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app.core.dependencies import SuperAdmin, require_perm
from app.core.redis_client import cache_delete_pattern
from app.models.market_control import MarketControl
from app.models.netting import SEGMENT_CODES
from app.schemas.common import APIResponse

router = APIRouter(prefix="/market-control", tags=["admin-market-control"])

SEGMENT_LABELS: dict[str, str] = {
    "NSE_EQ": "NSE Equity", "NSE_STK_FUT": "Stock Future", "NSE_IDX_FUT": "Index Future",
    "NSE_STK_OPT": "Stock Option", "NSE_IDX_OPT": "Index Option",
    "BSE_EQ": "BSE Equity", "BSE_FUT": "BSE Future", "BSE_OPT": "BSE Option",
    "MCX_FUT": "MCX Future", "MCX_OPT": "MCX Option",
    "FOREX": "Forex", "STOCKS": "Stocks", "INDICES": "Indices",
    "COMMODITIES": "Commodities", "CRYPTO": "Crypto", "CRYPTO_OPT": "Crypto Option",
}


# Option segments default to closing 30s BEFORE their own bell so option
# trading auto-stops just ahead of the underlying close (avoids last-second
# entries). Only the DEFAULT pre-fill — a saved row wins as usual.
_OPTION_SEGMENTS = {"NSE_STK_OPT", "NSE_IDX_OPT", "BSE_OPT", "MCX_OPT", "CRYPTO_OPT"}

# The pre-fill a row shows before it has ever been saved, per segment.
#
# It used to be 09:15 → 15:30 for everything, which is only true of NSE and
# BSE. Enabling MCX without first retyping both fields would have set a
# market that runs 09:00–23:30 to 09:15–15:30 — six hours of session gone,
# from a toggle that looked like it was only turning the window ON. The 24×7
# and 24×5 books had the same trap in reverse: a day's worth of Crypto or
# Forex trading silently cut to the Indian equity bell.
#
# These are the real session hours, so the toggle alone is now correct and
# the operator only types a time when they actually want to CHANGE one.
_SESSION_DEFAULTS: dict[str, tuple[str, str]] = {
    "MCX_FUT": ("09:00", "23:30"),
    "MCX_OPT": ("09:00", "23:30"),
    "CRYPTO": ("00:00", "23:59:59"),
    "CRYPTO_OPT": ("00:00", "23:59:59"),
    "FOREX": ("00:00", "23:59:59"),
}
_DEFAULT_SESSION = ("09:15", "15:30")


def _row_out(code: str, r: MarketControl | None) -> dict:
    default_open, session_close = _SESSION_DEFAULTS.get(code, _DEFAULT_SESSION)
    default_close = session_close
    if code in _OPTION_SEGMENTS:
        # 30s before this segment's OWN close, not before the equity bell.
        h, m, *_ = (int(x) for x in session_close.split(":"))
        total = h * 3600 + m * 60 - 30
        default_close = "%02d:%02d:%02d" % (total // 3600, (total % 3600) // 60, total % 60)
    return {
        "segment": code,
        "label": SEGMENT_LABELS.get(code, code),
        "enabled": bool(r.enabled) if r else False,
        "open_time": (r.open_time if r else default_open) or default_open,
        "close_time": (r.close_time if r else default_close) or default_close,
    }


@router.get("", response_model=APIResponse[list])
async def list_market_control(
    admin: SuperAdmin,
    _: None = Depends(require_perm("segment_settings", "read")),
):
    """Every segment's market-control row (defaults when unset)."""
    rows = {r.segment_name: r for r in await MarketControl.find().to_list()}
    return APIResponse(data=[_row_out(code, rows.get(code)) for code in SEGMENT_CODES])


@router.put("/{segment}", response_model=APIResponse[dict])
async def set_market_control(
    segment: str,
    payload: dict,
    admin: SuperAdmin,
    _: None = Depends(require_perm("segment_settings", "write")),
):
    """Set a segment's trading window. Payload: {enabled, open_time, close_time}."""
    if segment not in SEGMENT_CODES:
        raise HTTPException(status_code=400, detail=f"Unknown segment {segment}")
    row = await MarketControl.find_one(MarketControl.segment_name == segment)
    if row is None:
        row = MarketControl(segment_name=segment)
    if "enabled" in payload:
        row.enabled = bool(payload["enabled"])
    # Keep up to HH:MM:SS (8 chars) so the super-admin can set seconds, not just
    # HH:MM. parse_hhmm tolerates both when enforcing the window.
    if payload.get("open_time"):
        row.open_time = str(payload["open_time"]).strip()[:8]
    if payload.get("close_time"):
        row.close_time = str(payload["close_time"]).strip()[:8]
    await row.save()
    # Drop the enforcement cache so the change applies on the next order.
    try:
        await cache_delete_pattern("mktctl:*")
    except Exception:
        pass
    return APIResponse(data=_row_out(segment, row))
