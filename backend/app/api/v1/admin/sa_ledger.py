"""Super-admin LEDGER — clear, section-wise money map.

One endpoint feeds a page with distinct sections so the SA understands exactly
where the money is and that it reconciles:

  • CASH        — the SA cash pool (topped up) − given to admins = remaining.
  • FUNDING     — per admin: SA funded, wallet now, passed to users/brokers.
  • PNL         — per admin (+ per user drill): users' net P&L → house gain.
  • BROKERAGE   — per admin + per BROKER: brokerage the users paid.
  • GAMES       — per admin (+ per user): games house result.
  • BACK TO SA  — admin-book PnL + brokerage share returned to the SA.
  • MATCH       — every admin wallet's txns sum to its balance (✓ tie-out).

Read-only except the cash top-up. Super-admin only.
"""

from __future__ import annotations

from beanie import PydanticObjectId
from bson import Decimal128
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.core.dependencies import SuperAdmin
from app.models.admin_book_entry import AdminBookEntry
from app.models.games.wallet import GamesWalletLedger
from app.models.transaction import TransactionType, WalletTransaction
from app.models.user import User, UserRole
from app.models.wallet import Wallet
from app.schemas.common import APIResponse
from app.services import wallet_service
from app.utils.decimal_utils import quantize_money, to_decimal

router = APIRouter(prefix="/sa-ledger", tags=["admin-sa-ledger"])
T = TransactionType


def _f(x) -> float:
    try:
        return float(to_decimal(x if x is not None else 0))
    except Exception:
        return 0.0


# Wallet-txn buckets for the per-admin tie-out (signed → sum == balance).
_FUNDED_IN = {T.ADMIN_DEPOSIT.value, T.ADMIN_FLOAT_REPLENISH.value, T.DEPOSIT.value, T.BONUS.value}
_TO_USERS = {T.ADMIN_FLOAT_DISPENSE.value, T.ADMIN_TRANSFER.value, T.ADMIN_WITHDRAW.value}
_TRADING = {T.ADMIN_BOOK_PNL.value, T.ADMIN_BOOK_BROKERAGE.value}
_TO_SA = {T.SA_PNL_SHARE.value, T.SA_BROKERAGE_SHARE.value, T.PLATFORM_CHARGE.value}
_GAMES_T = {T.GAMES_TRANSFER_IN.value, T.GAMES_TRANSFER_OUT.value,
            T.GAMES_HOUSE_SETTLE.value, T.GAMES_HIERARCHY.value}


class TopupReq(BaseModel):
    amount: float


@router.post("/cash-topup", response_model=APIResponse[dict])
async def cash_topup(payload: TopupReq, admin: SuperAdmin):
    """Add capital to the SA cash wallet (the pool admins are funded from)."""
    amt = quantize_money(to_decimal(payload.amount))
    if amt <= 0:
        raise HTTPException(status_code=400, detail="amount must be positive")
    await wallet_service.get_or_create(admin.id)
    await Wallet.get_motor_collection().update_one(
        {"user_id": admin.id},
        {"$inc": {"sa_cash_balance": Decimal128(str(amt)),
                  "sa_cash_total_in": Decimal128(str(amt))}},
    )
    sw = await wallet_service.get_or_create(admin.id)
    return APIResponse(data={"sa_cash_balance": str(getattr(sw, "sa_cash_balance", 0))})


async def _maps():
    clients = await User.find(User.role == UserRole.CLIENT).to_list()
    u2admin = {u.id: getattr(u, "assigned_admin_id", None) for u in clients}
    u2broker = {u.id: getattr(u, "assigned_broker_id", None) for u in clients}
    return u2admin, u2broker


