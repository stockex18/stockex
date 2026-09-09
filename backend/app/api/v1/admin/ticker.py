"""Scrolling announcement lines — super admin only.

The strip runs across the top of the user home page. Each line is either for
every admin's users or for a chosen set of admins, so a message meant for one
pool never shows up in another's.

SUPER_ADMIN only, deliberately. An admin writing a line that their own users
read is a different feature with different blast radius; this one exists so the
platform owner can speak to the whole book, or to one pool, from one place.

    GET    /admin/ticker            list every line + the admins to choose from
    POST   /admin/ticker            create
    PUT    /admin/ticker/{id}       edit text / targeting / enabled / order
    DELETE /admin/ticker/{id}       remove

Audit-logged, because a line is visible to real users the moment it is saved.
"""

from __future__ import annotations

from beanie import PydanticObjectId
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.core.dependencies import SuperAdmin
from app.models.audit_log import AuditAction
from app.models.ticker_message import TickerMessage
from app.models.user import User, UserRole
from app.schemas.common import APIResponse
from app.services.audit_service import log_event

router = APIRouter(prefix="/ticker", tags=["admin-ticker"])


class TickerPayload(BaseModel):
    text: str = Field(min_length=1, max_length=500)
    enabled: bool = True
    target_all: bool = True
    admin_ids: list[str] = Field(default_factory=list)
    sort_order: int = 0


def _ser(m: TickerMessage) -> dict:
    return {
        "id": str(m.id),
        "text": m.text,
        "enabled": m.enabled,
        "target_all": m.target_all,
        "admin_ids": [str(x) for x in (m.admin_ids or [])],
        "sort_order": m.sort_order,
        "created_at": m.created_at.isoformat() if m.created_at else None,
    }


async def _admin_choices() -> list[dict]:
    """Every admin-tier account the super admin can target.

    Sent with the list so the picker never needs a second call, and so an
    `admin_ids` entry whose account was since deleted is visibly absent from
    the choices rather than rendering as a bare id.
    """
    rows = await User.find(
        {"role": {"$in": [UserRole.ADMIN.value, UserRole.BROKER.value]}}
    ).to_list()
    out = [
        {
            "id": str(u.id),
            "name": (u.full_name or u.email or u.user_code or str(u.id)),
            "code": u.user_code,
            "role": u.role.value,
        }
        for u in rows
    ]
    out.sort(key=lambda r: (r["role"], (r["name"] or "").lower()))
    return out


@router.get("", response_model=APIResponse[dict])
async def list_ticker(admin: SuperAdmin):
    rows = await TickerMessage.find_all().sort("+sort_order", "+created_at").to_list()
    return APIResponse(
        data={"items": [_ser(m) for m in rows], "admins": await _admin_choices()}
    )


def _ids(raw: list[str]) -> list[PydanticObjectId]:
    out: list[PydanticObjectId] = []
    for x in raw or []:
        try:
            out.append(PydanticObjectId(str(x)))
        except Exception:  # noqa: BLE001 — a bad id is dropped, not fatal
            continue
    return out


@router.post("", response_model=APIResponse[dict])
async def create_ticker(payload: TickerPayload, admin: SuperAdmin):
    m = TickerMessage(
        text=payload.text.strip(),
        enabled=payload.enabled,
        target_all=payload.target_all,
        admin_ids=_ids(payload.admin_ids),
        sort_order=payload.sort_order,
    )
    await m.insert()
    await log_event(
        action=AuditAction.CREATE,
        entity_type="TickerMessage",
        entity_id=m.id,
        actor_id=admin.id,
        new_values=_ser(m),
    )
    return APIResponse(data=_ser(m))


@router.put("/{message_id}", response_model=APIResponse[dict])
async def update_ticker(message_id: str, payload: TickerPayload, admin: SuperAdmin):
    m = await TickerMessage.get(PydanticObjectId(message_id))
    if m is None:
        raise HTTPException(status_code=404, detail="Ticker message not found")
    before = _ser(m)
    m.text = payload.text.strip()
    m.enabled = payload.enabled
    m.target_all = payload.target_all
    m.admin_ids = _ids(payload.admin_ids)
    m.sort_order = payload.sort_order
    await m.save()
    await log_event(
        action=AuditAction.UPDATE,
        entity_type="TickerMessage",
        entity_id=m.id,
        actor_id=admin.id,
        old_values=before,
        new_values=_ser(m),
    )
    return APIResponse(data=_ser(m))


@router.delete("/{message_id}", response_model=APIResponse[dict])
async def delete_ticker(message_id: str, admin: SuperAdmin):
    m = await TickerMessage.get(PydanticObjectId(message_id))
    if m is None:
        raise HTTPException(status_code=404, detail="Ticker message not found")
    before = _ser(m)
    await m.delete()
    await log_event(
        action=AuditAction.DELETE,
        entity_type="TickerMessage",
        entity_id=PydanticObjectId(message_id),
        actor_id=admin.id,
        old_values=before,
    )
    return APIResponse(data={"deleted": True})
