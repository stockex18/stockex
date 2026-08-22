"""Kuber wallet — the SUPER_ADMIN-only house pool (mirrors D:\\Stockex kuberWallet.js).

A distributable pool (capped at 🪙100 cr) kept SEPARATE from the SA's personal
`available_balance`. It funds downstream franchise / patti payouts. When the SA
funds a downstream admin, part comes from `kuber_balance` (pooled) and part from
`available_balance` (personal), per the funding plan.

All money moves are atomic ($inc + version) and write a WalletTransaction row so
they stay visible in the existing admin money views. Only the SUPER_ADMIN wallet
uses these fields; everyone else keeps kuber_* at 0.
"""

from __future__ import annotations

import logging
from decimal import Decimal

from beanie import PydanticObjectId
from bson import Decimal128
from pymongo import ReturnDocument

from app.core.exceptions import InsufficientFundsError
from app.models.transaction import TransactionStatus, TransactionType, WalletTransaction
from app.models.wallet import Wallet
from app.services import wallet_service
from app.utils.decimal_utils import ZERO, quantize_money, to_decimal

logger = logging.getLogger(__name__)

# 🪙100 crore cap on the kuber pool (KUBER_WALLET_MAX_BALANCE in the reference).
KUBER_MAX = Decimal("1000000000")


async def _sa_wallet(sa_id: str | PydanticObjectId) -> Wallet:
    return await wallet_service.get_or_create(sa_id)


async def _kuber_ledger(uid, amount_signed, before, after, ttype, narration, actor_id=None) -> None:
    await WalletTransaction(
        user_id=PydanticObjectId(str(uid)),
        transaction_type=ttype,
        amount=Decimal128(str(quantize_money(to_decimal(amount_signed)))),
        balance_before=Decimal128(str(quantize_money(to_decimal(before)))),
        balance_after=Decimal128(str(quantize_money(to_decimal(after)))),
        reference_type="KUBER",
        narration=narration,
        status=TransactionStatus.COMPLETED,
        created_by=PydanticObjectId(str(actor_id)) if actor_id else None,
    ).insert()


async def summary(sa_id: str | PydanticObjectId) -> dict:
    w = await _sa_wallet(sa_id)
    return {
        "kuber_balance": str(to_decimal(w.kuber_balance)),
        "kuber_total_in": str(to_decimal(w.kuber_total_in)),
        "kuber_total_out": str(to_decimal(w.kuber_total_out)),
        "available_balance": str(to_decimal(w.available_balance)),
        "kuber_cap": str(KUBER_MAX),
    }


async def bootstrap_kuber_to_max(sa_id: str | PydanticObjectId, actor_id=None) -> dict:
    """Idempotently top the kuber pool up to the 🪙100 cr cap."""
    w = await _sa_wallet(sa_id)
    cur = to_decimal(w.kuber_balance)
    if cur >= KUBER_MAX:
        return {"kuber_balance": str(cur), "topped_up": "0"}
    delta = KUBER_MAX - cur
    coll = Wallet.get_motor_collection()
    upd = await coll.find_one_and_update(
        {"_id": w.id},
        {"$inc": {"kuber_balance": Decimal128(str(delta)), "kuber_total_in": Decimal128(str(delta)), "version": 1}},
        return_document=ReturnDocument.AFTER,
    )
    after = to_decimal(upd["kuber_balance"])
    await _kuber_ledger(w.user_id, delta, cur, after, TransactionType.KUBER_TOPUP,
                        "Kuber pool topped up to 🪙100 cr", actor_id)
    return {"kuber_balance": str(after), "topped_up": str(delta)}


async def transfer_main_to_kuber(sa_id, amount, actor_id=None) -> dict:
    amt = quantize_money(to_decimal(amount))
    if amt <= ZERO:
        raise ValueError("amount must be positive")
    w = await _sa_wallet(sa_id)
    if to_decimal(w.available_balance) < amt:
        raise InsufficientFundsError("Insufficient main-wallet balance")
    if to_decimal(w.kuber_balance) + amt > KUBER_MAX:
        raise ValueError("Transfer would exceed the 🪙100 cr kuber cap")
    # Debit main (visible in money views), then credit kuber.
    await wallet_service.adjust(sa_id, -amt, transaction_type=TransactionType.KUBER_TRANSFER,
                                narration="Main → Kuber pool", reference_type="KUBER", actor_id=actor_id)
    coll = Wallet.get_motor_collection()
    upd = await coll.find_one_and_update(
        {"_id": w.id},
        {"$inc": {"kuber_balance": Decimal128(str(amt)), "kuber_total_in": Decimal128(str(amt)), "version": 1}},
        return_document=ReturnDocument.AFTER,
    )
    after = to_decimal(upd["kuber_balance"])
    await _kuber_ledger(w.user_id, amt, after - amt, after, TransactionType.KUBER_TRANSFER,
                        "Main → Kuber pool (pool credit)", actor_id)
    return {"kuber_balance": str(after)}