@router.get("", response_model=APIResponse[dict])
async def sa_ledger(admin: SuperAdmin):
    wtx = WalletTransaction.get_motor_collection()
    admins = await User.find(User.role == UserRole.ADMIN).sort("full_name").to_list()
    admin_ids = [a.id for a in admins]
    wallets = {w.user_id: w for w in await Wallet.find({"user_id": {"$in": admin_ids}}).to_list()}
    u2admin, u2broker = await _maps()

    # ── Per-admin wallet buckets (tie-out) ──
    buckets = {aid: {"funded": 0.0, "to_users": 0.0, "trading": 0.0, "to_sa": 0.0,
                     "games_w": 0.0, "other": 0.0, "all": 0.0} for aid in admin_ids}
    async for r in wtx.aggregate([
        {"$match": {"user_id": {"$in": admin_ids}}},
        {"$group": {"_id": {"u": "$user_id", "t": "$transaction_type"}, "s": {"$sum": "$amount"}}},
    ]):
        aid, typ, s = r["_id"]["u"], r["_id"]["t"], _f(r["s"])
        b = buckets.get(aid)
        if b is None:
            continue
        b["all"] += s
        if typ in _FUNDED_IN: b["funded"] += s
        elif typ in _TO_USERS: b["to_users"] += s
        elif typ in _TRADING: b["trading"] += s
        elif typ in _TO_SA: b["to_sa"] += s
        elif typ in _GAMES_T: b["games_w"] += s
        else: b["other"] += s

    # ── User PnL → per admin ──
    pnl_by_admin: dict = {}
    async for r in wtx.aggregate([
        {"$match": {"transaction_type": T.PNL.value}},
        {"$group": {"_id": "$user_id", "s": {"$sum": "$amount"}}},
    ]):
        a = u2admin.get(r["_id"])
        if a is not None:
            pnl_by_admin[a] = pnl_by_admin.get(a, 0.0) + _f(r["s"])

    # ── Brokerage (CHARGES) → per admin + per broker ──
    brok_by_admin: dict = {}
    brok_by_broker: dict = {}
    async for r in wtx.aggregate([
        {"$match": {"transaction_type": T.CHARGES.value}},
        {"$group": {"_id": "$user_id", "s": {"$sum": "$amount"}}},
    ]):
        v = -_f(r["s"])  # CHARGES are debits → positive brokerage collected
        a = u2admin.get(r["_id"]); b = u2broker.get(r["_id"])
        if a is not None:
            brok_by_admin[a] = brok_by_admin.get(a, 0.0) + v
        if b is not None:
            brok_by_broker[b] = brok_by_broker.get(b, 0.0) + v

    # ── Games net (CREDIT − DEBIT) per user → per admin (house gain = −user net) ──
    gcredit: dict = {}; gdebit: dict = {}
    async for r in GamesWalletLedger.get_motor_collection().aggregate([
        {"$group": {"_id": {"u": "$owner_id", "t": "$entry_type"}, "s": {"$sum": "$amount"}}},
    ]):
        if r["_id"]["t"] == "CREDIT": gcredit[r["_id"]["u"]] = _f(r["s"])
        else: gdebit[r["_id"]["u"]] = _f(r["s"])
    games_house_by_admin: dict = {}
    for uid in set(gcredit) | set(gdebit):
        user_net = gcredit.get(uid, 0.0) - gdebit.get(uid, 0.0)
        a = u2admin.get(uid)
        if a is not None:
            games_house_by_admin[a] = games_house_by_admin.get(a, 0.0) - user_net  # house = −user

    # ── Back to SA (admin-book) per admin ──
    ab_by_admin: dict = {}
    async for r in AdminBookEntry.get_motor_collection().aggregate([
        {"$group": {"_id": "$admin_id", "p": {"$sum": "$sa_pnl_share_inr"},
                    "b": {"$sum": "$sa_bkg_share_inr"}}},
    ]):
        ab_by_admin[r["_id"]] = (_f(r["p"]), _f(r["b"]))

    # ── Assemble per-admin rows ──
    rows = []
    tot = {"funded": 0.0, "to_users": 0.0, "wallet_now": 0.0, "user_pnl": 0.0,
           "house_gain": 0.0, "brokerage": 0.0, "games": 0.0, "back_pnl": 0.0,
           "back_bkg": 0.0, "back_to_sa": 0.0, "delta": 0.0}
    for a in admins:
        b = buckets.get(a.id, {})
        w = wallets.get(a.id)
        wallet_now = _f(w.available_balance) if w else 0.0
        delta = round(wallet_now - b.get("all", 0.0), 2)
        user_pnl = round(pnl_by_admin.get(a.id, 0.0), 2)
        brokerage = round(brok_by_admin.get(a.id, 0.0), 2)
        games = round(games_house_by_admin.get(a.id, 0.0), 2)
        bp, bb = ab_by_admin.get(a.id, (0.0, 0.0))
        back = round(bp + bb, 2)
        rows.append({
            "admin_id": str(a.id), "admin_code": a.user_code, "admin_name": a.full_name,
            "funded": round(b.get("funded", 0.0), 2),
            "to_users": round(-b.get("to_users", 0.0), 2),
            "wallet_now": round(wallet_now, 2),
            "user_pnl": user_pnl, "house_gain": round(-user_pnl, 2),
            "brokerage": brokerage, "games": games,
            "back_pnl": round(bp, 2), "back_bkg": round(bb, 2), "back_to_sa": back,
            "delta": delta, "matched": abs(delta) < 1.0,
        })
        tot["funded"] += b.get("funded", 0.0); tot["to_users"] += -b.get("to_users", 0.0)
        tot["wallet_now"] += wallet_now; tot["user_pnl"] += user_pnl
        tot["house_gain"] += -user_pnl; tot["brokerage"] += brokerage; tot["games"] += games
        tot["back_pnl"] += bp; tot["back_bkg"] += bb; tot["back_to_sa"] += back
        tot["delta"] += delta
    rows.sort(key=lambda r: r["wallet_now"], reverse=True)

    # ── SA cash + kuber + main ──
    sw = await wallet_service.get_or_create(admin.id)
    cash = {
        "topped_up": _f(getattr(sw, "sa_cash_total_in", 0)),
        "given_to_admins": _f(getattr(sw, "sa_cash_total_out", 0)),
        "cash_balance": _f(getattr(sw, "sa_cash_balance", 0)),
        "main": _f(getattr(sw, "available_balance", 0)),
        "kuber": _f(getattr(sw, "kuber_balance", 0)),
    }
    totals = {k: round(v, 2) for k, v in tot.items()}
    totals["all_matched"] = abs(tot["delta"]) < 1.0

    return APIResponse(data={"cash": cash, "rows": rows, "totals": totals})


