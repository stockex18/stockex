"""Self-serve money views for the logged-in admin-tier user.

- GET /admin/me/wallet    — the CURRENT admin/broker/sub-broker's OWN wallet:
  main available_balance, held games commission (temporary_balance), how much
  has been released, settlement-outstanding, plus their weekly P&L-share
  settlement history. Read-only (releasing held commission stays SUPER_ADMIN
  only, via /admin/games/hierarchy-earnings).
- GET /admin/me/house-summary — SUPER_ADMIN only: the house pool at a glance
  (games net collected/paid, pending hierarchy releases across everyone, house
  wallet balance, and total user settlement-outstanding).
"""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal

from beanie import PydanticObjectId
from bson import Decimal128

from app.core.dependencies import CurrentAdmin, SuperAdmin
from app.models.admin_settlement import AdminSettlement
from app.models.audit_log import AuditAction
from app.models.broker_settlement import BrokerSettlement
from app.models.transaction import TransactionType, WalletTransaction
from app.models.user import User, UserRole
from app.models.wallet import Wallet
from app.schemas.common import APIResponse
from app.services import wallet_service
from app.services.audit_service import log_event
from app.services.games import wallet_service as games_wallet_service
from app.utils.decimal_utils import ZERO, to_decimal
from fastapi import APIRouter, HTTPException, Query

router = APIRouter(prefix="/me", tags=["admin-me"])


def _f(v) -> float:
    try:
        return float(to_decimal(v))
    except Exception:
        return 0.0


# ── Self-service profile (admin-tier) — a BROKER sets their public `city`
#    here so they appear in the signup broker-search. ────────────────────
@router.get("/profile", response_model=APIResponse[dict])
async def my_profile(admin: CurrentAdmin):
    return APIResponse(
        data={
            "id": str(admin.id),
            "user_code": admin.user_code,
            "full_name": admin.full_name,
            "city": getattr(admin, "city", None),
            "role": admin.role.value if hasattr(admin.role, "value") else str(admin.role),
            # Expiry-settings lock — super-admin always True; an admin/broker is
            # True only when the SA unlocked it (drives the read-only expiry page).
            "can_edit_expiry_settings": (
                True
                if (admin.role.value if hasattr(admin.role, "value") else str(admin.role)) == "SUPER_ADMIN"
                else bool(getattr(admin, "can_edit_expiry_settings", False))
            ),
        }
    )


@router.put("/profile", response_model=APIResponse[dict])
async def update_my_profile(payload: dict, admin: CurrentAdmin):
    """Update the logged-in admin-tier user's own profile. A BROKER sets their
    public `city` (place) here → they become searchable at signup."""
    user = await User.get(admin.id)
    if user is None:
        raise HTTPException(status_code=404, detail="Not found")
    if "city" in payload:
        city = str(payload.get("city") or "").strip()
        user.city = city or None
    if payload.get("full_name"):
        user.full_name = str(payload["full_name"]).strip()
    await user.save()
    return APIResponse(
        data={"id": str(user.id), "full_name": user.full_name, "city": user.city}
    )


@router.post("/convert-to-real", response_model=APIResponse[dict])
async def convert_broker_to_real(admin: CurrentAdmin):
    """Convert the logged-in DEMO BROKER into a real broker: zero the (virtual)
    50L float, wipe its ledger, unlock full permissions (user-create), flip to
    LIVE. Login + hierarchy (platform pool, under the super-admin) are kept, so
    the broker carries on with a ₹0 float — funded later by the admin. 400 if the
    caller isn't a demo broker."""
    if admin.role != UserRole.BROKER or not getattr(admin, "is_demo", False):
        raise HTTPException(status_code=400, detail="This is not a demo broker account.")
    from app.services import demo_service

    res = await demo_service.convert_demo_broker_to_real(admin)
    if not res.get("converted"):
        raise HTTPException(status_code=400, detail="Could not convert this account.")
    try:
        await log_event(
            action=AuditAction.UPDATE,
            entity_type="User",
            entity_id=admin.id,
            actor_id=admin.id,
            new_values={"account_type": "LIVE", "is_demo": False, "role": "BROKER"},
        )
    except Exception:  # noqa: BLE001
        pass
    return APIResponse(
        data={"converted": True},
        message="Your broker account is now real. Float is ₹0 — contact your admin to add funds. You can now create users.",
    )


