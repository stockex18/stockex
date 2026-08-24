"""Security money — an admin's collateral against their users' games exposure.

Every balance change goes through `_apply`, which writes the ledger row and the
rollups in one place. Nothing else may touch the balances: a figure that can be
moved from several call sites is a figure nobody can reconcile later.

Direction (operator-confirmed with a worked example):

    admin lodges 5,00,000        security 5,00,000   payable        0
    a user of theirs LOSES 300   security 4,99,700   payable      300
    a user of theirs WINS 1L     security 5,99,700   payable      300

So, against `signed_house_amount` (the HOUSE's sign — positive when it
collected because the player lost, negative when it paid a win out):

    security moves by  -signed_house_amount   (always the opposite of the house)
    payable  moves by  +signed_house_amount   ONLY when the house collected

`payable` is what the super-admin owes this admin out of their book's losses.
It starts at ZERO — lodging security does NOT create it, because the deposit
is collateral being held, not something earned. A win does not reduce it
either; the win is absorbed by the collateral instead. The way payable comes
down is the super-admin actually funding it:

    SA tops up from its own wallet -> security UP, payable DOWN
"""

from __future__ import annotations

import logging
from decimal import Decimal

from beanie import PydanticObjectId
from bson import Decimal128

from app.core.exceptions import NotFoundError, ValidationFailedError
from app.models.admin_security import (
    AdminSecurity,
    AdminSecurityEntry,
    SecurityEntryType,
)
from app.models.user import User, UserRole
from app.utils.decimal_utils import quantize_money, to_decimal
from app.utils.time_utils import now_utc

logger = logging.getLogger(__name__)
ZERO = Decimal("0")


async def get_or_create(admin_id: str | PydanticObjectId) -> AdminSecurity:
    aid = PydanticObjectId(str(admin_id))
    row = await AdminSecurity.find_one(AdminSecurity.admin_id == aid)
    if row is None:
        row = AdminSecurity(admin_id=aid)
        try:
            await row.insert()
        except Exception:  # noqa: BLE001 — concurrent create; re-read the winner
            row = await AdminSecurity.find_one(AdminSecurity.admin_id == aid)
            if row is None:
                raise
    return row


async def _apply(
    admin_id: PydanticObjectId,
    *,
    entry_type: SecurityEntryType,
    security_delta: Decimal,
    payable_delta: Decimal = ZERO,
    narration: str = "",
    payment_mode: str | None = None,
    game_key: str | None = None,
    trade_id: str | None = None,
    user_id: PydanticObjectId | None = None,
    actor_id: PydanticObjectId | None = None,
) -> AdminSecurity:
    """The ONLY place these balances move. Writes the matching ledger row."""
    row = await get_or_create(admin_id)

    new_sec = to_decimal(row.security_balance) + security_delta
    new_pay = to_decimal(row.payable_balance) + payable_delta
    row.security_balance = Decimal128(str(quantize_money(new_sec)))
    row.payable_balance = Decimal128(str(quantize_money(new_pay)))

    if entry_type == SecurityEntryType.DEPOSIT:
        row.total_deposited = Decimal128(
            str(quantize_money(to_decimal(row.total_deposited) + security_delta))
        )
    elif entry_type == SecurityEntryType.GAMES_PNL:
        # `security_delta` is the OPPOSITE of the house here, so a POSITIVE
        # delta means the collateral grew — which happens on a player WIN.
        if security_delta > ZERO:
            row.total_games_out = Decimal128(
                str(quantize_money(to_decimal(row.total_games_out) + security_delta))
            )
        else:
            row.total_games_in = Decimal128(
                str(quantize_money(to_decimal(row.total_games_in) - security_delta))
            )
    elif entry_type == SecurityEntryType.BROKERAGE:
        row.total_brokerage = Decimal128(
            str(quantize_money(to_decimal(row.total_brokerage) - security_delta))
        )
    await row.save()

    await AdminSecurityEntry(
        admin_id=admin_id,
        entry_type=entry_type,
        amount=Decimal128(str(quantize_money(security_delta))),
        security_after=row.security_balance,
        payable_after=row.payable_balance,
        narration=narration,
        payment_mode=payment_mode,
        game_key=game_key,
        trade_id=trade_id,
        user_id=user_id,
        actor_id=actor_id,
    ).insert()
    return row


async def _assert_admin(admin_id: str | PydanticObjectId) -> User:
    try:
        u = await User.get(PydanticObjectId(str(admin_id)))
    except Exception as e:  # noqa: BLE001 — malformed id
        raise NotFoundError("Admin not found") from e
    if u is None or u.role not in (UserRole.ADMIN, UserRole.BROKER):
        raise NotFoundError("Admin not found")
    return u


