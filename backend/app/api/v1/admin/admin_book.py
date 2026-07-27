"""Super-admin ADMIN-BOOK earnings report — drill-down of the per-trade SA share.

Reads the `admin_book_entries` ledger (written by `admin_book_service`) and rolls
it up three ways so the SA sees exactly which admin, which user, and which trade
their PnL-share + brokerage came from:

  • GET /admin/admin-book/summary                      → per-admin totals
  • GET /admin/admin-book/admin/{admin_id}/users       → per-user totals (one admin)
  • GET /admin/admin-book/admin/{admin_id}/user/{uid}/trades → per-trade rows

All money is returned as strings (Decimal128). Optional `from`/`to` (IST
YYYY-MM-DD) filter by booking date; default = all time.
"""

from __future__ import annotations

from datetime import datetime, time, timedelta

from fastapi import APIRouter

from app.core.dependencies import SuperAdmin
from app.models.admin_book_entry import AdminBookEntry
from app.models.user import User
from app.schemas.common import APIResponse
from app.utils.time_utils import IST, to_utc

router = APIRouter(prefix="/admin-book", tags=["admin-book"])


def _date_match(frm: str | None, to: str | None) -> dict:
    """Build a created_at $match from IST day strings (inclusive of `to`)."""
    cond: dict = {}
    try:
        if frm:
            y, m, d = (int(x) for x in frm.split("-"))
            cond["$gte"] = to_utc(datetime.combine(datetime(y, m, d).date(), time.min, tzinfo=IST))
        if to:
            y, m, d = (int(x) for x in to.split("-"))
            end = datetime.combine(datetime(y, m, d).date(), time.min, tzinfo=IST) + timedelta(days=1)
            cond["$lt"] = to_utc(end)
    except Exception:
        return {}
    return {"created_at": cond} if cond else {}


@router.get("/report", response_model=APIResponse[list])
async def per_admin_summary(
    admin: SuperAdmin, from_: str | None = None, to: str | None = None
):
    """Per-admin totals of the SA's booked earnings (PnL share + brokerage
    share), newest-value-first. `from_`/`to` are IST YYYY-MM-DD (optional)."""
    coll = AdminBookEntry.get_motor_collection()
    match = _date_match(from_, to)
    pipeline: list[dict] = []
    if match:
        pipeline.append({"$match": match})
    pipeline += [
        {
            "$group": {
                "_id": "$admin_id",
                "sa_pnl": {"$sum": "$sa_pnl_share_inr"},
                "sa_bkg": {"$sum": "$sa_bkg_share_inr"},
                "sa_net": {"$sum": "$sa_net_inr"},
                "house_pnl": {"$sum": "$house_pnl_inr"},
                "brokerage": {"$sum": "$brokerage_inr"},
                "admin_net": {"$sum": "$admin_net_inr"},
                "trades": {"$sum": 1},
                "users": {"$addToSet": "$user_id"},
            }
        },
        {"$sort": {"sa_net": -1}},
    ]
    rows = await coll.aggregate(pipeline).to_list(length=1000)
    admins = {a.id: a for a in await User.find({"_id": {"$in": [r["_id"] for r in rows]}}).to_list()}
    out = []
    for r in rows:
        a = admins.get(r["_id"])
        out.append(
            {
                "admin_id": str(r["_id"]),
                "admin_code": getattr(a, "user_code", None),
                "admin_name": getattr(a, "full_name", None),
                "sa_pnl_share": str(r["sa_pnl"]),
                "sa_bkg_share": str(r["sa_bkg"]),
                "sa_net": str(r["sa_net"]),
                "house_pnl": str(r["house_pnl"]),
                "brokerage": str(r["brokerage"]),
                "admin_net": str(r["admin_net"]),
                "trades": r["trades"],
                "user_count": len(r.get("users") or []),
            }
        )
    return APIResponse(data=out)