@router.get("/wallet", response_model=APIResponse[dict])
async def my_wallet(admin: CurrentAdmin):
    """The logged-in admin/broker/sub-broker's own wallet + settlement history."""
    w = await wallet_service.get_or_create(admin.id)

    # Weekly P&L-share settlement history for this role.
    history: list[dict] = []
    if admin.role == UserRole.BROKER:
        rows = (
            await BrokerSettlement.find(BrokerSettlement.broker_id == admin.id)
            .sort("-period_start")
            .limit(26)
            .to_list()
        )
        for r in rows:
            history.append(
                {
                    "period_start": r.period_start,
                    "period_end": r.period_end,
                    "net_house_pnl": _f(r.net_house_pnl_inr),
                    "share": _f(r.broker_share_inr),
                    "status": r.status.value if hasattr(r.status, "value") else str(r.status),
                }
            )
    else:  # ADMIN (and SUPER_ADMIN, who normally has none)
        rows = (
            await AdminSettlement.find(AdminSettlement.sub_admin_id == admin.id)
            .sort("-period_start")
            .limit(26)
            .to_list()
        )
        for r in rows:
            history.append(
                {
                    "period_start": r.period_start,
                    "period_end": r.period_end,
                    "net_house_pnl": _f(r.net_house_pnl_inr),
                    "share": _f(r.sub_admin_share_inr),
                    "status": r.status.value if hasattr(r.status, "value") else str(r.status),
                }
            )

    return APIResponse(
        data={
            "role": admin.role.value,
            "user_code": admin.user_code,
            # Main withdrawable wallet.
            "available_balance": _f(w.available_balance),
            "used_margin": _f(w.used_margin),
            "credit_limit": _f(w.credit_limit),
            "settlement_outstanding": _f(w.settlement_outstanding),
            "total_deposits": _f(w.total_deposits),
            "total_withdrawals": _f(w.total_withdrawals),
            # Held games hierarchy commission (released to main by SUPER_ADMIN).
            "temporary_balance": _f(w.temporary_balance),
            "temporary_total_earned": _f(w.temporary_total_earned),
            "temporary_total_released": _f(w.temporary_total_released),
            # Weekly P&L-share settlements.
            "settlement_history": history,
        }
    )


@router.get("/house-summary", response_model=APIResponse[dict])
async def house_summary(admin: SuperAdmin):
    """SUPER_ADMIN house pool at a glance."""
    house = await wallet_service.get_or_create(admin.id)

    # Games net on the house = signed sum of GAMES_HOUSE_SETTLE on the SA wallet
    # (+ stakes collected, − wins funded). Positive = house up.
    tcoll = WalletTransaction.get_motor_collection()
    games_agg = await tcoll.aggregate(
        [
            {
                "$match": {
                    "user_id": admin.id,
                    "transaction_type": TransactionType.GAMES_HOUSE_SETTLE.value,
                }
            },
            {"$group": {"_id": None, "net": {"$sum": {"$toDecimal": "$amount"}}}},
        ]
    ).to_list(1)
    games_net = _f(games_agg[0]["net"]) if games_agg else 0.0

    # Pending hierarchy releases = total held temporary_balance across everyone,
    # and total user settlement-outstanding across the platform.
    wcoll = Wallet.get_motor_collection()
    wagg = await wcoll.aggregate(
        [
            {
                "$group": {
                    "_id": None,
                    "temp": {"$sum": {"$toDecimal": "$temporary_balance"}},
                    "settle": {"$sum": {"$toDecimal": "$settlement_outstanding"}},
                    "temp_earned": {"$sum": {"$toDecimal": "$temporary_total_earned"}},
                    "temp_released": {"$sum": {"$toDecimal": "$temporary_total_released"}},
                }
            }
        ]
    ).to_list(1)
    row = wagg[0] if wagg else {}
    pending_releases = _f(row.get("temp", Decimal128("0")))
    settlement_total = _f(row.get("settle", Decimal128("0")))
    lifetime_commission = _f(row.get("temp_earned", Decimal128("0")))
    lifetime_released = _f(row.get("temp_released", Decimal128("0")))

    # How many admins/brokers currently hold commission.
    holders = await wcoll.count_documents({"temporary_balance": {"$gt": Decimal128("0")}})

    return APIResponse(
        data={
            "house_wallet_balance": _f(house.available_balance),
            "house_settlement_outstanding": _f(house.settlement_outstanding),
            # Kuber pool (distributable house pool, separate from personal main).
            "kuber_balance": _f(house.kuber_balance),
            "kuber_total_in": _f(house.kuber_total_in),
            "kuber_total_out": _f(house.kuber_total_out),
            "games_net": games_net,
            "pending_hierarchy_releases": pending_releases,
            "pending_release_holders": holders,
            "lifetime_hierarchy_commission": lifetime_commission,
            "lifetime_hierarchy_released": lifetime_released,
            "platform_settlement_outstanding": settlement_total,
        }
    )


