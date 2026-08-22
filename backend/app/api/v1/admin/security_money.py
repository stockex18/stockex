"""Security money — super-admin only.

An admin lodges collateral; their users' games results then move it. See
`admin_security_service` for the direction rules and why `payable` is tracked
separately from `security`.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.core.dependencies import SuperAdmin
from app.core.exceptions import AppError
from app.schemas.common import APIResponse
from app.services import admin_security_service as svc

router = APIRouter(prefix="/security-money", tags=["admin-security-money"])


class EntryBody(BaseModel):
    admin_id: str
    amount: float
    payment_mode: str | None = None
    narration: str | None = None


class AdjustBody(BaseModel):
    admin_id: str
    amount: float  # signed
    narration: str | None = None


def _http(e: Exception) -> HTTPException:
    if isinstance(e, AppError):
        return HTTPException(status_code=e.status_code, detail=e.message or str(e))
    return HTTPException(status_code=400, detail=str(e))


@router.get("", response_model=APIResponse[list])
async def list_security(admin: SuperAdmin):
    return APIResponse(data=await svc.list_all())


@router.get("/entries", response_model=APIResponse[list])
async def list_entries(admin: SuperAdmin, admin_id: str | None = None, limit: int = 100):
    return APIResponse(data=await svc.list_entries(admin_id, min(limit, 500)))


@router.post("/deposit", response_model=APIResponse[dict])
async def deposit(body: EntryBody, admin: SuperAdmin):
    """Admin handed money over — security up, payable up."""
    try:
        row = await svc.record_deposit(
            admin, body.admin_id, body.amount,
            payment_mode=body.payment_mode, narration=body.narration or "",
        )
    except Exception as e:
        raise _http(e)
    return APIResponse(
        data={"security": str(row.security_balance), "payable": str(row.payable_balance)},
        message="Security recorded",
    )


@router.post("/withdraw", response_model=APIResponse[dict])
async def withdraw(body: EntryBody, admin: SuperAdmin):
    """Returned to the admin — security down, payable down."""
    try:
        row = await svc.record_withdraw(
            admin, body.admin_id, body.amount,
            payment_mode=body.payment_mode, narration=body.narration or "",
        )
    except Exception as e:
        raise _http(e)
    return APIResponse(
        data={"security": str(row.security_balance), "payable": str(row.payable_balance)},
        message="Security returned",
    )


@router.post("/topup", response_model=APIResponse[dict])
async def topup(body: EntryBody, admin: SuperAdmin):
    """Fund the security from the SA's own wallet — security up, payable down."""
    try:
        row = await svc.topup_from_main(
            admin, body.admin_id, body.amount, narration=body.narration or ""
        )
    except Exception as e:
        raise _http(e)
    return APIResponse(
        data={"security": str(row.security_balance), "payable": str(row.payable_balance)},
        message="Topped up from your wallet",
    )


@router.post("/adjust", response_model=APIResponse[dict])
async def adjust(body: AdjustBody, admin: SuperAdmin):
    """Signed manual correction — leaves payable alone."""
    try:
        row = await svc.adjust_manual(
            admin, body.admin_id, body.amount, narration=body.narration or ""
        )
    except Exception as e:
        raise _http(e)
    return APIResponse(
        data={"security": str(row.security_balance), "payable": str(row.payable_balance)},
        message="Adjusted",
    )
