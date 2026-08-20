"""Inter-admin fund flow (mirrors D:\\Stockex adminManagementRoutes fund ops).

- Direct transfers: a parent (or SUPER_ADMIN) pushes funds to / pulls funds
  from a child admin/broker — settles immediately.
- Fund-request chain: a child asks its parent (or SA) for funds; the parent
  approves (crediting the child) or rejects.

SA funding uses the kuber+personal split (kuber_service). SA approving skips
the balance gate (unlimited), mirroring the reference. All moves write ledgers.
"""

from __future__ import annotations

import logging

from beanie import PydanticObjectId
from bson import Decimal128

from app.core.exceptions import InsufficientFundsError, NotFoundError, ValidationFailedError
from app.models.admin_fund import AdminFundRequest, AdminFundStatus
from app.models.transaction import TransactionType
from app.models.user import User, UserRole
from app.services import kuber_service, wallet_service
from app.utils.decimal_utils import ZERO, quantize_money, to_decimal
from app.utils.time_utils import now_utc

logger = logging.getLogger(__name__)

# Platform-settings key for the live ON/OFF toggle (super-admin flips it from
# the panel). When the row is absent, the env default `settings.ADMIN_FLOAT_
# ENABLED` applies — so the toggle is authoritative once set, env is the seed.
ADMIN_FLOAT_ENABLED_KEY = "admin_float_enabled"


async def is_admin_float_enabled() -> bool:
    """Is the admin fund-cap / float feature ON? Reads the DB toggle (live,
    no restart), falling back to the env default when unset."""
    from app.core.config import settings
    from app.models.platform_setting import PlatformSetting

    row = await PlatformSetting.find_one(PlatformSetting.setting_key == ADMIN_FLOAT_ENABLED_KEY)
    if row is None:
        return bool(settings.ADMIN_FLOAT_ENABLED)
    return bool(row.setting_value)


async def _super_admin_id() -> PydanticObjectId | None:
    from app.services import netting_service

    return await netting_service._resolve_super_admin_id()


def _parent_id(user: User, sa_id):
    """The admin/broker directly above `user` (who funds/approves for them)."""
    return (
        getattr(user, "assigned_broker_id", None)
        or getattr(user, "assigned_admin_id", None)
        or sa_id
    )


def _is_admin_tier(u: User) -> bool:
    return u.role in (UserRole.SUPER_ADMIN, UserRole.ADMIN, UserRole.BROKER)


async def _assert_can_manage(actor: User, child: User) -> None:
    """Actor may fund/pull a child only if they are SA or the child's parent."""
    if actor.role == UserRole.SUPER_ADMIN:
        return
    sa_id = await _super_admin_id()
    if _parent_id(child, sa_id) != actor.id:
        raise ValidationFailedError("Not your direct member")


# ── Direct transfers ───────────────────────────────────────────────────
async def add_funds(actor: User, child_id, amount, description: str = "", payment_mode: str | None = None) -> dict:
    """Parent (or SA) credits a child admin/broker. SA funds from kuber+main.

    `payment_mode` (Cash/Cheque/Banking/UPI/Others) records how the funder
    physically received the money before generating these coins — stamped on
    the child's ADMIN_DEPOSIT ledger row for the SA coin-generation report.
    """
    amt = quantize_money(to_decimal(amount))
    if amt <= ZERO:
        raise ValidationFailedError("amount must be positive")
    child = await User.get(PydanticObjectId(str(child_id)))
    if child is None or not _is_admin_tier(child):
        raise NotFoundError("Member not found")
    await _assert_can_manage(actor, child)

    narration = description or f"Funds from {actor.user_code}"
    # Debit the funder.
    if actor.role == UserRole.SUPER_ADMIN:
        plan = kuber_service.resolve_funding_plan_for_admin(child)
        await kuber_service.fund_admin_share_from_sa_wallets(
            actor.id, amt, plan["kuber_pct"], narration=f"Fund {child.user_code}", actor_id=actor.id
        )
        # SA Cash Wallet tracker (SA Ledger): funding an admin draws down the SA's
        # cash pool + records the "given to admins" total. Best-effort, additive.
        try:
            from app.models.wallet import Wallet

            await Wallet.get_motor_collection().update_one(
                {"user_id": actor.id},
                {"$inc": {"sa_cash_balance": Decimal128(str(-amt)),
                          "sa_cash_total_out": Decimal128(str(amt))}},
            )
        except Exception:
            logging.getLogger(__name__).debug("sa_cash_decrement_failed", exc_info=True)
    else:
        pw = await wallet_service.get_or_create(actor.id)
        if to_decimal(pw.available_balance) < amt:
            raise InsufficientFundsError("Insufficient balance to fund member")
        await wallet_service.adjust(actor.id, -amt, transaction_type=TransactionType.ADMIN_TRANSFER,
                                    narration=f"Fund {child.user_code}", reference_type="ADMIN_FUND", actor_id=actor.id)
    # Credit the child.
    await wallet_service.adjust(child.id, amt, transaction_type=TransactionType.ADMIN_DEPOSIT,
                                narration=narration, reference_type="ADMIN_FUND", actor_id=actor.id,
                                payment_mode=payment_mode)
    return {"ok": True, "amount": str(amt)}


