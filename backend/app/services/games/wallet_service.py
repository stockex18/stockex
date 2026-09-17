"""Games wallet money primitives.

Design (v1):
  • SUPER_ADMIN main wallet is the HOUSE. Stakes flow to it, wins are funded
    from it (via the trading `wallet_service.adjust` with GAMES_HOUSE_SETTLE so
    real cash + house solvency stay visible in existing admin money views).
  • Games-wallet debits are ATOMIC + NON-NEGATIVE (server-side `$expr` guard,
    same pattern as `wallet_service.block_margin`).
  • main → games transfer is INSTANT; games → main is ADMIN-APPROVED (request).

Nothing here mutates the trading `Wallet` except through the public
`wallet_service.adjust`, so existing trading/wallet behavior is untouched.
"""

from __future__ import annotations

import asyncio
import logging
from decimal import Decimal
from typing import Any

from beanie import PydanticObjectId
from bson import Decimal128
from pymongo import ReturnDocument

from app.core.exceptions import (
    GameDisabledError,
    InsufficientFundsError,
    InsufficientGamesFundsError,
    NotFoundError,
)
from app.core.redis_client import publish
from app.models.games.wallet import (
    GamesLedgerEntryType,
    GamesWallet,
    GamesWalletLedger,
)
from app.models.transaction import TransactionType
from app.models.games.transfer import GamesWithdrawalRequest, GamesWithdrawalStatus
from app.models.wallet import Wallet
from app.services import wallet_service
from app.utils.decimal_utils import ZERO, add, quantize_money, to_decimal, to_decimal128
from app.utils.time_utils import now_utc

logger = logging.getLogger(__name__)


# ── Wallet accessors ─────────────────────────────────────────────────
async def get_or_create(user_id: str | PydanticObjectId) -> GamesWallet:
    uid = PydanticObjectId(str(user_id))
    w = await GamesWallet.find_one(GamesWallet.user_id == uid)
    if w is None:
        w = GamesWallet(user_id=uid)
        try:
            await w.insert()
        except Exception:
            w = await GamesWallet.find_one(GamesWallet.user_id == uid)
            if w is None:
                raise
    return w


async def get_balance(user_id: str | PydanticObjectId) -> Decimal:
    w = await get_or_create(user_id)
    return to_decimal(w.balance)


async def _publish_games_event(
    user_id: str | PydanticObjectId, *, reason: str, amount: Decimal, balance_after: Decimal
) -> None:
    try:
        await publish(
            f"user:{user_id}:games",
            {
                "type": "games_balance_changed",
                "payload": {
                    "reason": reason,
                    "amount": str(amount),
                    "balance_after": str(balance_after),
                },
            },
        )
    except Exception:  # noqa: BLE001 — best-effort
        logger.debug("games_wallet_publish_failed user=%s", user_id, exc_info=True)


async def _record_ledger(
    owner_id: PydanticObjectId,
    entry_type: GamesLedgerEntryType,
    amount: Decimal,
    balance_after: Decimal,
    *,
    game_key: str | None,
    description: str,
    meta: dict | None = None,
) -> GamesWalletLedger:
    row = GamesWalletLedger(
        owner_id=owner_id,
        entry_type=entry_type,
        amount=to_decimal128(amount),
        balance_after=to_decimal128(balance_after),
        game_key=game_key,
        description=description,
        meta=meta or {},
    )
    await row.insert()
    return row


