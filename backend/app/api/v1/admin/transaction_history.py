"""Super-admin unified transaction history.

One feed that merges TRADING money (WalletTransaction) with EACH game's money
(GamesWalletLedger), filterable by source (all / trading / a specific game) and
by admin (super-admin can drill into any admin's pool). Scoped to the caller's
pool for a regular admin. Powers the responsive Transaction History page.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from beanie import PydanticObjectId
from fastapi import APIRouter, Depends, Query

from app.core.dependencies import CurrentAdmin, require_perm, scoped_user_ids
from app.models.games.wallet import GamesLedgerEntryType, GamesWalletLedger
from app.models.transaction import WalletTransaction
from app.models.user import User, UserRole
from app.schemas.common import APIResponse
from app.utils.decimal_utils import to_decimal

router = APIRouter(prefix="/transaction-history", tags=["admin-transaction-history"])

# The 7 games (GameSettings keys) — each is its own selectable "source".
GAME_KEYS = [
    "niftyUpDown", "btcUpDown", "niftyNumber", "btcNumber",
    "niftyBracket", "niftyJackpot", "btcJackpot",
]
GAME_LABELS = {
    "niftyUpDown": "Nifty Up/Down", "btcUpDown": "BTC Up/Down",
    "niftyNumber": "Nifty Number", "btcNumber": "BTC Number",
    "niftyBracket": "Nifty Bracket", "niftyJackpot": "Nifty Jackpot",
    "btcJackpot": "BTC Jackpot",
}


def _role(u) -> str:
    return str(getattr(getattr(u, "role", None), "value", None) or "")


def _f(x) -> float:
    """Decimal128 / Decimal / str / None → float, safely (float() rejects Decimal128)."""
    try:
        return float(to_decimal(x if x is not None else 0))
    except Exception:
        return 0.0


async def _scope_ids(admin: User, admin_id: str | None) -> list[PydanticObjectId]:
    """The user_ids the caller may see. A super-admin can target ONE admin's
    pool via admin_id; otherwise the caller's own pool."""
    if admin_id and _role(admin) == "SUPER_ADMIN":
        try:
            target = await User.get(PydanticObjectId(admin_id))
        except Exception:
            target = None
        if target is not None:
            return await scoped_user_ids(target, include_closed=True)
    return await scoped_user_ids(admin, include_closed=True)


async def _admin_options(admin: User) -> list[dict[str, str]]:
    """Admin dropdown (super-admin only) — every ADMIN so the SA can filter the
    feed to a single admin's pool."""
    if _role(admin) != "SUPER_ADMIN":
        return []
    rows = await User.find(User.role == UserRole.ADMIN).sort("full_name").to_list()
    return [{"id": str(a.id), "label": a.full_name or a.user_code or "admin"} for a in rows]


