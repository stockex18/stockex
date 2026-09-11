"""Admin "Delivery & Pledge" section — delivery orders, pledged holdings, and
each user's pledge position against their cash. Read-only; the switch and the
haircut live in platform settings (`delivery_pledge.*`, super-admin only)."""

from __future__ import annotations

from typing import Any

from beanie import PydanticObjectId
from bson import Decimal128
from fastapi import APIRouter, Depends, Query

from app.api.v1.admin._owner import build_owner_map, owner_fields, pool_scope_for_admin
from app.core.dependencies import (
    CurrentAdmin,
    assert_user_in_scope,
    require_perm,
    scoped_user_ids,
    sees_every_book,
)
from app.models.order import Order
from app.models.position import Position
from app.schemas.common import APIResponse
from app.services import market_data_service, pledge_service, segment_wallet_service, wallet_kinds
from app.utils.decimal_utils import quantize_money, to_decimal

router = APIRouter(prefix="/pledge", tags=["admin-pledge"])

_NOT_DEMO = {"is_demo": {"$ne": True}}


async def _scope(admin: Any, user_id: str | None, admin_id: str | None) -> dict | None:
    """Mongo user filter for this caller — the same three branches the Orders
    and Positions monitors use. None = nothing visible (render empty)."""
    if user_id:
        await assert_user_in_scope(admin, user_id)
        return {"user_id": PydanticObjectId(user_id)}
    if admin_id:
        pool = await pool_scope_for_admin(admin, admin_id)
        return {"user_id": {"$in": pool}} if pool else None
    if sees_every_book(admin):
        return {}
    scope = await scoped_user_ids(admin)
    if scope is None:
        return {}
    return {"user_id": {"$in": scope}} if scope else None


@router.get("/orders", response_model=APIResponse[list])
async def delivery_orders(
    admin: CurrentAdmin,
    user_id: str | None = None,
    admin_id: str | None = None,
    side: str | None = None,
    pledged_only: bool = False,
    limit: int = Query(default=300, ge=1, le=1000),
    _: None = Depends(require_perm("trading_view", "read")),
):
    """NSE / BSE equity DELIVERY (CNC) orders, newest first."""
    f = await _scope(admin, user_id, admin_id)
    if f is None:
        return APIResponse(data=[])
    q: dict[str, Any] = {
        **f,
        **_NOT_DEMO,
        "product_type": "CNC",
        "instrument.segment": {"$in": sorted(pledge_service.EQUITY_SEGMENTS)},
    }
    if side:
        q["action"] = side.upper()
    if pledged_only:
        q["is_pledge"] = True
    rows = await Order.find(q).sort("-created_at").limit(limit).to_list()
    owners = await build_owner_map(list({r.user_id for r in rows}))
    out = []
    for r in rows:
        px = to_decimal(r.average_price) if to_decimal(r.average_price) > 0 else to_decimal(r.price)
        out.append(
            {
                "id": str(r.id),
                "order_number": r.order_number,
                "user_id": str(r.user_id),
                **owner_fields(owners.get(str(r.user_id))),
                "symbol": r.instrument.symbol,
                "exchange": r.instrument.exchange,
                "action": r.action.value,
                "order_type": r.order_type.value,
                "quantity": r.quantity,
                "price": str(quantize_money(px)),
                "value": str(quantize_money(px * to_decimal(r.quantity))),
                "status": r.status.value,
                "is_pledge": bool(getattr(r, "is_pledge", False)),
                "rejection_reason": r.rejection_reason,
                "created_at": r.created_at,
                "executed_at": r.executed_at,
            }
        )
    return APIResponse(data=out)


@router.get("/holdings", response_model=APIResponse[list])
async def pledged_holdings(
    admin: CurrentAdmin,
    user_id: str | None = None,
    admin_id: str | None = None,
    _: None = Depends(require_perm("trading_view", "read")),
):
    """Open pledged delivery positions and the margin each one backs."""
    f = await _scope(admin, user_id, admin_id)
    if f is None:
        return APIResponse(data=[])
    rows = await Position.find({**f, **_NOT_DEMO, "status": "OPEN", "is_pledge": True}).to_list()
    owners = await build_owner_map(list({r.user_id for r in rows}))
    haircut = await pledge_service.haircut_pct()
    out = []
    for r in rows:
        qty = abs(to_decimal(r.quantity or 0))
        avg = to_decimal(r.avg_price)
        try:
            ltp = to_decimal(await market_data_service.get_display_ltp(r.instrument.token))
        except Exception:  # noqa: BLE001
            ltp = to_decimal(r.ltp)
        if ltp <= 0:
            ltp = to_decimal(r.ltp) if to_decimal(r.ltp) > 0 else avg
        value = qty * ltp
        out.append(
            {
                "id": str(r.id),
                "user_id": str(r.user_id),
                **owner_fields(owners.get(str(r.user_id))),
                "symbol": r.instrument.symbol,
                "exchange": r.instrument.exchange,
                "quantity": float(qty),
                "avg_price": str(quantize_money(avg)),
                "ltp": str(quantize_money(ltp)),
                "invested": str(quantize_money(qty * avg)),
                "current_value": str(quantize_money(value)),
                "pledge_margin": str(quantize_money(value * haircut / 100)),
                "pnl": str(quantize_money((ltp - avg) * qty)),
                "opened_at": r.opened_at,
            }
        )
    return APIResponse(data=out)


@router.get("/summary", response_model=APIResponse[list])
async def pledge_summary(
    admin: CurrentAdmin,
    user_id: str | None = None,
    admin_id: str | None = None,
    _: None = Depends(require_perm("trading_view", "read")),
):
    """One line per user with pledge activity: cash, holdings, pledge limit /
    used / free, and how close the F&O loss is to the cash stop-out."""
    f = await _scope(admin, user_id, admin_id)
    if f is None:
        return APIResponse(data=[])
    uids = await Position.get_motor_collection().distinct(
        "user_id",
        {
            **f,
            **_NOT_DEMO,
            "status": "OPEN",
            "$or": [{"is_pledge": True}, {"pledge_margin": {"$gt": Decimal128("0")}}],
        },
    )
    owners = await build_owner_map(uids)
    out = []
    for uid in uids:
        st = await pledge_service.state(uid)
        w = await segment_wallet_service.get_or_create(uid, wallet_kinds.NSE_BSE)
        # Cash = what the wallet holds minus what was paid for the shares —
        # the same denominator the stop-out uses.
        cash = (
            to_decimal(w.available_balance)
            + to_decimal(w.used_margin)
            + to_decimal(w.credit_limit)
            - st.delivery_locked
        )
        fno_pnl = await segment_wallet_service.segment_float_pnl(uid, wallet_kinds.NSE_BSE)
        loss = max(to_decimal(0), -fno_pnl) + st.deficit
        loss_pct = float(loss / cash * 100) if cash > 0 else (100.0 if loss > 0 else 0.0)
        out.append(
            {
                "user_id": str(uid),
                **owner_fields(owners.get(str(uid))),
                "cash": str(quantize_money(cash)),
                "holdings_value": str(st.holdings_value),
                "pledge_limit": str(st.limit),
                "pledge_used": str(st.used),
                "pledge_available": str(quantize_money(st.available)),
                "pledge_deficit": str(quantize_money(st.deficit)),
                "fno_pnl": str(quantize_money(fno_pnl)),
                "loss_pct": round(loss_pct, 2),
            }
        )
    out.sort(key=lambda r: r["loss_pct"], reverse=True)
    return APIResponse(data=out)