# ── Atomic, non-negative debit ────────────────────────────────────────
async def atomic_games_wallet_debit(
    user_id: str | PydanticObjectId,
    amount: Decimal | float | int | str,
    *,
    game_key: str | None,
    description: str,
    meta: dict | None = None,
) -> GamesWallet:
    """Debit `amount` from the games wallet. Atomic + never goes negative
    (server evaluates the `$expr` sufficiency guard and applies the decrement
    in one op, so concurrent bets serialize on the doc). Raises
    InsufficientGamesFundsError when the balance can't cover it."""
    amt = quantize_money(to_decimal(amount))
    if amt <= ZERO:
        raise ValueError("debit amount must be positive")

    # A STAKE carries a game_key; a transfer or withdrawal does not. So this
    # gate sits on every game in one place and leaves a user's own money alone:
    # once their admin's security is spent past the cap, the betting stops but
    # moving the balance back to main does not. Operator: "game bhi play mat
    # kar paye."
    if game_key:
        from app.models.user import User as _User
        from app.services import admin_security_service as _sec

        _u = await _User.get(PydanticObjectId(str(user_id)))
        _cap = await _sec.blocked_for_user(_u) if _u is not None else None
        if _cap is not None:
            raise GameDisabledError(
                f"Games are paused on this account — your admin's security is "
                f"{_cap['used_pct']}% used, past the {_cap['cap_pct']}% limit."
            )

    await get_or_create(user_id)
    uid = PydanticObjectId(str(user_id))
    coll = GamesWallet.get_motor_collection()
    amt128 = to_decimal128(amt)
    neg128 = to_decimal128(ZERO - amt)
    zero128 = Decimal128("0")
    updated = await coll.find_one_and_update(
        {
            "user_id": uid,
            "$expr": {
                "$gte": [{"$ifNull": [{"$toDecimal": "$balance"}, zero128]}, amt128]
            },
        },
        {"$inc": {"balance": neg128, "version": 1}},
        return_document=ReturnDocument.AFTER,
    )
    if updated is None:
        w = await get_or_create(user_id)
        raise InsufficientGamesFundsError(
            f"Insufficient games balance: have 🪙{w.balance}, need 🪙{amt}"
        )
    balance_after = to_decimal(updated.get("balance"))
    await _record_ledger(
        uid, GamesLedgerEntryType.DEBIT, amt, balance_after,
        game_key=game_key, description=description, meta=meta,
    )
    asyncio.create_task(
        _publish_games_event(uid, reason="DEBIT", amount=-amt, balance_after=balance_after)
    )
    return await get_or_create(uid)


async def atomic_games_wallet_credit(
    user_id: str | PydanticObjectId,
    amount: Decimal | float | int | str,
    *,
    game_key: str | None,
    description: str,
    meta: dict | None = None,
    is_win: bool = False,
) -> GamesWallet:
    """Credit `amount` to the games wallet. When `is_win` and the wallet has
    `profit_blocked` set, the credit is SKIPPED (risk lever) but a zero-amount
    audit row is written so the block is visible in the ledger."""
    amt = quantize_money(to_decimal(amount))
    if amt < ZERO:
        raise ValueError("credit amount must be non-negative")
    uid = PydanticObjectId(str(user_id))
    w = await get_or_create(uid)

    if is_win and w.profit_blocked:
        await _record_ledger(
            uid, GamesLedgerEntryType.CREDIT, ZERO, to_decimal(w.balance),
            game_key=game_key,
            description=f"{description} — BLOCKED (profit_blocked)",
            meta={**(meta or {}), "blocked": True, "intended_amount": str(amt)},
        )
        return w

    if amt == ZERO:
        return w

    coll = GamesWallet.get_motor_collection()
    updated = await coll.find_one_and_update(
        {"user_id": uid},
        {"$inc": {"balance": to_decimal128(amt), "version": 1}},
        return_document=ReturnDocument.AFTER,
    )
    balance_after = to_decimal(updated.get("balance"))
    await _record_ledger(
        uid, GamesLedgerEntryType.CREDIT, amt, balance_after,
        game_key=game_key, description=description, meta=meta,
    )
    asyncio.create_task(
        _publish_games_event(uid, reason="CREDIT", amount=amt, balance_after=balance_after)
    )
    return await get_or_create(uid)


# ── House (SUPER_ADMIN main wallet) settlement ─────────────────────────
async def _is_demo_user(user_id: str | PydanticObjectId | None) -> bool:
    """True when `user_id` is a DEMO account. Demo play is virtual — it must
    never move real money on the house wallet. Not cached: demo→real conversion
    must take effect immediately, and games aren't hot enough for a User.get to
    matter."""
    if user_id is None:
        return False
    try:
        from app.models.user import User

        u = await User.get(PydanticObjectId(str(user_id)))
        return bool(getattr(u, "is_demo", False)) if u is not None else False
    except Exception:  # noqa: BLE001
        return False