@router.get("/admin/{admin_id}/users", response_model=APIResponse[list])
async def per_user_summary(
    admin_id: str, admin: SuperAdmin, from_: str | None = None, to: str | None = None
):
    """Per-user totals for one admin — SA earnings split by that admin's users."""
    from beanie import PydanticObjectId

    coll = AdminBookEntry.get_motor_collection()
    match = {"admin_id": PydanticObjectId(admin_id)}
    dm = _date_match(from_, to)
    if dm:
        match.update(dm)
    pipeline = [
        {"$match": match},
        {
            "$group": {
                "_id": "$user_id",
                "sa_pnl": {"$sum": "$sa_pnl_share_inr"},
                "sa_bkg": {"$sum": "$sa_bkg_share_inr"},
                "sa_net": {"$sum": "$sa_net_inr"},
                "house_pnl": {"$sum": "$house_pnl_inr"},
                "brokerage": {"$sum": "$brokerage_inr"},
                "trades": {"$sum": 1},
            }
        },
        {"$sort": {"sa_net": -1}},
    ]
    rows = await coll.aggregate(pipeline).to_list(length=5000)
    users = {u.id: u for u in await User.find({"_id": {"$in": [r["_id"] for r in rows]}}).to_list()}
    out = []
    for r in rows:
        u = users.get(r["_id"])
        out.append(
            {
                "user_id": str(r["_id"]),
                "user_code": getattr(u, "user_code", None),
                "user_name": getattr(u, "full_name", None),
                "sa_pnl_share": str(r["sa_pnl"]),
                "sa_bkg_share": str(r["sa_bkg"]),
                "sa_net": str(r["sa_net"]),
                "house_pnl": str(r["house_pnl"]),
                "brokerage": str(r["brokerage"]),
                "trades": r["trades"],
            }
        )
    return APIResponse(data=out)


@router.get("/transactions", response_model=APIResponse[list])
async def transactions(
    admin: SuperAdmin, from_: str | None = None, to: str | None = None, limit: int = 300
):
    """Flat chronological feed of every per-trade admin-book entry (all admins /
    users), newest first — the SA's "what came in, one by one" ledger. Each row
    shows the PnL share + brokerage share the SA earned on that single trade."""
    q = _date_match(from_, to)
    rows = await AdminBookEntry.find(q).sort("-created_at").limit(limit).to_list()
    admin_ids = {e.admin_id for e in rows}
    user_ids = {e.user_id for e in rows}
    people = {
        p.id: p
        for p in await User.find({"_id": {"$in": list(admin_ids | user_ids)}}).to_list()
    }
    out = []
    for e in rows:
        a = people.get(e.admin_id)
        u = people.get(e.user_id)
        out.append(
            {
                "trade_id": e.trade_id,
                "admin_code": getattr(a, "user_code", None),
                "admin_name": getattr(a, "full_name", None),
                "user_code": getattr(u, "user_code", None),
                "user_name": getattr(u, "full_name", None),
                "segment": e.segment,
                "symbol": e.instrument_symbol,
                "pnl_pct": str(e.pnl_pct_snapshot),
                "bkg_pct": str(e.bkg_pct_snapshot),
                "house_pnl": str(e.house_pnl_inr),
                "brokerage": str(e.brokerage_inr),
                "sa_pnl_share": str(e.sa_pnl_share_inr),
                "sa_bkg_share": str(e.sa_bkg_share_inr),
                "sa_net": str(e.sa_net_inr),
                "admin_net": str(e.admin_net_inr),
                "booked_at": e.booked_at or e.created_at,
            }
        )
    return APIResponse(data=out)


@router.get("/admin/{admin_id}/user/{user_id}/trades", response_model=APIResponse[list])
async def per_trade(
    admin_id: str, user_id: str, admin: SuperAdmin,
    from_: str | None = None, to: str | None = None, limit: int = 500,
):
    """Per-trade rows for one user under one admin — the finest drill-down."""
    from beanie import PydanticObjectId

    q: dict = {"admin_id": PydanticObjectId(admin_id), "user_id": PydanticObjectId(user_id)}
    dm = _date_match(from_, to)
    if dm:
        q.update(dm)
    rows = await AdminBookEntry.find(q).sort("-created_at").limit(limit).to_list()
    return APIResponse(
        data=[
            {
                "trade_id": e.trade_id,
                "segment": e.segment,
                "symbol": e.instrument_symbol,
                "pnl_pct": str(e.pnl_pct_snapshot),
                "bkg_pct": str(e.bkg_pct_snapshot),
                "house_pnl": str(e.house_pnl_inr),
                "brokerage": str(e.brokerage_inr),
                "sa_pnl_share": str(e.sa_pnl_share_inr),
                "sa_bkg_share": str(e.sa_bkg_share_inr),
                "sa_net": str(e.sa_net_inr),
                "admin_net": str(e.admin_net_inr),
                "booked_at": e.booked_at or e.created_at,
            }
            for e in rows
        ]
    )
