"""Inter-admin fund flow endpoints.

Direct transfers (parent → child add/deduct) + the request→approve chain.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.core.dependencies import CurrentAdmin
from app.core.exceptions import (
    InsufficientFundsError,
    NotFoundError,
    ValidationFailedError,
)
from app.schemas.common import APIResponse
from app.services import admin_fund_service

router = APIRouter(prefix="/fund", tags=["admin-fund"])


class AmountBody(BaseModel):
    amount: float
    description: str | None = None
    payment_mode: str | None = None  # Cash/Cheque/Banking/UPI/Others — used by BOTH add and deduct
    source: str | None = None  # SA only: "MAIN" or "KUBER" — which wallet pays


class FundRequestBody(BaseModel):
    amount: float
    reason: str | None = None


class PeerTransferBody(BaseModel):
    target: str  # recipient admin's user_code (ADM…/BRK…) or id
    amount: float
    description: str | None = None


class ResolveBody(BaseModel):
    approve: bool
    remarks: str | None = None


def _http(e: Exception) -> HTTPException:
    if isinstance(e, NotFoundError):
        return HTTPException(status_code=404, detail=getattr(e, "message", str(e)))
    if isinstance(e, (ValidationFailedError, InsufficientFundsError)):
        return HTTPException(status_code=400, detail=getattr(e, "message", str(e)))
    return HTTPException(status_code=400, detail=str(e))


@router.post("/members/{member_id}/add", response_model=APIResponse[dict])
async def add_funds(member_id: str, body: AmountBody, admin: CurrentAdmin):
    try:
        data = await admin_fund_service.add_funds(
            admin, member_id, body.amount, body.description or "",
            payment_mode=body.payment_mode, source=body.source,
        )
    except Exception as e:
        raise _http(e)
    return APIResponse(data=data, message="Funds added")


@router.get("/coin-summary", response_model=APIResponse[dict])
async def coin_summary(admin: CurrentAdmin):
    """Total coins this admin generated + per-admin/per-mode breakdown."""
    try:
        data = await admin_fund_service.coin_generation_summary(admin)
    except Exception as e:
        raise _http(e)
    return APIResponse(data=data)


@router.post("/members/{member_id}/deduct", response_model=APIResponse[dict])
async def deduct_funds(member_id: str, body: AmountBody, admin: CurrentAdmin):
    try:
        data = await admin_fund_service.deduct_funds(
            admin, member_id, body.amount, body.description or "", payment_mode=body.payment_mode
        )
    except Exception as e:
        raise _http(e)
    return APIResponse(data=data, message="Funds deducted")


@router.post("/transfer", response_model=APIResponse[dict])
async def transfer_to_admin(body: PeerTransferBody, admin: CurrentAdmin):
    """Peer transfer — send my own float to ANOTHER admin by their ID/code."""
    try:
        data = await admin_fund_service.transfer_to_admin(
            admin, body.target, body.amount, body.description or ""
        )
    except Exception as e:
        raise _http(e)
    return APIResponse(data=data, message=f"Sent 🪙{body.amount:,.2f} to {data.get('to_code')}")


@router.post("/requests", response_model=APIResponse[dict])
async def create_request(body: FundRequestBody, admin: CurrentAdmin):
    try:
        req = await admin_fund_service.create_fund_request(admin, body.amount, body.reason or "")
    except Exception as e:
        raise _http(e)
    return APIResponse(data={"id": str(req.id)}, message="Fund request submitted")


@router.get("/requests/incoming", response_model=APIResponse[list])
async def incoming(admin: CurrentAdmin, status: str = "PENDING"):
    return APIResponse(data=await admin_fund_service.list_incoming(admin, status))


@router.get("/requests/mine", response_model=APIResponse[list])
async def mine(admin: CurrentAdmin):
    return APIResponse(data=await admin_fund_service.list_mine(admin))


@router.put("/requests/{req_id}", response_model=APIResponse[dict])
async def resolve(req_id: str, body: ResolveBody, admin: CurrentAdmin):
    try:
        if body.approve:
            req = await admin_fund_service.approve_fund_request(admin, req_id)
        else:
            req = await admin_fund_service.reject_fund_request(admin, req_id, body.remarks)
    except Exception as e:
        raise _http(e)
    return APIResponse(
        data={"id": str(req.id), "status": req.status.value if hasattr(req.status, "value") else str(req.status)},
        message="Request resolved",
    )