async def house_settle(
    signed_amount: Decimal | float | int | str,
    *,
    game_key: str,
    narration: str,
    reference_id: str | None = None,
    user_id: str | PydanticObjectId | None = None,
) -> None:
    """Move money on the SUPER_ADMIN's MAIN wallet (the house pool).

    signed_amount > 0 → house COLLECTS (a losing stake flows in).
    signed_amount < 0 → house FUNDS (a win is paid out).

    `user_id` (when passed) is the player this settle originates from — if that
    account is DEMO the call is a NO-OP, so virtual demo play never touches the
    real house wallet / games-net. System-level settles omit it and always apply.

    Best-effort: the user payout must NEVER be gated on house solvency, so a
    failure here is logged but not raised. The house may go negative — that
    surfaces as the super-admin's `settlement_outstanding` (auto-settle path)."""
    from app.services import netting_service

    amt = quantize_money(to_decimal(signed_amount))
    if amt == ZERO:
        return
    if await _is_demo_user(user_id):
        logger.debug("games_house_settle_skipped_demo game=%s user=%s", game_key, user_id)
        return
    try:
        sa_id = await netting_service._resolve_super_admin_id()
        if sa_id is None:
            logger.warning("games_house_settle_no_super_admin game=%s", game_key)
            return
        await wallet_service.adjust(
            sa_id,
            amt,
            transaction_type=TransactionType.GAMES_HOUSE_SETTLE,
            narration=narration,
            reference_type="GAMES_HOUSE",
            reference_id=reference_id or game_key,
        )
    except Exception:  # noqa: BLE001 — never block a user payout on the house
        logger.exception("games_house_settle_failed game=%s amount=%s", game_key, amt)

    # Mirror the same settle onto the player's owning admin's SECURITY money —
    # the collateral that admin lodged against their own book's games exposure.
    # Same sign as the house: it collected (player lost) -> security up; it paid
    # out (player won) -> security down.
    #
    # Deliberately OUTSIDE the try above, so a house-wallet failure does not
    # skip the collateral entry and vice versa; the hook swallows its own
    # errors. Demo players and users with no owning admin are no-ops inside it.
    from app.services import admin_security_service

    await admin_security_service.apply_games_result(
        user_id, amt, game_key=game_key, narration=narration
    )


# ── main → games (instant) ─────────────────────────────────────────────
async def transfer_main_to_games(
    user_id: str | PydanticObjectId, amount: Decimal | float | int | str
) -> dict[str, Any]:
    amt = quantize_money(to_decimal(amount))
    if amt <= ZERO:
        raise ValueError("transfer amount must be positive")

    # Pre-validate main balance BEFORE adjust so a short wallet is rejected
    # cleanly (never books settlement via the GAMES_TRANSFER_IN path).
    mw = await wallet_service.get_or_create(user_id)
    if to_decimal(mw.available_balance) < amt:
        raise InsufficientFundsError(
            f"Insufficient main-wallet balance: available 🪙{mw.available_balance}, need 🪙{amt}"
        )

    await wallet_service.adjust(
        user_id, -amt,
        transaction_type=TransactionType.GAMES_TRANSFER_IN,
        narration="Transfer to games wallet",
        reference_type="GAMES_WALLET",
    )
    try:
        w = await atomic_games_wallet_credit(
            user_id, amt, game_key=None,
            description="Transfer in from main wallet",
            meta={"kind": "TRANSFER_IN"},
        )
    except Exception:
        # Revert the main debit so money is never destroyed.
        await wallet_service.adjust(
            user_id, amt,
            transaction_type=TransactionType.GAMES_TRANSFER_OUT,
            narration="Reverted failed games transfer-in",
            reference_type="GAMES_WALLET",
        )
        raise
    return {"games_balance": str(w.balance)}


# ── games → main (INSTANT, no admin approval) ──────────────────────────
async def transfer_games_to_main(
    user_id: str | PydanticObjectId, amount: Decimal | float | int | str
) -> dict[str, Any]:
    """Move free games balance straight back to the MAIN wallet — INSTANT, no
    admin approval. Safe because a placed bet's stake is DEBITED from the games
    balance immediately (v1), so `balance` is already the FREE amount: money
    locked in an active ticket isn't in it and can't be pulled out here. Mirror
    of `transfer_main_to_games` in reverse; reverts the games debit if the main
    credit fails so money is never destroyed."""
    amt = quantize_money(to_decimal(amount))
    if amt <= ZERO:
        raise ValueError("transfer amount must be positive")

    bal = await get_balance(user_id)
    if bal < amt:
        raise InsufficientGamesFundsError(
            f"Insufficient games balance: available 🪙{bal}, requested 🪙{amt}"
        )

    w = await atomic_games_wallet_debit(
        user_id, amt, game_key=None,
        description="Transfer out to main wallet",
        meta={"kind": "TRANSFER_OUT"},
    )
    try:
        await wallet_service.adjust(
            user_id, amt,
            transaction_type=TransactionType.GAMES_TRANSFER_OUT,
            narration="Transfer from games wallet",
            reference_type="GAMES_WALLET",
        )
    except Exception:
        # Main credit failed — return the money to the games wallet.
        await atomic_games_wallet_credit(
            user_id, amt, game_key=None,
            description="Reverted failed games → main transfer",
            meta={"kind": "TRANSFER_OUT_REVERT"},
        )
        raise
    return {"games_balance": str(w.balance)}