@router.get("/reconciliation", response_model=APIResponse[dict])
async def reconciliation(admin: CurrentAdmin):
    """SUPER-ADMIN ledger reconciliation. Per admin: money the SA funded to them
    (kuber/main deposits), their wallet now, what they dispensed to users, the
    brokerage their users generated, and what came BACK to the SA (admin-book PnL
    + brokerage share). Grand totals + the SA's own balance so the ledger ties
    out. Read-only."""
    from app.models.admin_book_entry import AdminBookEntry
    from app.models.transaction import TransactionType
    from app.models.wallet import Wallet
    from app.services import netting_service, wallet_service

    if _role(admin) != "SUPER_ADMIN":
        return APIResponse(data={"is_super": False, "rows": [], "totals": {}})

    wtx = WalletTransaction.get_motor_collection()
    T = TransactionType

    # 1) Per-admin funding (ADMIN_DEPOSIT/WITHDRAW) + float dispensed
    #    (ADMIN_FLOAT_DISPENSE/REPLENISH), grouped on the admin's own wallet.
    fund_pipe = [
        {"$match": {"transaction_type": {"$in": [
            T.ADMIN_DEPOSIT.value, T.ADMIN_WITHDRAW.value,
            T.ADMIN_FLOAT_DISPENSE.value, T.ADMIN_FLOAT_REPLENISH.value,
        ]}}},
        {"$group": {
            "_id": "$user_id",
            "funded": {"$sum": {"$cond": [
                {"$in": ["$transaction_type", [T.ADMIN_DEPOSIT.value, T.ADMIN_WITHDRAW.value]]},
                "$amount", 0]}},
            "dispensed": {"$sum": {"$cond": [
                {"$in": ["$transaction_type", [T.ADMIN_FLOAT_DISPENSE.value, T.ADMIN_FLOAT_REPLENISH.value]]},
                "$amount", 0]}},
        }},
    ]
    fund_map = {r["_id"]: r async for r in wtx.aggregate(fund_pipe)}

    # 2) Per-admin brokerage the users PAID (CHARGES), mapped user → owning admin.
    users = await User.find(User.role == UserRole.CLIENT).to_list()
    u2admin = {u.id: getattr(u, "assigned_admin_id", None) for u in users}
    brok_pipe = [
        {"$match": {"transaction_type": T.CHARGES.value}},
        {"$group": {"_id": "$user_id", "brok": {"$sum": "$amount"}}},
    ]
    brok_by_admin: dict = {}
    async for r in wtx.aggregate(brok_pipe):
        a = u2admin.get(r["_id"])
        if a is not None:
            brok_by_admin[a] = brok_by_admin.get(a, 0) + _f(r["brok"])

    # 3) Per-admin returned to SA (admin-book PnL + brokerage share).
    ab = AdminBookEntry.get_motor_collection()
    ab_pipe = [
        {"$group": {"_id": "$admin_id",
                    "sa_pnl": {"$sum": "$sa_pnl_share_inr"},
                    "sa_bkg": {"$sum": "$sa_bkg_share_inr"}}},
    ]
    ab_map = {r["_id"]: r async for r in ab.aggregate(ab_pipe)}

    # 4) Assemble per admin.
    admins = await User.find(User.role == UserRole.ADMIN).sort("full_name").to_list()
    admin_ids = [a.id for a in admins]
    wallets = {w.user_id: w for w in await Wallet.find({"user_id": {"$in": admin_ids}}).to_list()}

    rows = []
    tot = {"funded": 0.0, "wallet_now": 0.0, "dispensed": 0.0, "brokerage": 0.0,
           "sa_pnl": 0.0, "sa_bkg": 0.0, "returned": 0.0}
    for a in admins:
        f = fund_map.get(a.id, {})
        funded = _f(f.get("funded"))
        dispensed = -_f(f.get("dispensed"))  # debits are negative → show positive out
        w = wallets.get(a.id)
        wallet_now = _f(w.available_balance) if w else 0.0
        # CHARGES are debits (negative on the user) → negate to show brokerage collected.
        brokerage = -float(brok_by_admin.get(a.id, 0) or 0)
        abr = ab_map.get(a.id, {})
        sa_pnl = _f(abr.get("sa_pnl"))
        sa_bkg = _f(abr.get("sa_bkg"))
        returned = sa_pnl + sa_bkg
        rows.append({
            "admin_id": str(a.id), "admin_code": a.user_code, "admin_name": a.full_name,
            "funded_by_sa": round(funded, 2), "wallet_now": round(wallet_now, 2),
            "dispensed_to_users": round(dispensed, 2), "user_brokerage": round(brokerage, 2),
            "returned_sa_pnl": round(sa_pnl, 2), "returned_sa_brokerage": round(sa_bkg, 2),
            "returned_to_sa": round(returned, 2),
        })
        tot["funded"] += funded; tot["wallet_now"] += wallet_now
        tot["dispensed"] += dispensed; tot["brokerage"] += brokerage
        tot["sa_pnl"] += sa_pnl; tot["sa_bkg"] += sa_bkg; tot["returned"] += returned
    rows.sort(key=lambda r: r["returned_to_sa"], reverse=True)

    # 5) SA own balance (main + kuber) for the tie-out.
    sa_id = await netting_service._resolve_super_admin_id()
    sa_main = sa_kuber = 0.0
    if sa_id is not None:
        sw = await wallet_service.get_or_create(sa_id)
        sa_main = _f(getattr(sw, "available_balance", 0))
        sa_kuber = _f(getattr(sw, "kuber_balance", 0))

    totals = {k: round(v, 2) for k, v in tot.items()}
    totals.update({
        "sa_main": round(sa_main, 2), "sa_kuber": round(sa_kuber, 2),
        "sa_total_now": round(sa_main + sa_kuber, 2),
    })
    return APIResponse(data={"is_super": True, "rows": rows, "totals": totals})