# ── Self-release held games commission (temporary_balance → main) ─────
@router.post("/release-commission", response_model=APIResponse[dict])
async def release_commission(admin: CurrentAdmin, payload: dict | None = None):
    """The logged-in admin/broker/sub-broker releases THEIR OWN held games
    commission (`temporary_balance`) into their OWN main wallet.

    Body: {"amount": number | null}. A null/absent amount releases the FULL
    held balance. Reuses the atomic, self-guarded
    `games_wallet_service.release_temp_to_main` (same primitive the
    SUPER_ADMIN `/games/hierarchy-earnings/{id}/release` path uses); the
    SUPER_ADMIN path stays unchanged.
    """
    w = await wallet_service.get_or_create(admin.id)
    held = to_decimal(w.temporary_balance)

    raw = (payload or {}).get("amount")
    if raw is None:
        amt = held  # release ALL
    else:
        try:
            amt = to_decimal(raw)
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid amount")

    if amt <= 0:
        raise HTTPException(status_code=400, detail="Nothing to release")
    if amt > held:
        raise HTTPException(
            status_code=400,
            detail=f"Amount 🪙{amt} exceeds held commission 🪙{held}",
        )

    try:
        await games_wallet_service.release_temp_to_main(
            admin.id, amt, actor_id=admin.id
        )
    except HTTPException:
        raise
    except Exception as exc:  # atomic guard / insufficient temp → clean 400
        raise HTTPException(status_code=400, detail=str(exc) or "Release failed")

    fresh = await wallet_service.get_or_create(admin.id)
    return APIResponse(
        data={
            "released": _f(amt),
            "available_balance": _f(fresh.available_balance),
            "temporary_balance": _f(fresh.temporary_balance),
        },
        message="Commission released to main wallet",
    )


# ── Fund / commission ledger for the acting user ─────────────────────
_LEDGER_TYPES = [
    TransactionType.ADMIN_DEPOSIT.value,
    TransactionType.ADMIN_TRANSFER.value,
    TransactionType.ADMIN_WITHDRAW.value,
    TransactionType.ADMIN_FLOAT_DISPENSE.value,
    TransactionType.ADMIN_FLOAT_REPLENISH.value,
    TransactionType.GAMES_HIERARCHY.value,
    TransactionType.DEPOSIT.value,
    TransactionType.WITHDRAWAL.value,
]

