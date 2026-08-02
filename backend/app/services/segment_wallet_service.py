"""Per-segment trading wallet money service (multi-wallet — wallet.md).

Mirrors `wallet_service` primitives (atomic, version/`$expr`-guarded) but keyed
by (user_id, kind) on `SegmentWallet`. MAIN is the existing `Wallet` (handled
via `wallet_service`); this module handles NSE_BSE / MCX / CRYPTO / FOREX.

Golden rule: only free balance (`available_balance − used_margin`) can transfer;
locked margin stays put. Never let a wallet go negative.
"""

from __future__ import annotations

import asyncio
import logging
from decimal import Decimal
from typing import Any

from beanie import PydanticObjectId
from bson import Decimal128
from pymongo import ReturnDocument

from app.core.config import settings
from app.core.exceptions import InsufficientFundsError
from app.core.redis_client import publish
from app.models.segment_wallet import SegmentWallet
from app.models.transaction import TransactionStatus, TransactionType, WalletTransaction
from app.models.wallet import Wallet
from app.services import wallet_kinds, wallet_service
from app.utils.decimal_utils import ZERO, add, quantize_money, sub, to_decimal, to_decimal128
from app.utils.time_utils import now_utc

logger = logging.getLogger(__name__)


def _require_segment_kind(kind: str, op: str) -> None:
    """PERMANENT SAFETY GUARD — a segment-wallet money op (margin / P&L) may
    only ever touch one of the 4 trading segment wallets (NSE_BSE / MCX /
    CRYPTO / FOREX), never MAIN / GAMES / a malformed kind. Defence-in-depth
    behind `wallet_router`: even a direct caller can't move one segment's
    money into another wallet by mistake."""
    if kind not in wallet_kinds.SEGMENT_KINDS:
        logger.critical("segment_wallet_bad_kind op=%s kind=%s", op, kind)
        raise ValueError(
            f"segment_wallet.{op}: refusing a money op on non-segment wallet kind {kind!r}"
        )


async def get_or_create(user_id: str | PydanticObjectId, kind: str) -> SegmentWallet:
    uid = PydanticObjectId(str(user_id))
    w = await SegmentWallet.find_one(SegmentWallet.user_id == uid, SegmentWallet.kind == kind)
    if w is None:
        w = SegmentWallet(user_id=uid, kind=kind)
        try:
            await w.insert()
        except Exception:
            w = await SegmentWallet.find_one(SegmentWallet.user_id == uid, SegmentWallet.kind == kind)
            if w is None:
                raise
    return w


async def _publish(user_id, kind: str, *, reason: str, amount: Decimal, balance_after: Decimal) -> None:
    try:
        await publish(
            f"user:{user_id}:wallet",
            {"type": "wallet", "payload": {"reason": reason, "wallet_kind": kind,
                                            "amount": str(amount), "balance_after": str(balance_after)}},
        )
    except Exception:
        logger.debug("segment_wallet_publish_failed user=%s kind=%s", user_id, kind, exc_info=True)


async def segment_float_pnl(user_id: str | PydanticObjectId, kind: str) -> Decimal:
    """Live floating P&L across the user's OPEN positions in this wallet kind.
    Counts toward free-margin buying power (dabba/CFD): a floating PROFIT lets
    the user open more, a floating LOSS reduces what they can open."""
    from app.models.position import Position, PositionStatus

    segs = wallet_kinds.segments_for_kind(kind)
    if not segs:
        return ZERO
    rows = await Position.find(
        {
            "user_id": PydanticObjectId(str(user_id)),
            "status": PositionStatus.OPEN.value,
            "instrument.segment": {"$in": segs},
        }
    ).to_list()
    return sum((to_decimal(p.unrealized_pnl) for p in rows), ZERO)