@router.get("", response_model=APIResponse[dict])
async def transaction_history(
    admin: CurrentAdmin,
    source: str = Query("all", description="all | trading | <game_key>"),
    admin_id: str | None = Query(None),
    limit: int = Query(400, ge=1, le=2000),
    _: None = Depends(require_perm("ledger", "read")),
):
    ids = await _scope_ids(admin, admin_id)
    meta = {
        "admins": await _admin_options(admin),
        "games": [{"key": k, "label": GAME_LABELS[k]} for k in GAME_KEYS],
        "is_super": _role(admin) == "SUPER_ADMIN",
    }
    if not ids:
        return APIResponse(data={"rows": [], **meta})

    rows: list[dict[str, Any]] = []

    # ── Trading money (WalletTransaction — signed amount) ──────────────
    if source in ("all", "trading"):
        txns = (
            await WalletTransaction.find({"user_id": {"$in": ids}})
            .sort("-created_at")
            .limit(limit)
            .to_list()
        )
        for t in txns:
            amt = to_decimal(t.amount)
            rows.append(
                {
                    "id": f"t_{t.id}",
                    "date": t.created_at,
                    "source": "trading",
                    "source_label": "Trading",
                    "category": t.transaction_type.value,
                    "amount": float(amt),  # signed
                    "balance_after": float(to_decimal(t.balance_after)),
                    "description": t.narration or "",
                    "_uid": str(t.user_id),
                }
            )

    # ── Games money (GamesWalletLedger — magnitude + direction) ─────────
    if source == "all" or source in GAME_KEYS:
        gq: dict[str, Any] = {"owner_id": {"$in": ids}}
        gq["game_key"] = source if source in GAME_KEYS else {"$in": GAME_KEYS}
        gls = (
            await GamesWalletLedger.find(gq).sort("-created_at").limit(limit).to_list()
        )
        for g in gls:
            mag = to_decimal(g.amount)
            signed = mag if g.entry_type == GamesLedgerEntryType.CREDIT else -mag
            gk = g.game_key or "games"
            kind = (g.meta or {}).get("kind") or g.entry_type.value
            rows.append(
                {
                    "id": f"g_{g.id}",
                    "date": g.created_at,
                    "source": gk,
                    "source_label": GAME_LABELS.get(gk, gk),
                    "category": str(kind),
                    "amount": float(signed),
                    "balance_after": float(to_decimal(g.balance_after)),
                    "description": g.description or "",
                    "_uid": str(g.owner_id),
                }
            )

    # newest first, then cap.
    rows.sort(key=lambda r: r["date"] or datetime.min, reverse=True)
    rows = rows[:limit]

    # ── Enrich with user + owning-admin names (batch) ──────────────────
    uid_objs = list({PydanticObjectId(r["_uid"]) for r in rows})
    users = {str(u.id): u for u in await User.find({"_id": {"$in": uid_objs}}).to_list()}
    admin_ids = list(
        {u.assigned_admin_id for u in users.values() if u.assigned_admin_id is not None}
    )
    admins = {str(a.id): a for a in await User.find({"_id": {"$in": admin_ids}}).to_list()}
    for r in rows:
        u = users.get(r.pop("_uid"))
        r["user_code"] = u.user_code if u else "—"
        r["user_name"] = (u.full_name if u else "") or ""
        oa = admins.get(str(u.assigned_admin_id)) if (u and u.assigned_admin_id) else None
        r["admin_name"] = (oa.full_name or oa.user_code) if oa else ("—" if not u else "Platform")
        r["date"] = r["date"].isoformat() if r["date"] else None

    return APIResponse(data={"rows": rows, **meta})