async def deduct_funds(
    actor: User, child_id, amount, description: str = "", payment_mode: str | None = None
) -> dict:
    """Parent (or SA) pulls funds back from a child admin/broker.

    `payment_mode` is the mirror of the one on `add_funds`: it records how the
    money physically went BACK to the member (Cash/Cheque/Banking/UPI/Others)
    before their coins were burned, and is stamped on the child's
    ADMIN_WITHDRAW row so the pay-out side is as auditable as the take-in side.
    """
    amt = quantize_money(to_decimal(amount))
    if amt <= ZERO:
        raise ValidationFailedError("amount must be positive")
    child = await User.get(PydanticObjectId(str(child_id)))
    if child is None or not _is_admin_tier(child):
        raise NotFoundError("Member not found")
    await _assert_can_manage(actor, child)

    cw = await wallet_service.get_or_create(child.id)
    if to_decimal(cw.available_balance) < amt:
        raise InsufficientFundsError("Member has insufficient balance")
    # Debit child, credit the actor's main wallet (pulled funds land in main;
    # SA can move main → kuber afterwards if it should return to the pool).
    await wallet_service.adjust(child.id, -amt, transaction_type=TransactionType.ADMIN_WITHDRAW,
                                narration=f"Funds pulled by {actor.user_code}", reference_type="ADMIN_FUND", actor_id=actor.id,
                                payment_mode=payment_mode)
    await wallet_service.adjust(actor.id, amt, transaction_type=TransactionType.ADMIN_TRANSFER,
                                narration=f"Pulled from {child.user_code}", reference_type="ADMIN_FUND", actor_id=actor.id)
    return {"ok": True, "amount": str(amt)}


# ── Peer transfer (admin → ANY admin by id/code) ───────────────────────
async def _resolve_admin_target(target: str) -> User:
    """Resolve an admin-tier user by user_code (ADM…/BRK…) or ObjectId."""
    t = (target or "").strip()
    if not t:
        raise ValidationFailedError("Enter the recipient admin's ID")
    user = await User.find_one(User.user_code == t)
    if user is None:
        try:
            user = await User.get(PydanticObjectId(t))
        except Exception:
            user = None
    if user is None or not _is_admin_tier(user):
        raise NotFoundError(f"No admin found with ID '{t}'")
    return user


async def transfer_to_admin(actor: User, target: str, amount, description: str = "") -> dict:
    """Peer transfer: an admin sends part of their OWN float to ANY other admin
    identified by ID/code — no parent-child link required. Settles immediately.
    Safe by construction: the sender can only move money they actually hold
    (their Wallet.available_balance), so there's no way to pull from someone else.
    """
    amt = quantize_money(to_decimal(amount))
    if amt <= ZERO:
        raise ValidationFailedError("amount must be positive")
    if not _is_admin_tier(actor):
        raise ValidationFailedError("Only admin-tier accounts can transfer funds")
    tgt = await _resolve_admin_target(target)
    if tgt.id == actor.id:
        raise ValidationFailedError("You can't transfer funds to yourself")

    aw = await wallet_service.get_or_create(actor.id)
    if to_decimal(aw.available_balance) < amt:
        raise InsufficientFundsError(
            f"Insufficient balance: 🪙{to_decimal(aw.available_balance):,.2f} available, 🪙{amt:,.2f} needed"
        )
    await wallet_service.adjust(
        actor.id, -amt, transaction_type=TransactionType.ADMIN_TRANSFER,
        narration=description or f"Transfer to {tgt.user_code}",
        reference_type="ADMIN_PEER_TRANSFER", actor_id=actor.id,
    )
    await wallet_service.adjust(
        tgt.id, amt, transaction_type=TransactionType.ADMIN_DEPOSIT,
        narration=description or f"Transfer from {actor.user_code}",
        reference_type="ADMIN_PEER_TRANSFER", actor_id=actor.id,
    )
    logger.info("admin_peer_transfer from=%s to=%s amount=%s", actor.user_code, tgt.user_code, amt)
    return {
        "ok": True, "amount": str(amt),
        "to_code": tgt.user_code, "to_name": tgt.full_name,
        "to_role": tgt.role.value if hasattr(tgt.role, "value") else str(tgt.role),
    }


