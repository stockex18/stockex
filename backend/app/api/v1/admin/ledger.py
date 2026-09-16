"""Admin master ledger — every user's wallet transactions + manual entry."""

from __future__ import annotations

import logging
from typing import Any

from beanie import PydanticObjectId
from fastapi import APIRouter, Depends, Query

from app.core.dependencies import (
    CurrentAdmin,
    assert_user_in_scope,
    require_perm,
    scoped_user_ids,
    sees_every_book,
)
from app.models.audit_log import AuditAction
from app.models.transaction import TransactionType, WalletTransaction
from app.models.user import User
from app.schemas.common import APIResponse
from app.services import wallet_service
from app.services.audit_service import log_event

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/ledger", tags=["admin-ledger"])


@router.get("", response_model=APIResponse[dict])
async def list_all(
    admin: CurrentAdmin,
    user_id: str | None = None,
    transaction_type: str | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=1000),
    _: None = Depends(require_perm("ledger", "read")),
):
    q: dict[str, Any] = {}
    if user_id:
        # Sub-admin: refuse user_id outside their scope. The super-admin is
        # unrestricted — their own pool clause is "clients with no admin", so
        # the scope check 403'd them off every real client's ledger.
        if not sees_every_book(admin):
            await assert_user_in_scope(admin, user_id)
        q["user_id"] = PydanticObjectId(user_id)
    elif not sees_every_book(admin):
        # Same reason the Orders and Positions monitors opt out (70e80db):
        # every client belongs to an admin, so the super-admin's scope
        # resolved to nobody and the whole ledger came back empty.
        scope = await scoped_user_ids(admin)
        if scope is not None:
            if not scope:
                return APIResponse(
                    data={
                        "items": [],
                        "meta": {
                            "page": page,
                            "page_size": page_size,
                            "total": 0,
                            "total_pages": 0,
                        },
                    }
                )
            q["user_id"] = {"$in": scope}
    if transaction_type:
        q["transaction_type"] = transaction_type
    total = await WalletTransaction.find(q).count()
    rows = (
        await WalletTransaction.find(q)
        .sort("-created_at")
        .skip((page - 1) * page_size)
        .limit(page_size)
        .to_list()
    )

    user_ids = list({r.user_id for r in rows})
    users = await User.find({"_id": {"$in": user_ids}}).to_list() if user_ids else []
    umap = {str(u.id): u.user_code for u in users}

    return APIResponse(
        data={
            "items": [
                {
                    "id": str(r.id),
                    "user_id": str(r.user_id),
                    "user_code": umap.get(str(r.user_id)),
                    "transaction_type": r.transaction_type.value,
                    "amount": str(r.amount),
                    "balance_before": str(r.balance_before),
                    "balance_after": str(r.balance_after),
                    "narration": r.narration,
                    "status": r.status.value,
                    "reference_type": r.reference_type,
                    "reference_id": r.reference_id,
                    "created_at": r.created_at,
                }
                for r in rows
            ],
            "meta": {
                "page": page,
                "page_size": page_size,
                "total": total,
                "total_pages": (total + page_size - 1) // page_size,
            },
        }
    )


@router.post("/manual-entry", response_model=APIResponse[dict])
async def manual_entry(
    payload: dict,
    admin: CurrentAdmin,
    _: None = Depends(require_perm("ledger", "write")),
):
    user_id = payload["user_id"]
    await assert_user_in_scope(admin, user_id)
    amount = float(payload["amount"])
    txn_type = payload.get("transaction_type", "ADJUSTMENT")
    narration = payload["narration"]

    # Admin-float cap: a manual CREDIT (amount > 0) draws down the owning-admin's
    # float (raises + blocks if insufficient); a manual DEBIT (amount < 0)
    # replenishes it. All a no-op unless ADMIN_FLOAT_ENABLED / SA-owned user.
    from app.services import admin_fund_service

    if amount > 0:
        await admin_fund_service.debit_admin_float_for_user(
            user_id, amount, reference_type="ADJUSTMENT", actor_id=admin.id,
            narration=f"Manual credit — float debit ({narration})",
        )
    try:
        txn = await wallet_service.adjust(
            user_id,
            amount,
            transaction_type=TransactionType(txn_type),
            narration=narration,
            actor_id=admin.id,
        )
    except Exception:
        if amount > 0:  # roll the float debit back
            await admin_fund_service.credit_admin_float_for_user(
                user_id, amount, reference_type="ADJUSTMENT", actor_id=admin.id,
                narration="Manual credit rollback — float returned",
            )
        raise
    if amount < 0:  # manual debit removed user funds → return float, best-effort
        try:
            await admin_fund_service.credit_admin_float_for_user(
                user_id, -amount, reference_type="ADJUSTMENT", actor_id=admin.id,
                narration=f"Manual debit — float returned ({narration})",
            )
        except Exception:  # noqa: BLE001
            logger.exception("manual_debit_float_replenish_failed user=%s", user_id)
    await log_event(
        action=AuditAction.WALLET_ADJUST,
        entity_type="WalletTransaction",
        entity_id=str(txn.id),
        actor_id=admin.id,
        target_user_id=user_id,
        metadata={"amount": str(amount), "type": txn_type},
    )
    return APIResponse(data={"transaction_id": str(txn.id)})