# ── games → main (admin-approved request) ──────────────────────────────
async def create_games_withdrawal(
    user_id: str | PydanticObjectId, amount: Decimal | float | int | str, remark: str | None = None
) -> GamesWithdrawalRequest:
    amt = quantize_money(to_decimal(amount))
    if amt <= ZERO:
        raise ValueError("amount must be positive")
    uid = PydanticObjectId(str(user_id))

    bal = await get_balance(uid)
    if bal < amt:
        raise InsufficientGamesFundsError(
            f"Insufficient games balance: available 🪙{bal}, requested 🪙{amt}"
        )
    existing = await GamesWithdrawalRequest.find_one(
        GamesWithdrawalRequest.user_id == uid,
        GamesWithdrawalRequest.status == GamesWithdrawalStatus.PENDING,
    )
    if existing is not None:
        raise InsufficientGamesFundsError(
            "You already have a pending games → main transfer request"
        )
    req = GamesWithdrawalRequest(
        user_id=uid, amount=to_decimal128(amt), user_remark=remark,
        status=GamesWithdrawalStatus.PENDING,
    )
    await req.insert()
    return req


async def approve_games_withdrawal(
    request_id: str | PydanticObjectId, admin_id: PydanticObjectId, admin_remark: str | None = None
) -> dict[str, Any]:
    """Atomic-claim the PENDING request, debit games wallet, credit main
    wallet, revert the games debit on main-credit failure."""
    coll = GamesWithdrawalRequest.get_motor_collection()
    claimed = await coll.find_one_and_update(
        {"_id": PydanticObjectId(str(request_id)), "status": GamesWithdrawalStatus.PENDING.value},
        {
            "$set": {
                "status": GamesWithdrawalStatus.APPROVED.value,
                "processed_by": admin_id,
                "processed_at": now_utc(),
                "admin_remark": admin_remark,
                "updated_at": now_utc(),
            }
        },
        return_document=ReturnDocument.AFTER,
    )
    if claimed is None:
        raise NotFoundError("Request not found or already processed")

    uid = claimed["user_id"]
    amt = to_decimal(claimed["amount"])
    try:
        await atomic_games_wallet_debit(
            uid, amt, game_key=None,
            description="Transfer out to main wallet (approved)",
            meta={"kind": "TRANSFER_OUT", "request_id": str(request_id)},
        )
    except Exception:
        # Couldn't debit — roll the request back to PENDING.
        await coll.update_one(
            {"_id": claimed["_id"]},
            {"$set": {"status": GamesWithdrawalStatus.PENDING.value, "processed_by": None, "processed_at": None}},
        )
        raise
    try:
        await wallet_service.adjust(
            uid, amt,
            transaction_type=TransactionType.GAMES_TRANSFER_OUT,
            narration="Transfer from games wallet (approved)",
            reference_type="GAMES_WALLET",
            reference_id=str(request_id),
            actor_id=admin_id,
        )
    except Exception:
        # Main credit failed — return the money to the games wallet.
        await atomic_games_wallet_credit(
            uid, amt, game_key=None,
            description="Reverted failed games → main transfer",
            meta={"kind": "TRANSFER_OUT_REVERT", "request_id": str(request_id)},
        )
        await coll.update_one(
            {"_id": claimed["_id"]},
            {"$set": {"status": GamesWithdrawalStatus.PENDING.value, "processed_by": None, "processed_at": None}},
        )
        raise
    return {"id": str(request_id), "status": "APPROVED", "amount": str(amt)}