# ── Admin float ↔ user funding (SA→admin allocation caps user deposits) ─
# The admin's spendable ceiling IS their own Wallet.available_balance (one
# shared float, same pool the inter-admin transfers above draw from). When a
# downline USER is funded the OWNING admin's float is debited; a user
# withdrawal replenishes it. SA is always unlimited (never capped/debited).
# All of this is a NO-OP unless settings.ADMIN_FLOAT_ENABLED is True — so the
# legacy "mint into the user wallet" behaviour is byte-identical until the
# operator turns the feature on (after giving each admin a float).
async def _owning_admin_id(user_or_id):
    """The admin/broker whose float funds this user, plus the SA id."""
    sa_id = await _super_admin_id()
    user = user_or_id if isinstance(user_or_id, User) else await User.get(PydanticObjectId(str(user_or_id)))
    if user is None:
        return None, sa_id, None
    return _parent_id(user, sa_id), sa_id, user


async def debit_admin_float_for_user(
    user_or_id, amount, *, reference_type: str, reference_id: str | None = None,
    actor_id=None, narration: str | None = None,
) -> None:
    """Debit the user's OWNING-admin float by `amount` before crediting the user.

    NO-OP when the feature flag is off or the owning admin is the SUPER_ADMIN
    (SA is unlimited). Raises InsufficientFundsError when a non-SA owning admin
    can't cover it — the caller must let that propagate so the funding is blocked.
    """
    if not await is_admin_float_enabled():
        return
    amt = quantize_money(to_decimal(amount))
    if amt <= ZERO:
        return
    owner_id, sa_id, user = await _owning_admin_id(user_or_id)
    if owner_id is None or (sa_id is not None and str(owner_id) == str(sa_id)):
        return  # SA-owned user → unlimited
    ow = await wallet_service.get_or_create(owner_id)
    if to_decimal(ow.available_balance) < amt:
        raise InsufficientFundsError(
            f"Admin float insufficient: 🪙{to_decimal(ow.available_balance):,.2f} available, "
            f"🪙{amt:,.2f} needed. Fund the admin (opening fund / fund request) first."
        )
    await wallet_service.adjust(
        owner_id, -amt, transaction_type=TransactionType.ADMIN_FLOAT_DISPENSE,
        narration=narration or f"Float dispensed to {getattr(user, 'user_code', user_or_id)}",
        reference_type=reference_type, reference_id=reference_id, actor_id=actor_id,
    )


async def credit_admin_float_for_user(
    user_or_id, amount, *, reference_type: str, reference_id: str | None = None,
    actor_id=None, narration: str | None = None,
) -> None:
    """Replenish the user's OWNING-admin float by `amount` (mirror of debit —
    used on a user withdrawal / debit, and to roll back a failed deposit).
    NO-OP when the flag is off or the owning admin is the SUPER_ADMIN."""
    if not await is_admin_float_enabled():
        return
    amt = quantize_money(to_decimal(amount))
    if amt <= ZERO:
        return
    owner_id, sa_id, user = await _owning_admin_id(user_or_id)
    if owner_id is None or (sa_id is not None and str(owner_id) == str(sa_id)):
        return
    await wallet_service.adjust(
        owner_id, amt, transaction_type=TransactionType.ADMIN_FLOAT_REPLENISH,
        narration=narration or f"Float replenished from {getattr(user, 'user_code', user_or_id)}",
        reference_type=reference_type, reference_id=reference_id, actor_id=actor_id,
    )