# Per-trade earnings that flow to THIS node from the trading cascade (admin-book
# PnL/brokerage, SA share, broker/sub-broker markup, patti). One row per closing
# trade — how much came to this wallet, from which user.
_TRADE_EARN_TYPES = [
    TransactionType.ADMIN_BOOK_PNL.value,
    TransactionType.ADMIN_BOOK_BROKERAGE.value,
    TransactionType.SA_PNL_SHARE.value,
    TransactionType.SA_BROKERAGE_SHARE.value,
    TransactionType.BROKER_CASCADE_BROKERAGE.value,
    TransactionType.PATTI_PNL.value,
    TransactionType.PATTI_BROKERAGE.value,
]


# ── Per-member fund lifecycle (how a member used what its parent gave) ──
# The transaction types that describe an admin-tier member's money story:
# what the parent/SA GAVE them, what they PUSHED DOWN to users/brokers, what
# came back, and games commission earned. Signed as stored in the ledger.
_FUND_FLOW_TYPES = [
    TransactionType.ADMIN_DEPOSIT.value,          # + received from parent / SA (incl. opening fund)
    TransactionType.ADMIN_WITHDRAW.value,         # − pulled back by parent / SA
    TransactionType.ADMIN_TRANSFER.value,         # ∓ funded a child (−) / pulled from a child (+)
    TransactionType.ADMIN_FLOAT_DISPENSE.value,   # − dispensed to a downline USER
    TransactionType.ADMIN_FLOAT_REPLENISH.value,  # + replenished from a user withdrawal
    TransactionType.GAMES_HIERARCHY.value,        # + games commission earned
]


async def _fund_aggregates(ids: list) -> dict:
    """Per-user summed (signed) transaction amounts over the fund-flow types.

    Returns ``{user_id_str: {transaction_type: Decimal}}`` in a single grouped
    aggregation over the immutable ``wallet_transactions`` collection.
    """
    out: dict = defaultdict(dict)
    if not ids:
        return out
    coll = WalletTransaction.get_motor_collection()
    pipeline = [
        {"$match": {"user_id": {"$in": ids}, "transaction_type": {"$in": _FUND_FLOW_TYPES}}},
        {"$group": {"_id": {"u": "$user_id", "t": "$transaction_type"},
                    "total": {"$sum": {"$toDecimal": "$amount"}}}},
    ]
    async for row in coll.aggregate(pipeline):
        out[str(row["_id"]["u"])][row["_id"]["t"]] = to_decimal(row["total"])
    return out


def _fund_summary(a: dict, balance: Decimal, held: Decimal) -> dict:
    """Derive the human 'what did they do with the money' view from raw sums."""
    def g(t: str) -> Decimal:
        return a.get(t, ZERO)

    given_by_parent = g(TransactionType.ADMIN_DEPOSIT.value)             # + received (incl. opening)
    pulled_back = -g(TransactionType.ADMIN_WITHDRAW.value)              # stored − → show +
    transfer_net = g(TransactionType.ADMIN_TRANSFER.value)             # signed
    deployed_users = -g(TransactionType.ADMIN_FLOAT_DISPENSE.value)    # stored − → show +
    returned_users = g(TransactionType.ADMIN_FLOAT_REPLENISH.value)    # +
    games_earned = g(TransactionType.GAMES_HIERARCHY.value)            # +
    funded_downline = -transfer_net if transfer_net < ZERO else ZERO   # money funded to a child
    pulled_downline = transfer_net if transfer_net > ZERO else ZERO    # money pulled from a child
    deployed_total = deployed_users + funded_downline                 # everything pushed downstream

    return {
        "given_by_parent": _f(given_by_parent),
        "pulled_back": _f(pulled_back),
        "deployed_to_users": _f(deployed_users),
        "returned_from_users": _f(returned_users),
        "funded_to_downline": _f(funded_downline),
        "pulled_from_downline": _f(pulled_downline),
        "games_earned": _f(games_earned),
        "deployed_total": _f(deployed_total),
        "current_balance": _f(balance),
        "held": _f(held),
    }