# ── Margin (no ledger — internal lock, mirrors wallet_service.block_margin) ──
async def block_margin(user_id: str | PydanticObjectId, kind: str, amount: Decimal | float) -> None:
    _require_segment_kind(kind, "block_margin")
    amt = quantize_money(to_decimal(amount))
    if amt <= ZERO:
        return
    await get_or_create(user_id, kind)
    uid = PydanticObjectId(str(user_id))
    # FREE-MARGIN (dabba/CFD): the segment's live floating P&L is buying power.
    # Cash actually needed = margin − float_pnl (a profit lowers it — even lets
    # available go negative, backed by the unrealized gain; a loss raises it).
    # The lock still shifts the FULL margin available→used, so the stop-out
    # denominator (available + used + credit) is invariant and stays at real
    # capital — protection is unchanged (see risk_enforcer._denominator).
    float_pnl = await segment_float_pnl(uid, kind)
    cash_needed = amt - float_pnl
    amt128 = to_decimal128(amt)
    neg128 = to_decimal128(ZERO - amt)
    threshold128 = to_decimal128(cash_needed)
    zero128 = Decimal128("0")
    updated = await SegmentWallet.get_motor_collection().find_one_and_update(
        {
            "user_id": uid, "kind": kind,
            "$expr": {"$gte": [
                {"$add": [{"$ifNull": ["$available_balance", zero128]}, {"$ifNull": ["$credit_limit", zero128]}]},
                threshold128,
            ]},
        },
        {"$inc": {"available_balance": neg128, "used_margin": amt128, "version": 1}},
        return_document=ReturnDocument.AFTER,
    )
    if updated is None:
        w = await get_or_create(user_id, kind)
        raise InsufficientFundsError(
            f"Insufficient {wallet_kinds.LABELS.get(kind, kind)} margin: have 🪙{w.available_balance} "
            f"(+credit 🪙{w.credit_limit}, +float 🪙{quantize_money(float_pnl)}), need 🪙{amt}"
        )


async def release_margin(user_id: str | PydanticObjectId, kind: str, amount: Decimal | float) -> None:
    _require_segment_kind(kind, "release_margin")
    amt = quantize_money(to_decimal(amount))
    if amt <= ZERO:
        return
    coll = SegmentWallet.get_motor_collection()
    for _ in range(8):
        w = await get_or_create(user_id, kind)
        actual = min(amt, to_decimal(w.used_margin))
        if actual <= ZERO:
            return
        res = await coll.update_one(
            {"_id": w.id, "version": w.version},
            {"$set": {
                "used_margin": to_decimal128(sub(w.used_margin, actual)),
                "available_balance": to_decimal128(add(w.available_balance, actual)),
            }, "$inc": {"version": 1}},
        )
        if res.modified_count == 1:
            return
    logger.error("segment_release_margin_contended user=%s kind=%s", user_id, kind)


# ── Signed balance adjust (writes a WalletTransaction tagged with kind) ──
async def _kind_auto_settlement_on(user_id: str | PydanticObjectId, kind: str) -> bool:
    """Whether THIS segment wallet auto-settles (floors at 0 + books to
    settlement_outstanding) for the user's owning admin. Default True (floor).
    When the owning admin has turned auto-settlement OFF for this wallet kind
    (`pool_auto_settlement_kinds[kind] = False`), returns False → the segment
    wallet is allowed to go NEGATIVE instead of flooring. Resolved live so it
    covers all current + future users; only ever called on the below-zero path
    so it adds no overhead to normal credits/debits. Fails SAFE (True = floor)."""
    try:
        from app.models.user import User, UserRole

        u = await User.get(PydanticObjectId(str(user_id)))
        if u is None:
            return True
        owner = await User.get(u.assigned_admin_id) if u.assigned_admin_id else None
        if owner is None:
            owner = await User.find_one(User.role == UserRole.SUPER_ADMIN)
        if owner is None:
            return True
        kinds = getattr(owner, "pool_auto_settlement_kinds", None) or {}
        return bool(kinds.get(kind, True))
    except Exception:
        return True