# ── Fund-request chain (requests up, approvals down) ───────────────────
async def create_fund_request(requester: User, amount, reason: str = "") -> AdminFundRequest:
    amt = quantize_money(to_decimal(amount))
    if amt <= ZERO:
        raise ValidationFailedError("amount must be positive")
    if requester.role == UserRole.SUPER_ADMIN:
        raise ValidationFailedError("Super-admin does not request funds")
    sa_id = await _super_admin_id()
    target = _parent_id(requester, sa_id)
    req = AdminFundRequest(
        requester_id=requester.id,
        target_admin_id=target,
        amount=Decimal128(str(amt)),
        reason=reason,
    )
    await req.insert()
    return req


async def _resolve(approver: User, req_id, approve: bool, remarks: str | None) -> AdminFundRequest:
    coll = AdminFundRequest.get_motor_collection()
    new_status = AdminFundStatus.APPROVED.value if approve else AdminFundStatus.REJECTED.value
    claimed = await coll.find_one_and_update(
        {"_id": PydanticObjectId(str(req_id)), "status": AdminFundStatus.PENDING.value, "target_admin_id": approver.id},
        {"$set": {"status": new_status, "remarks": remarks, "resolved_by": approver.id, "resolved_at": now_utc()}},
    )
    if claimed is None:
        raise NotFoundError("Request not found, already resolved, or not yours to approve")
    req = await AdminFundRequest.get(PydanticObjectId(str(req_id)))
    if approve:
        amt = to_decimal(req.amount)
        requester = await User.get(req.requester_id)
        # Credit the requester. SA approver skips the balance gate (unlimited);
        # a non-SA approver is debited.
        if approver.role != UserRole.SUPER_ADMIN:
            pw = await wallet_service.get_or_create(approver.id)
            if to_decimal(pw.available_balance) < amt:
                # roll the request back to PENDING and refuse
                await coll.update_one({"_id": req.id}, {"$set": {"status": AdminFundStatus.PENDING.value, "resolved_by": None, "resolved_at": None}})
                raise InsufficientFundsError("Insufficient balance to approve")
            await wallet_service.adjust(approver.id, -amt, transaction_type=TransactionType.ADMIN_TRANSFER,
                                        narration=f"Approved fund request of {requester.user_code if requester else ''}",
                                        reference_type="FUND_REQUEST", reference_id=str(req.id), actor_id=approver.id)
        await wallet_service.adjust(req.requester_id, amt, transaction_type=TransactionType.ADMIN_DEPOSIT,
                                    narration="Fund request approved", reference_type="FUND_REQUEST",
                                    reference_id=str(req.id), actor_id=approver.id)
    return req


async def approve_fund_request(approver: User, req_id) -> AdminFundRequest:
    return await _resolve(approver, req_id, True, None)


async def reject_fund_request(approver: User, req_id, remarks: str | None = None) -> AdminFundRequest:
    return await _resolve(approver, req_id, False, remarks)


async def list_incoming(approver: User, status: str = "PENDING") -> list[dict]:
    rows = (
        await AdminFundRequest.find(AdminFundRequest.target_admin_id == approver.id, AdminFundRequest.status == status)
        .sort("-created_at").limit(200).to_list()
    )
    return await _serialize(rows)


async def list_mine(requester: User) -> list[dict]:
    rows = (
        await AdminFundRequest.find(AdminFundRequest.requester_id == requester.id)
        .sort("-created_at").limit(200).to_list()
    )
    return await _serialize(rows)