@router.get("/ledger", response_model=APIResponse[list])
async def my_ledger(admin: CurrentAdmin, limit: int = Query(50, ge=1, le=200)):
    """The acting user's own fund / commission ledger.

    Filters the immutable `wallet_transactions` collection to the money-flow
    types that matter to an admin-tier member (how much the super-admin /
    parent funded them, self-released games commission, and their own
    deposits/withdrawals). The very first ADMIN_DEPOSIT row is the opening
    fund. Read-only.
    """
    rows = (
        await WalletTransaction.find(
            WalletTransaction.user_id == admin.id,
            {"transaction_type": {"$in": _LEDGER_TYPES}},
        )
        .sort("-created_at")
        .limit(limit)
        .to_list()
    )
    out: list[dict] = []
    for r in rows:
        out.append(
            {
                "id": str(r.id),
                "type": r.transaction_type.value
                if hasattr(r.transaction_type, "value")
                else str(r.transaction_type),
                "amount": _f(r.amount),  # signed as stored
                "narration": r.narration,
                "reference_type": r.reference_type,
                "created_at": r.created_at,
            }
        )
    return APIResponse(data=out)


@router.get("/trade-earnings", response_model=APIResponse[list])
async def my_trade_earnings(admin: CurrentAdmin, limit: int = Query(100, ge=1, le=500)):
    """This node's PER-TRADE earnings from the trading cascade — admin-book PnL /
    brokerage, SA share, broker/sub-broker markup, patti — one row per closing
    trade, newest first. Shows the admin/broker/sub-broker exactly how much came
    to THEIR wallet from each trade (the narration carries the user code)."""
    rows = (
        await WalletTransaction.find(
            WalletTransaction.user_id == admin.id,
            {"transaction_type": {"$in": _TRADE_EARN_TYPES}},
        )
        .sort("-created_at")
        .limit(limit)
        .to_list()
    )
    out: list[dict] = []
    for r in rows:
        out.append(
            {
                "id": str(r.id),
                "type": r.transaction_type.value
                if hasattr(r.transaction_type, "value")
                else str(r.transaction_type),
                "amount": _f(r.amount),  # signed (+ received, − paid)
                "narration": r.narration,
                "trade_id": r.reference_id,
                "created_at": r.created_at,
            }
        )
    return APIResponse(data=out)


# ── Direct fundable downline of the acting user ──────────────────────
async def _direct_members(admin: User) -> list[User]:
    """The acting user's DIRECT fundable members.

    SUPER_ADMIN → all ADMIN-role users.
    ADMIN       → BROKER users with assigned_admin_id == admin.id.
    BROKER      → BROKER users with assigned_broker_id == admin.id (sub-brokers).
    """
    if admin.role == UserRole.SUPER_ADMIN:
        q: dict = {"role": UserRole.ADMIN.value}
    elif admin.role == UserRole.ADMIN:
        q = {"role": UserRole.BROKER.value, "assigned_admin_id": admin.id}
    elif admin.role == UserRole.BROKER:
        q = {"role": UserRole.BROKER.value, "assigned_broker_id": admin.id}
    else:
        return []
    return await User.find(q).sort("+user_code").limit(200).to_list()


@router.get("/members", response_model=APIResponse[list])
async def my_members(admin: CurrentAdmin, q: str | None = Query(None)):
    """The acting user's direct fundable downline with live balances (cap 200).

    Optional `?q=` filters on user_code / full_name (case-insensitive substring).
    """
    members = await _direct_members(admin)
    needle = (q or "").strip().lower()
    if needle:
        members = [
            m
            for m in members
            if needle in (m.user_code or "").lower()
            or needle in (m.full_name or "").lower()
        ]

    ids = [m.id for m in members]
    wallets: dict = {}
    if ids:
        for w in await Wallet.find({"user_id": {"$in": ids}}).to_list():
            wallets[str(w.user_id)] = w
    agg = await _fund_aggregates(ids)

    out: list[dict] = []
    for m in members:
        w = wallets.get(str(m.id))
        bal = to_decimal(w.available_balance) if w else ZERO
        held = to_decimal(w.temporary_balance) if w else ZERO
        s = _fund_summary(agg.get(str(m.id), {}), bal, held)
        out.append(
            {
                "id": str(m.id),
                "user_code": m.user_code,
                "full_name": m.full_name,
                "role": m.role.value if hasattr(m.role, "value") else str(m.role),
                "available_balance": _f(bal),
                "temporary_balance": _f(held),
                # Compact fund-usage summary (full breakdown via /members/{id}/fund-detail).
                "given_by_parent": s["given_by_parent"],   # total the parent/SA gave them
                "deployed_total": s["deployed_total"],      # total they pushed to users/brokers
            }
        )
    return APIResponse(data=out)


