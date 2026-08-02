"""Super-admin "Ban Security" panel — ban a stock (globally or for one admin's
users). Banned = no new/adding position (close-only) + open-position P&L frozen
at ban-time LTP. SUPER-ADMIN ONLY."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.core.dependencies import CurrentAdmin
from app.models.banned_security import GLOBAL_SCOPE
from app.models.user import User, UserRole
from app.schemas.common import APIResponse
from app.services import banned_security_service, instrument_service

router = APIRouter(tags=["admin-ban-security"])


def _require_super_admin(admin) -> None:
    if getattr(admin, "role", None) != UserRole.SUPER_ADMIN:
        raise HTTPException(status_code=403, detail="Super-admin only")


class BanReq(BaseModel):
    token: str
    admin_id: str | None = None  # None → GLOBAL (all users)


@router.get("/ban-security", response_model=APIResponse[list])
async def list_bans(admin: CurrentAdmin):
    _require_super_admin(admin)
    rows = await banned_security_service.list_bans()
    # Resolve admin-scope names for display.
    admin_ids = {r.scope for r in rows if r.scope != GLOBAL_SCOPE}
    names: dict[str, str] = {}
    for aid in admin_ids:
        try:
            u = await User.get(aid)
            if u:
                names[aid] = u.full_name or u.user_code
        except Exception:  # noqa: BLE001
            pass
    out = [
        {
            "id": str(r.id),
            "token": r.token,
            "symbol": r.symbol,
            "scope": r.scope,
            "scope_label": "All users" if r.scope == GLOBAL_SCOPE else names.get(r.scope, r.scope),
            "freeze_price": str(r.freeze_price),
            "banned_at": r.banned_at,
        }
        for r in rows
    ]
    return APIResponse(data=out)


@router.post("/ban-security", response_model=APIResponse[dict])
async def ban(req: BanReq, admin: CurrentAdmin):
    _require_super_admin(admin)
    try:
        inst = await instrument_service.get_by_token(req.token)
    except Exception:
        raise HTTPException(status_code=404, detail="Instrument not found")
    scope = GLOBAL_SCOPE
    if req.admin_id:
        target = await User.get(req.admin_id)
        if target is None or target.role != UserRole.ADMIN:
            raise HTTPException(status_code=400, detail="Invalid admin for scope")
        scope = str(req.admin_id)
    row = await banned_security_service.ban(req.token, inst.symbol, scope, admin.id)
    return APIResponse(
        data={"id": str(row.id), "symbol": row.symbol, "scope": row.scope,
              "freeze_price": str(row.freeze_price)},
        message=f"{inst.symbol} banned",
    )


@router.delete("/ban-security/{ban_id}", response_model=APIResponse[dict])
async def unban(ban_id: str, admin: CurrentAdmin):
    _require_super_admin(admin)
    ok = await banned_security_service.unban(ban_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Ban not found")
    return APIResponse(data={"removed": ban_id}, message="Unbanned")