async def coin_generation_summary(actor: User) -> dict:
    """Per-admin coin movement THIS actor caused, split by payment mode.

    Counts BOTH directions, because the headline is what the actor has put
    into circulation NET — paying a member back burns coins again:

        ADMIN_DEPOSIT   (Received) -> coins generated, stored positive
        ADMIN_WITHDRAW  (Pay)      -> coins pulled back, stored NEGATIVE

    Because the withdraw rows are already negative, summing the two together
    nets naturally. Counting only deposits — as this did — meant the total
    never moved when money was paid back out, so it drifted further from the
    real coins-in-circulation figure with every payout.

    Returns:
        {
          "total_generated": float,           # NET across all admins
          "total_in": float, "total_out": float,
          "admins": [                         # sorted desc by net
            {"id", "user_code", "full_name",
             "total": float,                  # net for this admin
             "in": float, "out": float,
             "count": int,                    # receipts + payouts
             "in_count": int, "out_count": int,
             "by_mode": {"CASH": float, ...},      # net per mode
             "by_mode_in": {...}, "by_mode_out": {...}},
            ...
          ]
        }
    """
    from app.models.transaction import WalletTransaction

    coll = WalletTransaction.get_motor_collection()
    # Only credits this actor generated into admins (ADMIN_DEPOSIT, positive
    # amount, created_by=actor). Legacy rows without payment_mode fold into CASH
    # (operator: "abhi jo direct add hua hai ve cash type se entry kar dena").
    pipeline = [
        {"$match": {
            "transaction_type": {"$in": [
                TransactionType.ADMIN_DEPOSIT.value,
                TransactionType.ADMIN_WITHDRAW.value,
            ]},
            "created_by": actor.id,
        }},
        {"$group": {
            "_id": {
                "user": "$user_id",
                "mode": {"$ifNull": ["$payment_mode", "CASH"]},
                "type": "$transaction_type",
            },
            "amount": {"$sum": "$amount"},
            "count": {"$sum": 1},
        }},
    ]
    rows = await coll.aggregate(pipeline).to_list(length=None)

    per_admin: dict = {}
    for r in rows:
        uid = str(r["_id"]["user"])
        mode = r["_id"]["mode"] or "CASH"
        amt = float(to_decimal(r["amount"]))  # withdraws arrive negative
        n = int(r["count"])
        is_out = r["_id"]["type"] == TransactionType.ADMIN_WITHDRAW.value
        a = per_admin.setdefault(uid, {
            "total": 0.0, "count": 0, "by_mode": {},
            "in": 0.0, "out": 0.0, "in_count": 0, "out_count": 0,
            "by_mode_in": {}, "by_mode_out": {},
        })
        a["total"] += amt
        a["count"] += n
        a["by_mode"][mode] = a["by_mode"].get(mode, 0.0) + amt
        if is_out:
            # Report payouts as a positive magnitude — the direction is already
            # carried by the field name, and a "-1,000" under a heading that
            # says "Paid" reads as a double negative.
            a["out"] += -amt
            a["out_count"] += n
            a["by_mode_out"][mode] = a["by_mode_out"].get(mode, 0.0) + -amt
        else:
            a["in"] += amt
            a["in_count"] += n
            a["by_mode_in"][mode] = a["by_mode_in"].get(mode, 0.0) + amt

    users = {}
    if per_admin:
        for u in await User.find({"_id": {"$in": [PydanticObjectId(k) for k in per_admin]}}).to_list():
            users[str(u.id)] = u

    admins = []
    for uid, a in per_admin.items():
        u = users.get(uid)
        admins.append({
            "id": uid,
            "user_code": u.user_code if u else uid,
            "full_name": (u.full_name if u else None) or (u.user_code if u else uid),
            "total": round(a["total"], 2),
            "count": a["count"],
            "in": round(a["in"], 2),
            "out": round(a["out"], 2),
            "in_count": a["in_count"],
            "out_count": a["out_count"],
            "by_mode": {k: round(v, 2) for k, v in a["by_mode"].items()},
            "by_mode_in": {k: round(v, 2) for k, v in a["by_mode_in"].items()},
            "by_mode_out": {k: round(v, 2) for k, v in a["by_mode_out"].items()},
        })
    admins.sort(key=lambda x: x["total"], reverse=True)
    return {
        "total_generated": round(sum(a["total"] for a in admins), 2),
        "total_in": round(sum(a["in"] for a in admins), 2),
        "total_out": round(sum(a["out"] for a in admins), 2),
        "admins": admins,
    }


async def _serialize(rows: list[AdminFundRequest]) -> list[dict]:
    uids = {r.requester_id for r in rows} | {r.target_admin_id for r in rows}
    users = {}
    if uids:
        for u in await User.find({"_id": {"$in": list(uids)}}).to_list():
            users[str(u.id)] = u
    out = []
    for r in rows:
        req = users.get(str(r.requester_id))
        tgt = users.get(str(r.target_admin_id))
        out.append({
            "id": str(r.id),
            "amount": float(to_decimal(r.amount)),
            "reason": r.reason,
            "status": r.status.value if hasattr(r.status, "value") else str(r.status),
            "remarks": r.remarks,
            "requester_code": req.user_code if req else None,
            "requester_role": req.role.value if req else None,
            "target_code": tgt.user_code if tgt else None,
            "created_at": r.created_at,
        })
    return out