@router.get("/admin/{admin_id}/drill", response_model=APIResponse[dict])
async def admin_drill(admin_id: str, admin: SuperAdmin):
    """Per-user (PnL, brokerage, games) + per-broker (brokerage) breakdown for one
    admin — the drill-down under a ledger row."""
    aid = PydanticObjectId(admin_id)
    wtx = WalletTransaction.get_motor_collection()
    # users in this admin's pool
    clients = await User.find({"role": UserRole.CLIENT.value, "assigned_admin_id": aid}).to_list()
    uids = [u.id for u in clients]
    umap = {u.id: u for u in clients}
    u2broker = {u.id: getattr(u, "assigned_broker_id", None) for u in clients}

    pnl: dict = {}; brok: dict = {}
    if uids:
        async for r in wtx.aggregate([
            {"$match": {"user_id": {"$in": uids}, "transaction_type": T.PNL.value}},
            {"$group": {"_id": "$user_id", "s": {"$sum": "$amount"}}},
        ]):
            pnl[r["_id"]] = _f(r["s"])
        async for r in wtx.aggregate([
            {"$match": {"user_id": {"$in": uids}, "transaction_type": T.CHARGES.value}},
            {"$group": {"_id": "$user_id", "s": {"$sum": "$amount"}}},
        ]):
            brok[r["_id"]] = -_f(r["s"])
    gcredit: dict = {}; gdebit: dict = {}
    if uids:
        async for r in GamesWalletLedger.get_motor_collection().aggregate([
            {"$match": {"owner_id": {"$in": uids}}},
            {"$group": {"_id": {"u": "$owner_id", "t": "$entry_type"}, "s": {"$sum": "$amount"}}},
        ]):
            if r["_id"]["t"] == "CREDIT": gcredit[r["_id"]["u"]] = _f(r["s"])
            else: gdebit[r["_id"]["u"]] = _f(r["s"])

    users = []
    for u in clients:
        upnl = round(pnl.get(u.id, 0.0), 2)
        ubrok = round(brok.get(u.id, 0.0), 2)
        ugames_house = round(-(gcredit.get(u.id, 0.0) - gdebit.get(u.id, 0.0)), 2)
        if upnl == 0 and ubrok == 0 and ugames_house == 0:
            continue
        users.append({
            "user_id": str(u.id), "user_code": u.user_code, "user_name": u.full_name,
            "user_pnl": upnl, "house_gain": round(-upnl, 2),
            "brokerage": ubrok, "games_house": ugames_house,
        })
    users.sort(key=lambda r: r["house_gain"], reverse=True)

    # brokerage per broker (brokers under this admin)
    brokers = await User.find({"role": UserRole.BROKER.value, "assigned_admin_id": aid}).to_list()
    bmap = {b.id: b for b in brokers}
    brok_by_broker: dict = {}
    for uid, v in brok.items():
        bkr = u2broker.get(uid)
        if bkr is not None:
            brok_by_broker[bkr] = brok_by_broker.get(bkr, 0.0) + v
    broker_rows = []
    for bkr_id, v in brok_by_broker.items():
        bk = bmap.get(bkr_id)
        broker_rows.append({
            "broker_id": str(bkr_id),
            "broker_code": getattr(bk, "user_code", None),
            "broker_name": getattr(bk, "full_name", None),
            "brokerage": round(v, 2),
        })
    broker_rows.sort(key=lambda r: r["brokerage"], reverse=True)

    return APIResponse(data={"users": users, "brokers": broker_rows})