async def _cover_from_main(user_id: str | PydanticObjectId, kind: str) -> None:
    """Auto-cover a segment wallet's shortfall from the user's MAIN cash wallet.

    When a trading (segment) wallet's loss exceeds its balance it either floors
    to 0 (booking ``settlement_outstanding``, auto-settlement ON) or goes
    NEGATIVE (auto-settlement OFF). Either way the user still owes the shortfall.
    Since the MAIN wallet is where deposits land and trading wallets are funded
    FROM it, pull the shortfall out of MAIN automatically when it has cash — so a
    trading wallet dipping into minus is covered from available cash first.

    Pulls only what MAIN can afford (never drives MAIN negative); any remainder
    stays as the segment wallet's shortfall (settlement / negative balance).
    No-op when the feature is off, MAIN is empty, or there's nothing to cover.
    Best-effort: never raises into the caller's settlement path.
    """
    if not settings.SEGMENT_SHORTFALL_COVER_FROM_MAIN:
        return
    try:
        # 1) How much is owed, and how much MAIN can spare right now.
        w = await get_or_create(user_id, kind)
        outstanding = to_decimal(w.settlement_outstanding)
        avail = to_decimal(w.available_balance)
        shortfall = add(outstanding, (-avail) if avail < ZERO else ZERO)
        if shortfall <= ZERO:
            return
        mw = await wallet_service.get_or_create(user_id)
        main_avail = to_decimal(mw.available_balance)
        if main_avail <= ZERO:
            return
        cover = quantize_money(min(shortfall, main_avail))
        if cover <= ZERO:
            return

        # 2) Debit MAIN once (atomic + version-guarded inside wallet_service).
        #    cover ≤ main_avail, so MAIN never floors/goes negative.
        await wallet_service.adjust(
            user_id, -cover, transaction_type=TransactionType.WALLET_TRANSFER,
            narration=f"Auto-cover {kind} shortfall from main wallet",
            reference_type=f"WALLET:{kind}",
        )

        # 3) Apply the SAME cover to the segment wallet (pay down settlement
        #    first, then raise a negative available back toward 0), version-
        #    guarded. Refund MAIN if we somehow can't land it.
        coll = SegmentWallet.get_motor_collection()
        for _attempt in range(12):
            w = await get_or_create(user_id, kind)
            outstanding = to_decimal(w.settlement_outstanding)
            avail = to_decimal(w.available_balance)
            # Raise a NEGATIVE available back toward 0 FIRST (that's the minus the
            # user sees on the wallet card), then pay down any settlement booking.
            neg = (-avail) if avail < ZERO else ZERO
            pay_neg = quantize_money(min(cover, neg))
            remainder = sub(cover, pay_neg)
            pay_settle = quantize_money(min(remainder, outstanding if outstanding > ZERO else ZERO))
            updated = await coll.find_one_and_update(
                {"_id": w.id, "version": w.version},
                {"$set": {
                    "available_balance": to_decimal128(add(avail, pay_neg)),
                    "settlement_outstanding": to_decimal128(sub(outstanding, pay_settle)),
                    "version": (w.version or 0) + 1,
                }},
                return_document=ReturnDocument.AFTER,
            )
            if updated is not None:
                new_available = to_decimal(updated.get("available_balance"))
                try:
                    await WalletTransaction(
                        user_id=PydanticObjectId(str(user_id)),
                        transaction_type=TransactionType.WALLET_TRANSFER,
                        amount=Decimal128(str(cover)),
                        balance_before=Decimal128(str(avail)),
                        balance_after=Decimal128(str(new_available)),
                        reference_type=f"WALLET:{kind}",
                        narration="Auto-cover from main wallet",
                        status=TransactionStatus.COMPLETED,
                    ).insert()
                except Exception:  # noqa: BLE001
                    logger.debug("cover_from_main_txn_failed", exc_info=True)
                asyncio.create_task(
                    _publish(user_id, kind, reason="AUTO_COVER", amount=cover, balance_after=new_available)
                )
                return
            await asyncio.sleep(0.015 * (_attempt + 1))
        # Couldn't land the segment credit — refund MAIN so the books balance.
        await wallet_service.adjust(
            user_id, cover, transaction_type=TransactionType.WALLET_TRANSFER,
            narration=f"Auto-cover refund ({kind})",
        )
    except Exception:  # noqa: BLE001 — never let auto-cover break settlement
        logger.exception("cover_from_main_failed user=%s kind=%s", user_id, kind)