@router.get("/members/{member_id}/fund-detail", response_model=APIResponse[dict])
async def my_member_fund_detail(
    member_id: str, admin: CurrentAdmin, limit: int = Query(100, ge=1, le=300)
):
    """Full fund lifecycle of ONE direct member — how much the parent/SA gave
    them, how they deployed it to users/brokers, what came back, games
    commission earned, plus the raw ledger. Read-only.

    Authorization: the member must be a DIRECT fundable downline of the acting
    user (same rule as ``/members``) — no peeking outside your own subtree.
    """
    member = await User.get(PydanticObjectId(str(member_id)))
    if member is None:
        raise HTTPException(status_code=404, detail="Member not found")
    directs = {str(m.id) for m in await _direct_members(admin)}
    if str(member.id) not in directs:
        raise HTTPException(status_code=403, detail="Not your direct member")

    w = await wallet_service.get_or_create(member.id)
    agg = await _fund_aggregates([member.id])
    summary = _fund_summary(
        agg.get(str(member.id), {}),
        to_decimal(w.available_balance),
        to_decimal(w.temporary_balance),
    )

    rows = (
        await WalletTransaction.find(
            WalletTransaction.user_id == member.id,
            {"transaction_type": {"$in": _FUND_FLOW_TYPES}},
        )
        .sort("-created_at")
        .limit(limit)
        .to_list()
    )
    ledger = [
        {
            "id": str(r.id),
            "type": r.transaction_type.value if hasattr(r.transaction_type, "value") else str(r.transaction_type),
            "amount": _f(r.amount),  # signed as stored
            "narration": r.narration,
            "created_at": r.created_at,
        }
        for r in rows
    ]

    return APIResponse(
        data={
            "member": {
                "id": str(member.id),
                "user_code": member.user_code,
                "full_name": member.full_name,
                "role": member.role.value if hasattr(member.role, "value") else str(member.role),
            },
            "summary": summary,
            "ledger": ledger,
        }
    )


# ── Games revenue analytics (SUPER_ADMIN) ────────────────────────────
# Canonical game keys (mirrors app.models.games.settings.GAME_KEYS). Kept as a
# local literal so this analytics endpoint degrades gracefully even if that
# module changes shape.
_GAMES_KEYS: tuple[str, ...] = (
    "niftyUpDown",
    "btcUpDown",
    "niftyNumber",
    "btcNumber",
    "niftyBracket",
    "niftyJackpot",
    "btcJackpot",
)


async def _game_stats(model, game_key: str, amount_field: str, payout_field: str) -> dict:
    """Per-collection tickets / gross / payouts aggregate. Defensive — any
    failure (missing collection/field) degrades to zeros so the whole
    breakdown never 500s on one bad game."""
    try:
        coll = model.get_motor_collection()
        agg = await coll.aggregate(
            [
                {"$match": {"game_key": game_key}},
                {
                    "$group": {
                        "_id": None,
                        "tickets": {"$sum": 1},
                        "gross": {
                            "$sum": {
                                "$ifNull": [{"$toDecimal": f"${amount_field}"}, Decimal128("0")]
                            }
                        },
                        "payouts": {
                            "$sum": {
                                "$ifNull": [{"$toDecimal": f"${payout_field}"}, Decimal128("0")]
                            }
                        },
                    }
                },
            ]
        ).to_list(1)
        if not agg:
            return {"tickets": 0, "gross_revenue": 0.0, "payouts": 0.0}
        row = agg[0]
        return {
            "tickets": int(row.get("tickets", 0) or 0),
            "gross_revenue": _f(row.get("gross", Decimal128("0"))),
            "payouts": _f(row.get("payouts", Decimal128("0"))),
        }
    except Exception:  # noqa: BLE001 — degrade gracefully per collection
        return {"tickets": 0, "gross_revenue": 0.0, "payouts": 0.0}