def _positive(amount) -> Decimal:
    amt = quantize_money(to_decimal(amount))
    if amt <= ZERO:
        raise ValidationFailedError("amount must be positive")
    return amt


async def _to_ledger(actor, admin_user, amount, payment_mode, *, inflow: bool, note: str = "") -> None:
    """Mirror a security receipt/return into the operator's ledger books.

    Security money changes hands physically, so it belongs in the Cash / Cheque
    / Bank book alongside every other movement of the same mode. The security
    ledger stays the record of the COLLATERAL; this is the record of the CASH.
    """
    from app.services import ledger_book_service

    await ledger_book_service.post(
        getattr(actor, "id", None), payment_mode, amount=amount, is_inflow=inflow,
        particulars=str(getattr(admin_user, "user_code", "") or ""),
        narration=note or ("Security " + ("received" if inflow else "returned")),
        source_type="ADMIN_SECURITY",
        source_id=("sec:" + ("in" if inflow else "out") + ":" + str(getattr(admin_user, "id", ""))
                   + ":" + str(amount) + ":" + now_utc().isoformat()),
    )


# -- Operator actions --------------------------------------------------
async def record_deposit(
    actor, admin_id, amount, *, payment_mode=None, narration=""
) -> AdminSecurity:
    """The admin handed money over — collateral only.

    Payable is deliberately NOT touched: this is money being HELD, not money
    earned. Payable is what their book's losses have earned them, and it
    starts at zero.
    """
    amt = _positive(amount)
    u = await _assert_admin(admin_id)
    row = await _apply(
        u.id,
        entry_type=SecurityEntryType.DEPOSIT,
        security_delta=amt,
        narration=narration or "Security received from " + str(u.user_code),
        payment_mode=payment_mode,
        actor_id=getattr(actor, "id", None),
    )
    await _to_ledger(actor, u, amt, payment_mode, inflow=True, note=narration)
    return row


async def record_withdraw(
    actor, admin_id, amount, *, payment_mode=None, narration=""
) -> AdminSecurity:
    """Returned to the admin — collateral only, mirroring the deposit."""
    amt = _positive(amount)
    u = await _assert_admin(admin_id)
    row = await get_or_create(u.id)
    if to_decimal(row.security_balance) < amt:
        raise ValidationFailedError(
            "Security is only " + str(row.security_balance) + " - cannot return " + str(amt)
        )
    out = await _apply(
        u.id,
        entry_type=SecurityEntryType.WITHDRAW,
        security_delta=-amt,
        narration=narration or "Security returned to " + str(u.user_code),
        payment_mode=payment_mode,
        actor_id=getattr(actor, "id", None),
    )
    await _to_ledger(actor, u, amt, payment_mode, inflow=False, note=narration)
    return out


async def topup_from_main(actor, admin_id, amount, *, narration="") -> AdminSecurity:
    """SA funds the security out of its OWN main wallet.

    Collateral rises but the debt FALLS by the same amount: this is the
    super-admin's money going in, so it settles what was owed rather than
    adding to it.

    The wallet is debited FIRST. If that raises (insufficient funds) nothing
    has been written yet, so the two sides can never drift apart.
    """
    from app.models.transaction import TransactionType
    from app.services import wallet_service

    amt = _positive(amount)
    u = await _assert_admin(admin_id)

    await wallet_service.adjust(
        actor.id,
        -amt,
        transaction_type=TransactionType.ADMIN_TRANSFER,
        narration="Security top-up for " + str(u.user_code),
        reference_type="ADMIN_SECURITY",
        actor_id=actor.id,
    )
    return await _apply(
        u.id,
        entry_type=SecurityEntryType.SA_TOPUP,
        security_delta=amt,
        payable_delta=-amt,
        narration=narration or "Top-up from super-admin wallet",
        actor_id=getattr(actor, "id", None),
    )


async def adjust_manual(actor, admin_id, signed_amount, *, narration="") -> AdminSecurity:
    """Manual correction. Signed; deliberately leaves payable alone."""
    amt = quantize_money(to_decimal(signed_amount))
    if amt == ZERO:
        raise ValidationFailedError("amount must be non-zero")
    u = await _assert_admin(admin_id)
    return await _apply(
        u.id,
        entry_type=SecurityEntryType.ADJUSTMENT,
        security_delta=amt,
        narration=narration or "Manual adjustment",
        actor_id=getattr(actor, "id", None),
    )