async def adjust(
    user_id: str | PydanticObjectId, kind: str, amount: Decimal | float | int | str, *,
    transaction_type: TransactionType, narration: str,
    reference_type: str | None = None, reference_id: str | None = None,
    actor_id: str | PydanticObjectId | None = None, allow_negative: bool = False,
) -> WalletTransaction:
    _require_segment_kind(kind, "adjust")
    amt = quantize_money(to_decimal(amount))
    coll = SegmentWallet.get_motor_collection()
    before = after = ZERO
    breached = False  # this debit took the wallet below zero (floor OR negative)
    for _attempt in range(12):
        w = await get_or_create(user_id, kind)
        before = to_decimal(w.available_balance)
        after = add(before, amt)
        # Below-zero shortfall: floor at 0 + book to settlement (default), UNLESS
        # the owning admin turned auto-settlement OFF for this segment wallet —
        # then let `available_balance` go NEGATIVE (mines), like the main wallet's
        # auto_settlement=OFF flow. `allow_negative` (internal transfer-revert etc.)
        # still bypasses flooring outright.
        breached = after < ZERO and not allow_negative
        floor_this = breached
        if floor_this and not await _kind_auto_settlement_on(user_id, kind):
            floor_this = False
        if floor_this:
            # Debit available all the way down to 0; the shortfall that the
            # wallet can't cover overflows to settlement_outstanding (mirrors
            # the main wallet). `available` is always floored ≥ 0, so `before`
            # is the amount actually absorbed and `-after` (after is negative
            # here) is exactly the uncovered remainder.
            #
            # BUG (fixed 2026-07-02): the old `after = max(before, 0)` left
            # available UNCHANGED when before > 0 — so a stop-out loss bigger
            # than the balance booked the overflow to settlement but never
            # actually cut the wallet. It must go to 0.
            booked = -after  # uncovered remainder → settlement
            after = ZERO
            set_fields: dict[str, Any] = {
                "available_balance": to_decimal128(after),
                "settlement_outstanding": to_decimal128(add(to_decimal(w.settlement_outstanding), booked)),
                "version": (w.version or 0) + 1,
            }
        else:
            set_fields = {"available_balance": to_decimal128(after), "version": (w.version or 0) + 1}
        if transaction_type == TransactionType.PNL:
            set_fields["realized_pnl"] = to_decimal128(add(w.realized_pnl, amt))
        updated = await coll.find_one_and_update(
            {"_id": w.id, "version": w.version}, {"$set": set_fields},
            return_document=ReturnDocument.AFTER,
        )
        if updated is not None:
            after = to_decimal(updated.get("available_balance"))
            break
        await asyncio.sleep(0.015 * (_attempt + 1))
    else:
        raise RuntimeError("segment adjust: too much contention")

    txn = WalletTransaction(
        user_id=PydanticObjectId(str(user_id)), transaction_type=transaction_type,
        amount=Decimal128(str(after - before)), balance_before=Decimal128(str(before)),
        balance_after=Decimal128(str(after)), reference_type=reference_type or f"WALLET:{kind}",
        reference_id=reference_id, narration=narration, status=TransactionStatus.COMPLETED,
        created_by=PydanticObjectId(str(actor_id)) if actor_id else None,
    )
    await txn.insert()
    asyncio.create_task(_publish(user_id, kind, reason=transaction_type.value, amount=amt, balance_after=after))
    # This debit pushed the trading wallet below zero — auto-cover the shortfall
    # from the user's MAIN cash wallet (if it has funds) before it lingers as a
    # settlement / negative balance. Best-effort; never fails the debit.
    if breached and amt < ZERO:
        await _cover_from_main(user_id, kind)
    return txn


# ── Read helpers ──────────────────────────────────────────────────────
async def summary(user_id: str | PydanticObjectId, kind: str) -> dict[str, Any]:
    w = await get_or_create(user_id, kind)
    avail = to_decimal(w.available_balance)
    used = to_decimal(w.used_margin)
    bal = add(avail, used)
    return {
        "kind": kind, "label": wallet_kinds.LABELS.get(kind, kind),
        "available_balance": str(avail), "used_margin": str(used),
        "balance": str(bal), "equity": str(add(bal, to_decimal(w.unrealized_pnl))),
        "credit_limit": str(w.credit_limit), "profit_blocked": w.profit_blocked,
        "settlement_outstanding": str(w.settlement_outstanding),
    }