@router.get("/games-breakdown", response_model=APIResponse[dict])
async def games_breakdown(admin: SuperAdmin):
    """SUPER_ADMIN games revenue analytics — read-only + defensive.

    Returns:
      • per_game   : tickets / gross_revenue / payouts / house_net per game_key
      • per_admin  : commission_earned / held / released for admin/broker wallets
      • totals     : aggregate tickets / revenue / payouts / house_net
    """
    from app.models.games.bets import (
        BracketTrade,
        JackpotBid,
        NumberBet,
        UpDownBet,
    )

    # game_key → (model, stake_field, payout_field)
    model_for = {
        "niftyUpDown": (UpDownBet, "amount", "payout"),
        "btcUpDown": (UpDownBet, "amount", "payout"),
        "niftyNumber": (NumberBet, "amount", "payout"),
        "btcNumber": (NumberBet, "amount", "payout"),
        "niftyBracket": (BracketTrade, "amount", "payout"),
        "niftyJackpot": (JackpotBid, "amount", "prize"),
        "btcJackpot": (JackpotBid, "amount", "prize"),
    }

    per_game: list[dict] = []
    total_tickets = 0
    total_revenue = 0.0
    total_payouts = 0.0
    for key in _GAMES_KEYS:
        model, amt_f, pay_f = model_for[key]
        s = await _game_stats(model, key, amt_f, pay_f)
        house_net = round(s["gross_revenue"] - s["payouts"], 2)
        per_game.append(
            {
                "game_key": key,
                "tickets": s["tickets"],
                "gross_revenue": s["gross_revenue"],
                "payouts": s["payouts"],
                "house_net": house_net,
            }
        )
        total_tickets += s["tickets"]
        total_revenue += s["gross_revenue"]
        total_payouts += s["payouts"]

    # Per-admin/broker commission (from the trading Wallet temporary_* fields).
    per_admin: list[dict] = []
    try:
        admin_ids = [
            u.id
            for u in await User.find(
                {"role": {"$in": [UserRole.ADMIN.value, UserRole.BROKER.value]}}
            ).to_list()
        ]
        if admin_ids:
            wallets = await Wallet.find(
                {
                    "user_id": {"$in": admin_ids},
                    "$or": [
                        {"$expr": {"$gt": [{"$toDecimal": "$temporary_total_earned"}, 0]}},
                        {"$expr": {"$gt": [{"$toDecimal": "$temporary_balance"}, 0]}},
                        {"$expr": {"$gt": [{"$toDecimal": "$temporary_total_released"}, 0]}},
                    ],
                }
            ).to_list()
            users = {}
            for u in await User.find({"_id": {"$in": [w.user_id for w in wallets]}}).to_list():
                users[str(u.id)] = u
            for w in wallets:
                u = users.get(str(w.user_id))
                if u is None:
                    continue
                per_admin.append(
                    {
                        "user_code": u.user_code,
                        "full_name": u.full_name,
                        "commission_earned": _f(w.temporary_total_earned),
                        "held": _f(w.temporary_balance),
                        "released": _f(w.temporary_total_released),
                    }
                )
            per_admin.sort(key=lambda r: r["commission_earned"], reverse=True)
            per_admin = per_admin[:100]
    except Exception:  # noqa: BLE001 — degrade gracefully
        per_admin = []

    return APIResponse(
        data={
            "per_game": per_game,
            "per_admin": per_admin,
            "totals": {
                "total_tickets": total_tickets,
                "total_revenue": round(total_revenue, 2),
                "total_payouts": round(total_payouts, 2),
                "house_net": round(total_revenue - total_payouts, 2),
            },
        }
    )