# -- Brokerage hook ----------------------------------------------------
async def charge_brokerage(
    admin_id, amount, *, narration: str = "", trade_id: str | None = None, user_id=None
) -> bool:
    """Take the super-admin's fixed brokerage out of this admin's collateral.

    Returns True when it was charged here, False when this admin has no
    security row — the caller then falls back to debiting their wallet, which
    is what every admin without lodged collateral has always done.

    Deliberately NOT `get_or_create`: an admin who never lodged security has no
    collateral to consume, and silently opening a row at -X would invent a debt
    that nobody agreed to.

    Payable is untouched. Brokerage is the super-admin EARNING money, not owing
    it — only the admin's own book losses (GAMES_PNL) put it there.
    """
    amt = quantize_money(to_decimal(amount))
    if amt <= ZERO or admin_id is None:
        return False
    aid = PydanticObjectId(str(admin_id))
    if await AdminSecurity.find_one({"admin_id": aid}) is None:
        return False
    await _apply(
        aid,
        entry_type=SecurityEntryType.BROKERAGE,
        security_delta=-amt,
        narration=narration or "SA fixed brokerage",
        trade_id=str(trade_id) if trade_id else None,
        user_id=PydanticObjectId(str(user_id)) if user_id else None,
    )
    return True


# -- Games hook --------------------------------------------------------
async def apply_games_result(
    player_id, signed_house_amount, *, game_key: str, narration: str = ""
) -> None:
    """Route one games settle onto the player's owning admin's security.

    `signed_house_amount` carries the HOUSE's sign, straight from
    `house_settle`: positive when the house collected (player lost), negative
    when it paid a win out.

    Security moves the OPPOSITE way to the house, and payable only accrues on
    a loss:

        player LOSES 300  -> house +300 -> security -300, payable +300
        player WINS  1L   -> house -1L  -> security +1L,  payable unchanged

    A win is absorbed by the collateral rather than netted off payable —
    payable is the running total of what this admin's book has earned, and it
    is brought down by the super-admin actually funding it (SA_TOPUP), not by
    a later win.

    Best-effort by design — this runs on the payout path, and a player's
    winnings must never be gated on collateral bookkeeping succeeding. A demo
    player, or one with no owning admin (a direct super-admin user), is a
    no-op: there is no admin whose collateral it would belong to.
    """
    try:
        amt = quantize_money(to_decimal(signed_house_amount))
        if amt == ZERO or player_id is None:
            return
        player = await User.get(PydanticObjectId(str(player_id)))
        if player is None or getattr(player, "is_demo", False):
            return
        admin_id = getattr(player, "assigned_admin_id", None)
        if admin_id is None:
            return
        await _apply(
            admin_id,
            entry_type=SecurityEntryType.GAMES_PNL,
            security_delta=-amt,
            payable_delta=amt if amt > ZERO else ZERO,
            narration=narration or ("Games " + str(game_key)),
            game_key=game_key,
            user_id=player.id,
        )
    except Exception:  # noqa: BLE001 — never break a payout on this
        logger.exception("admin_security_games_hook_failed game=%s", game_key)


# -- Reads -------------------------------------------------------------
async def list_all() -> list[dict]:
    rows = await AdminSecurity.find_all().to_list()
    users: dict[str, User] = {}
    if rows:
        for u in await User.find({"_id": {"$in": [r.admin_id for r in rows]}}).to_list():
            users[str(u.id)] = u
    out = []
    for r in rows:
        u = users.get(str(r.admin_id))
        out.append({
            "admin_id": str(r.admin_id),
            "user_code": u.user_code if u else str(r.admin_id),
            "full_name": (u.full_name if u else None) or (u.user_code if u else ""),
            "security_balance": str(r.security_balance),
            "payable_balance": str(r.payable_balance),
            "total_deposited": str(r.total_deposited),
            "total_games_in": str(r.total_games_in),
            "total_games_out": str(r.total_games_out),
            "total_brokerage": str(r.total_brokerage),
        })
    out.sort(key=lambda x: float(x["security_balance"] or 0), reverse=True)
    return out


async def list_entries(admin_id=None, limit: int = 100) -> list[dict]:
    q: dict = {} if admin_id is None else {"admin_id": PydanticObjectId(str(admin_id))}
    rows = await AdminSecurityEntry.find(q).sort("-created_at").limit(limit).to_list()
    return [
        {
            "id": str(r.id),
            "admin_id": str(r.admin_id),
            "entry_type": (
                r.entry_type.value if hasattr(r.entry_type, "value") else str(r.entry_type)
            ),
            "amount": str(r.amount),
            "security_after": str(r.security_after),
            "payable_after": str(r.payable_after),
            "narration": r.narration,
            "payment_mode": r.payment_mode,
            "game_key": r.game_key,
            "trade_id": r.trade_id,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]
