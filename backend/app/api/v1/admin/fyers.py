"""Fyers order price check — credentials, connect, and the check results.

Super-admin only. The secret is never returned by any route here.
"""

from __future__ import annotations

import html
import logging
import re
from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import HTMLResponse

from app.core.dependencies import SuperAdmin
from app.models.audit_log import AuditAction
from app.models.fyers_price_check import FyersPriceCheck, PriceCheckStatus
from app.schemas.common import APIResponse
from app.services import fyers_price_check, fyers_service, fyers_symbol_map
from app.services.audit_service import log_event
from app.utils.background import fire_and_forget
from app.utils.time_utils import now_ist

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/fyers", tags=["admin-fyers"])


@router.get("/settings", response_model=APIResponse[dict])
async def get_fyers_settings(admin: SuperAdmin):
    return APIResponse(data=await fyers_service.status())


@router.put("/settings", response_model=APIResponse[dict])
async def set_fyers_settings(payload: dict, admin: SuperAdmin):
    """Save the App ID / secret / on-off switch. An omitted field is left
    alone — the UI never sends the secret back."""
    row = await fyers_service.save_credentials(
        app_id=payload.get("app_id"),
        secret=payload.get("secret"),
        redirect_url=payload.get("redirect_url"),
        enabled=payload.get("enabled"),
    )
    await log_event(
        action=AuditAction.SETTING_CHANGE,
        entity_type="FyersSettings",
        entity_id=str(row.id),
        actor_id=admin.id,
        new_values={"fields": sorted(k for k in payload if k != "secret")},
    )
    return APIResponse(data=await fyers_service.status())


@router.get("/login-url", response_model=APIResponse[dict])
async def get_login_url(admin: SuperAdmin):
    try:
        return APIResponse(data={"url": await fyers_service.login_url()})
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/disconnect", response_model=APIResponse[dict])
async def disconnect_fyers(admin: SuperAdmin):
    await fyers_service.disconnect()
    await log_event(
        action=AuditAction.SETTING_CHANGE,
        entity_type="FyersSettings",
        entity_id="disconnect",
        actor_id=admin.id,
    )
    return APIResponse(data=await fyers_service.status())


@router.get("/callback", response_class=HTMLResponse)
async def fyers_callback(
    auth_code: str | None = Query(default=None),
    s: str | None = Query(default=None),
    message: str | None = Query(default=None),
    state: str | None = Query(default=None),
):
    """Where Fyers sends the browser back after the operator logs in.

    PUBLIC by necessity — it is opened by a redirect from Fyers, which
    carries no session of ours. Safe because the auth code alone is
    worthless: the exchange needs the app secret, which never leaves this
    server, and a code is single-use and short-lived.
    """
    if not auth_code or (s and s.lower() != "ok"):
        detail = message or "Fyers returned no auth code."
        return HTMLResponse(_page("Fyers connect failed", detail, ok=False), status_code=400)
    try:
        await fyers_service.exchange_code(auth_code)
    except Exception as e:  # noqa: BLE001 — the message is the whole point here
        return HTMLResponse(_page("Fyers connect failed", str(e), ok=False), status_code=400)
    # Build today's symbol list now rather than on the first order.
    fire_and_forget(fyers_symbol_map.refresh(), label="fyers_symbol_map_refresh")
    return HTMLResponse(
        _page(
            "Fyers connected",
            "You can close this tab and go back to Fyers Connect in the admin panel.",
            ok=True,
        )
    )


def _ist_day_start(d: str) -> datetime:
    """'YYYY-MM-DD' (IST) → that day's 00:00 IST as an aware datetime."""
    tz = now_ist().tzinfo
    return datetime.strptime(d, "%Y-%m-%d").replace(tzinfo=tz)


@router.get("/checks", response_model=APIResponse[dict])
async def list_checks(
    admin: SuperAdmin,
    status: str | None = Query(default=None),
    date_from: str | None = Query(default=None),
    date_to: str | None = Query(default=None),
    q: str | None = Query(default=None, description="symbol, user code or order number"),
    limit: int = Query(default=100, ge=1, le=500),
    skip: int = Query(default=0, ge=0),
):
    """The check rows, newest first, plus counts per status for the range."""
    today = now_ist().date().isoformat()
    try:
        start = _ist_day_start(date_from or today)
        end = _ist_day_start(date_to or date_from or today) + timedelta(days=1)
    except ValueError as e:
        raise HTTPException(status_code=400, detail="Dates must be YYYY-MM-DD") from e

    base: dict[str, Any] = {"placed_at": {"$gte": start, "$lt": end}}
    if q and q.strip():
        term = q.strip()
        rx = {"$regex": re.escape(term), "$options": "i"}
        base["$or"] = [{"symbol": rx}, {"user_code": rx}, {"order_number": rx}, {"user_name": rx}]

    counts = {s.value: 0 for s in PriceCheckStatus}
    agg = FyersPriceCheck.get_motor_collection().aggregate(
        [{"$match": base}, {"$group": {"_id": "$status", "n": {"$sum": 1}}}]
    )
    async for g in agg:
        counts[str(g["_id"])] = int(g["n"])

    filt = dict(base)
    if status:
        filt["status"] = status.upper()
    rows = (
        await FyersPriceCheck.find(filt).sort("-placed_at").skip(skip).limit(limit).to_list()
    )
    return APIResponse(
        data={
            "range": {"from": date_from or today, "to": date_to or date_from or today},
            "counts": counts,
            "rows": [fyers_price_check.serialize(r) for r in rows],
            "tolerance_ticks": fyers_price_check.MISMATCH_TOLERANCE_TICKS,
        }
    )


@router.get("/mismatch-count", response_model=APIResponse[dict])
async def mismatch_count(
    admin: SuperAdmin,
    since: datetime | None = Query(default=None, description="count mismatches after this time"),
):
    """For the menu badge: how many mismatches since the admin last looked
    (default: today, IST)."""
    if since is None:
        since = _ist_day_start(now_ist().date().isoformat())
    n = await FyersPriceCheck.find(
        {"status": PriceCheckStatus.MISMATCH.value, "placed_at": {"$gt": since}}
    ).count()
    return APIResponse(data={"count": n})


def _page(title: str, detail: str, *, ok: bool) -> str:
    # `detail` can come straight from the public callback's query string.
    title, detail = html.escape(title), html.escape(detail)
    colour = "#10b981" if ok else "#ef4444"
    return (
        "<!doctype html><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        f"<title>{title}</title>"
        "<body style=\"margin:0;display:grid;place-items:center;min-height:100vh;"
        "background:#0a0a0a;color:#e5e5e5;font:16px/1.5 system-ui,sans-serif\">"
        "<div style='max-width:32rem;padding:2rem;text-align:center'>"
        f"<h1 style='margin:0 0 .5rem;font-size:1.25rem;color:{colour}'>{title}</h1>"
        f"<p style='margin:0;color:#a3a3a3;word-break:break-word'>{detail}</p>"
        "</div></body>"
    )