async def transfer_kuber_to_main(sa_id, amount, actor_id=None) -> dict:
    amt = quantize_money(to_decimal(amount))
    if amt <= ZERO:
        raise ValueError("amount must be positive")
    w = await _sa_wallet(sa_id)
    coll = Wallet.get_motor_collection()
    upd = await coll.find_one_and_update(
        {"_id": w.id, "kuber_balance": {"$gte": Decimal128(str(amt))}},
        {"$inc": {"kuber_balance": Decimal128(str(-amt)), "kuber_total_out": Decimal128(str(amt)), "version": 1}},
        return_document=ReturnDocument.AFTER,
    )
    if upd is None:
        raise InsufficientFundsError("Insufficient kuber pool balance")
    after = to_decimal(upd["kuber_balance"])
    await _kuber_ledger(w.user_id, -amt, after + amt, after, TransactionType.KUBER_TRANSFER,
                        "Kuber pool → Main (pool debit)", actor_id)
    await wallet_service.adjust(sa_id, amt, transaction_type=TransactionType.KUBER_TRANSFER,
                                narration="Kuber pool → Main", reference_type="KUBER", actor_id=actor_id)
    return {"kuber_balance": str(after)}


def resolve_funding_plan_for_admin(admin) -> dict:
    """How much of a fund-out to a downstream admin comes from the kuber pool
    vs the SA's personal main wallet. Franchise/patti-specific percentages
    arrive with Phase C; default is 0 (fund from personal main)."""
    if getattr(admin, "is_franchise_root", False):
        return {"kuber_pct": 100.0}
    patti_pct = getattr(admin, "patti_child_pct", None)
    if patti_pct:
        return {"kuber_pct": float(patti_pct)}
    return {"kuber_pct": 0.0}


async def fund_admin_share_from_sa_wallets(
    sa_id, amount, kuber_pct, *, narration, actor_id=None, strict: bool = False
) -> dict:
    """Debit a fund-out split across the SA's kuber pool (`kuber_pct%`) and
    personal main wallet (rest). Falls back to personal for any kuber shortfall.
    Used by the inter-admin fund flow (Phase B) + patti funding (Phase C).

    `strict` turns that fallback off. When the SA has explicitly PICKED which
    wallet to fund from, quietly taking the money out of the other one defeats
    the point of asking — so say the pool is short instead.
    """
    amt = quantize_money(to_decimal(amount))
    if amt <= ZERO:
        return {"kuber": "0", "personal": "0"}
    kuber_part = quantize_money(amt * to_decimal(kuber_pct) / to_decimal(100))
    personal_part = quantize_money(amt - kuber_part)
    w = await _sa_wallet(sa_id)

    if kuber_part > ZERO:
        coll = Wallet.get_motor_collection()
        upd = await coll.find_one_and_update(
            {"_id": w.id, "kuber_balance": {"$gte": Decimal128(str(kuber_part))}},
            {"$inc": {"kuber_balance": Decimal128(str(-kuber_part)), "kuber_total_out": Decimal128(str(kuber_part)), "version": 1}},
            return_document=ReturnDocument.AFTER,
        )
        if upd is None:
            if strict:
                raise InsufficientFundsError(
                    "Kuber pool is short of " + str(kuber_part)
                )
            # Not enough in kuber → fund the whole thing from personal.
            personal_part = amt
            kuber_part = ZERO
        else:
            after = to_decimal(upd["kuber_balance"])
            await _kuber_ledger(w.user_id, -kuber_part, after + kuber_part, after,
                                TransactionType.ADMIN_TRANSFER, f"{narration} (kuber part)", actor_id)

    if personal_part > ZERO:
        await wallet_service.adjust(sa_id, -personal_part, transaction_type=TransactionType.ADMIN_TRANSFER,
                                    narration=f"{narration} (personal part)", reference_type="ADMIN_FUND", actor_id=actor_id)

    return {"kuber": str(kuber_part), "personal": str(personal_part)}
