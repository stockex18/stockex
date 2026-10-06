"""Upstox setup for Check Trades — credentials, connect, disconnect.

Super-admin only, like Check Trades itself. These are the keys to an outside
brokerage account; an admin who can read them can read the operator's market
data allowance, and the secret is never returned by any route here.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import HTMLResponse

from app.core.dependencies import SuperAdmin
from app.models.audit_log import AuditAction
from app.schemas.common import APIResponse
from app.services import upstox_service
from app.services.audit_service import log_event

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/upstox", tags=["admin-upstox"])


@router.get("/settings", response_model=APIResponse[dict])
async def get_upstox_settings(admin: SuperAdmin):
    """Everything the setup card renders. `has_secret` instead of the secret:
    a saved secret is something to confirm, not something to read back."""
    return APIResponse(data=await upstox_service.status())


@router.put("/settings", response_model=APIResponse[dict])
async def set_upstox_settings(payload: dict, admin: SuperAdmin):
    """Save the API key / secret / redirect URL. An omitted field is left
    alone — the UI never sends the secret back, so a blanket write would
    erase it on every other save."""
    row = await upstox_service.save_credentials(
        api_key=payload.get("api_key"),
        api_secret=payload.get("api_secret"),
        redirect_url=payload.get("redirect_url"),
        enabled=payload.get("enabled"),
    )
    await log_event(
        action=AuditAction.SETTING_CHANGE,
        entity_type="UpstoxSettings",
        entity_id=str(row.id),
        actor_id=admin.id,
        # Deliberately no values: this row's whole content is a credential.
        new_values={"fields": sorted(k for k in payload if k != "api_secret")},
    )
    return APIResponse(data=await upstox_service.status())


@router.get("/login-url", response_model=APIResponse[dict])
async def get_login_url(admin: SuperAdmin):
    """The Upstox page to open to authorise the app."""
    try:
        return APIResponse(data={"url": await upstox_service.login_url()})
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/disconnect", response_model=APIResponse[dict])
async def disconnect_upstox(admin: SuperAdmin):
    await upstox_service.disconnect()
    await log_event(
        action=AuditAction.SETTING_CHANGE,
        entity_type="UpstoxSettings",
        entity_id="disconnect",
        actor_id=admin.id,
    )
    return APIResponse(data=await upstox_service.status())


@router.get("/callback", response_class=HTMLResponse)
async def upstox_callback(
    code: str | None = Query(default=None),
    state: str | None = Query(default=None),
    error: str | None = Query(default=None),
):
    """Where Upstox sends the browser back after the operator authorises.

    PUBLIC by necessity — it is opened by a redirect from Upstox, which
    carries no session of ours. That is safe because the code alone is
    worthless: the exchange needs the api_secret, which never leaves this
    server, and a code is single-use and short-lived.

    Returns a small page rather than JSON because a human is looking at it.
    """
    if error or not code:
        detail = error or "Upstox returned no authorisation code."
        return HTMLResponse(_page("Upstox connect failed", detail, ok=False), status_code=400)
    try:
        await upstox_service.exchange_code(code)
    except Exception as e:  # noqa: BLE001 — the message is the whole point here
        return HTMLResponse(_page("Upstox connect failed", str(e), ok=False), status_code=400)
    return HTMLResponse(
        _page("Upstox connected", "You can close this tab and go back to Check Trades.", ok=True)
    )


def _page(title: str, detail: str, *, ok: bool) -> str:
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