async def reject_games_withdrawal(
    request_id: str | PydanticObjectId, admin_id: PydanticObjectId, reason: str | None = None
) -> dict[str, Any]:
    coll = GamesWithdrawalRequest.get_motor_collection()
    claimed = await coll.find_one_and_update(
        {"_id": PydanticObjectId(str(request_id)), "status": GamesWithdrawalStatus.PENDING.value},
        {
            "$set": {
                "status": GamesWithdrawalStatus.REJECTED.value,
                "processed_by": admin_id,
                "processed_at": now_utc(),
                "admin_remark": reason,
                "updated_at": now_utc(),
            }
        },
        return_document=ReturnDocument.AFTER,
    )
    if claimed is None:
        raise NotFoundError("Request not found or already processed")
    return {"id": str(request_id), "status": "REJECTED"}


# ── Hierarchy "temporary wallet" (held admin/broker earnings) ──────────
async def credit_admin_temp(
    admin_user_id: str | PydanticObjectId,
    amount: Decimal | float | int | str,
    *,
    game_key: str,
    description: str,
    meta: dict | None = None,
) -> None:
    """Accrue games hierarchy commission into an admin/broker's TEMPORARY
    wallet (never available_balance). Writes a GamesWalletLedger row with
    owner_type='ADMIN' so it stays out of the trading ledger. Mirrors
    Stockex's temporaryWallet.balance / totalEarned."""
    amt = quantize_money(to_decimal(amount))
    if amt <= ZERO:
        return
    uid = PydanticObjectId(str(admin_user_id))
    # Ensure a wallet doc exists (admins have wallets too).
    await wallet_service.get_or_create(uid)
    coll = Wallet.get_motor_collection()
    updated = await coll.find_one_and_update(
        {"user_id": uid},
        {
            "$inc": {
                "temporary_balance": to_decimal128(amt),
                "temporary_total_earned": to_decimal128(amt),
                "version": 1,
            }
        },
        return_document=ReturnDocument.AFTER,
    )
    bal_after = to_decimal(updated.get("temporary_balance")) if updated else amt
    await _record_ledger(
        uid, GamesLedgerEntryType.CREDIT, amt, bal_after,
        game_key=game_key, description=description,
        meta={**(meta or {}), "wallet": "TEMPORARY"},
    )


async def release_temp_to_main(
    admin_user_id: str | PydanticObjectId,
    amount: Decimal | float | int | str,
    *,
    actor_id: PydanticObjectId,
) -> dict[str, Any]:
    """Release held games commission from an admin's temporary wallet into
    their main trading wallet. Atomic-guarded on sufficient temp balance."""
    amt = quantize_money(to_decimal(amount))
    if amt <= ZERO:
        raise ValueError("amount must be positive")
    uid = PydanticObjectId(str(admin_user_id))
    await wallet_service.get_or_create(uid)
    coll = Wallet.get_motor_collection()
    amt128 = to_decimal128(amt)
    neg128 = to_decimal128(ZERO - amt)
    zero128 = Decimal128("0")
    updated = await coll.find_one_and_update(
        {
            "user_id": uid,
            "$expr": {"$gte": [{"$ifNull": [{"$toDecimal": "$temporary_balance"}, zero128]}, amt128]},
        },
        {
            "$inc": {
                "temporary_balance": neg128,
                "temporary_total_released": amt128,
                "version": 1,
            }
        },
        return_document=ReturnDocument.AFTER,
    )
    if updated is None:
        raise InsufficientGamesFundsError("Insufficient temporary wallet balance")
    # Credit main wallet via the trading wallet service (writes WalletTransaction).
    await wallet_service.adjust(
        uid, amt,
        transaction_type=TransactionType.GAMES_HIERARCHY,
        narration="Games hierarchy commission released to main wallet",
        reference_type="GAMES_HIERARCHY",
        actor_id=actor_id,
    )
    return {
        "released": str(amt),
        "temporary_balance": str(to_decimal(updated.get("temporary_balance"))),
    }


async def list_ledger(
    user_id: str | PydanticObjectId, *, game_key: str | None = None, limit: int = 100, day: str | None = None
) -> list[GamesWalletLedger]:
    uid = PydanticObjectId(str(user_id))
    q: dict[str, Any] = {"owner_id": uid}
    if game_key:
        q["game_key"] = game_key
    rows = GamesWalletLedger.find(q).sort("-created_at").limit(limit)
    return await rows.to_list()