async def list_all(user_id: str | PydanticObjectId) -> list[dict[str, Any]]:
    """MAIN (from main Wallet) + the 4 segment wallets."""
    out: list[dict[str, Any]] = []
    mw = await wallet_service.get_or_create(user_id)
    out.append({
        "kind": wallet_kinds.MAIN, "label": "Main",
        "available_balance": str(mw.available_balance), "used_margin": "0",
        "balance": str(mw.available_balance), "equity": str(mw.available_balance),
        "credit_limit": str(mw.credit_limit), "profit_blocked": False,
        "settlement_outstanding": str(mw.settlement_outstanding),
    })
    for kind in wallet_kinds.SEGMENT_KINDS:
        out.append(await summary(user_id, kind))
    return out


# ── Transfers (Main ↔ segment, segment ↔ segment) ──────────────────────
async def _transferable(user_id, kind: str) -> Decimal:
    if kind == wallet_kinds.MAIN:
        mw = await wallet_service.get_or_create(user_id)
        return to_decimal(mw.available_balance)
    # `available_balance` IS the free balance — block_margin already MOVES the
    # locked amount out of available and into used_margin (see block_margin).
    # Subtracting used_margin again here double-counted it, so a user with, say,
    # ₹16,138 free + ₹1,012 locked could only transfer ₹15,126 (the locked part
    # was withheld twice). Return available_balance directly, exactly like MAIN.
    w = await get_or_create(user_id, kind)
    return to_decimal(w.available_balance)


async def transfer(
    user_id: str | PydanticObjectId, from_kind: str, to_kind: str, amount: Decimal | float | int | str,
) -> dict[str, Any]:
    amt = quantize_money(to_decimal(amount))
    if amt <= ZERO:
        raise ValueError("amount must be positive")
    if from_kind == to_kind:
        raise ValueError("source and target must differ")
    if not (wallet_kinds.is_valid_kind(from_kind) and wallet_kinds.is_valid_kind(to_kind)):
        raise ValueError("invalid wallet")

    if await _transferable(user_id, from_kind) < amt:
        raise InsufficientFundsError(
            f"Only free balance can transfer from {wallet_kinds.LABELS.get(from_kind, from_kind)}"
        )

    ref = f"{from_kind}->{to_kind}"
    # Debit source.
    if from_kind == wallet_kinds.MAIN:
        await wallet_service.adjust(user_id, -amt, transaction_type=TransactionType.WALLET_TRANSFER,
                                    narration=f"Transfer to {wallet_kinds.LABELS.get(to_kind, to_kind)} wallet",
                                    reference_type="WALLET_TRANSFER", reference_id=ref)
    else:
        await adjust(user_id, from_kind, -amt, transaction_type=TransactionType.WALLET_TRANSFER,
                     narration=f"Transfer to {wallet_kinds.LABELS.get(to_kind, to_kind)} wallet",
                     reference_id=ref)
    # Credit target (revert source on failure).
    try:
        if to_kind == wallet_kinds.MAIN:
            await wallet_service.adjust(user_id, amt, transaction_type=TransactionType.WALLET_TRANSFER,
                                        narration=f"Transfer from {wallet_kinds.LABELS.get(from_kind, from_kind)} wallet",
                                        reference_type="WALLET_TRANSFER", reference_id=ref)
        else:
            await adjust(user_id, to_kind, amt, transaction_type=TransactionType.WALLET_TRANSFER,
                         narration=f"Transfer from {wallet_kinds.LABELS.get(from_kind, from_kind)} wallet",
                         reference_id=ref, allow_negative=True)
    except Exception:
        if from_kind == wallet_kinds.MAIN:
            await wallet_service.adjust(user_id, amt, transaction_type=TransactionType.WALLET_TRANSFER,
                                        narration="Reverted failed transfer", reference_type="WALLET_TRANSFER")
        else:
            await adjust(user_id, from_kind, amt, transaction_type=TransactionType.WALLET_TRANSFER,
                         narration="Reverted failed transfer", allow_negative=True)
        raise
    return {"from": from_kind, "to": to_kind, "amount": str(amt)}
