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

    forget_cap_state(row.admin_id)
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
async def charge_pnl_share(
    admin_id, amount, *, narration: str = "", trade_id: str | None = None, user_id=None
) -> bool:
    """Settle the super-admin's P&L share against this admin's collateral.

    The same rule brokerage already follows: the collateral is what the SA
    holds against this admin's book, so what that book earns the SA draws it
    down — and the admin's Security ledger shows the line, which is the point
    (operator: "pnl sharing me jitna paisa super admin ko aata hai wo cut ho
    aur wahi entry dikhe, isse balance kam hota chale").

    SIGNED, unlike brokerage: a user PROFIT makes the share negative, the SA
    pays it, and the collateral goes back UP.

    Returns False when this admin has no security row — the caller then falls
    back to debiting their wallet, which is the old behaviour for every admin
    without lodged collateral. Payable is untouched: a share the SA earns is
    not money it owes.
    """
    amt = quantize_money(to_decimal(amount))
    if amt == ZERO or admin_id is None:
        return False
    aid = PydanticObjectId(str(admin_id))
    if await AdminSecurity.find_one({"admin_id": aid}) is None:
        return False
    await _apply(
        aid,
        entry_type=SecurityEntryType.PNL_SHARE,
        security_delta=-amt,
        narration=narration or "SA P&L share",
        trade_id=str(trade_id) if trade_id else None,
        user_id=PydanticObjectId(str(user_id)) if user_id else None,
    )
    return True


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
    # How close each one is to the cap, on the same screen that shows the
    # balances — a number nobody can act on is a number nobody reads.
    for row in out:
        try:
            u = await utilisation(row["admin_id"])
            row.update({
                "used_pct": u["used_pct"],
                "cap_pct": u["cap_pct"],
                "lodged": u["lodged"],
                "consumed": u["consumed"],
                "blocked": u["blocked"],
            })
        except Exception:  # noqa: BLE001 — a reading must never break the list
            logger.debug("security_utilisation_failed", exc_info=True)
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


# ── The printed statement, per admin ──────────────────────────────────
#: What each movement is, in the Particulars column. Debit = collateral came
#: IN, credit = collateral was consumed — so the running balance IS the
#: security. The GAMES row reads by DIRECTION, because "Games" on its own says
#: nothing the Type column has not already said.
_ENTRY_LABEL = {
    SecurityEntryType.DEPOSIT: "Security received",
    SecurityEntryType.WITHDRAW: "Security returned",
    SecurityEntryType.SA_TOPUP: "Top-up from super-admin wallet",
    SecurityEntryType.GAMES_PNL: "Games",
    SecurityEntryType.BROKERAGE: "SA brokerage",
    SecurityEntryType.PNL_SHARE: "SA P&L share",
    SecurityEntryType.ADJUSTMENT: "Manual adjustment",
}

#: What the Type column says. Money that physically changed hands reads as the
#: MODE it moved by — the operator names those ledgers themselves, so the
#: statement says "bank" or "Cash", not an accounting abbreviation nobody set.
_TYPE_FIXED = {
    SecurityEntryType.SA_TOPUP: "Top-up",
    SecurityEntryType.GAMES_PNL: "Games",
    SecurityEntryType.BROKERAGE: "Brokerage",
    SecurityEntryType.PNL_SHARE: "P&L share",
    SecurityEntryType.ADJUSTMENT: "Adjust",
}


async def _mode_labels() -> dict:
    """code -> the name the super-admin gave that payment mode."""
    try:
        from app.services import ledger_book_service

        return {m["code"]: m["label"] for m in await ledger_book_service.payment_modes()}
    except Exception:  # noqa: BLE001 — a statement must render without them
        return {}


async def statement(admin_id, start=None, end=None) -> dict:
    """One admin's security account as a ruled ledger.

    Same shape as `ledger_book_service.statement`, so the PDF builder renders
    it without knowing this is a different kind of account.

    Sides are the ordinary ones for a liability. Collateral an admin lodges is
    money you are HOLDING, so it is a CREDIT in their account and the balance
    reads Cr — "you owe them this much". A games loss or your brokerage eats
    into it, so those are DEBITS. `amount` is stored signed the way it moved
    the COLLATERAL, so each row's sides are the mirror of that sign.

    The magnitude still reproduces `security_balance` exactly: the balance on
    the card can always be explained by the rows.

    `payable_balance` rides along on every row from what was stored at the
    time, so the two halves of the relationship are read down one page.

    Rows before `start` are folded into the opening figure rather than
    dropped, so narrowing the window SHOWS less without RESTATING the balance.
    """
    u = await _assert_admin(admin_id)
    aid = u.id

    opening = ZERO
    if start is not None:
        for e in await AdminSecurityEntry.find(
            {"admin_id": aid, "created_at": {"$lt": start}}
        ).to_list():
            opening += -to_decimal(e.amount)   # mirrored, like the rows below

    q: dict = {"admin_id": aid}
    if start is not None or end is not None:
        rng: dict = {}
        if start is not None:
            rng["$gte"] = start
        if end is not None:
            rng["$lte"] = end
        q["created_at"] = rng

    modes = await _mode_labels()

    entries = await AdminSecurityEntry.find(q).sort("created_at").to_list()

    # Whose money moved. Resolved in ONE query for the whole page rather than
    # per row — a busy admin's statement is hundreds of lines.
    clients: dict = {}
    ids = {e.user_id for e in entries if e.user_id is not None}
    if ids:
        for cu in await User.find({"_id": {"$in": list(ids)}}).to_list():
            clients[str(cu.id)] = (cu.user_code or "", cu.full_name or cu.user_code or "")

    rows: list[dict] = []
    running = opening
    total_dr = total_cr = ZERO
    for e in entries:
        amt = to_decimal(e.amount)
        # Mirrored: collateral coming IN is a credit to them.
        dr = -amt if amt < ZERO else ZERO
        cr = amt if amt > ZERO else ZERO
        running += -amt
        total_dr += dr
        total_cr += cr

        label = _ENTRY_LABEL.get(e.entry_type, str(e.entry_type))
        if e.entry_type == SecurityEntryType.GAMES_PNL:
            # Security rises when the house PAID a win out, falls when it
            # collected — so the sign already says which way the player went.
            label = "Player won" if amt > ZERO else "Player lost"
        vtype = _TYPE_FIXED.get(e.entry_type)
        if vtype is None:
            code = (e.payment_mode or "").strip().upper()
            vtype = modes.get(code) or code or "Entry"

        code, name = clients.get(str(e.user_id), ("", "")) if e.user_id else ("", "")
        rows.append({
            "id": str(e.id),
            "entry_date": e.created_at.isoformat() if e.created_at else None,
            # Blank on a deposit or return: that is the admin's own money
            # changing hands, with no client behind it.
            "client_code": code,
            "client_name": name,
            "voucher_type": vtype,
            # The game or trade this came from — what makes a row checkable
            # against the thing that caused it. Trade ids are trimmed so the
            # column stays one line; the narration carries the client code.
            "voucher_no": (e.game_key or (e.trade_id or "")[-12:] or ""),
            "particulars": label,
            "narration": e.narration or "",
            "debit": str(quantize_money(dr)),
            "credit": str(quantize_money(cr)),
            "balance": str(quantize_money(abs(running))),
            "balance_side": "Dr" if running >= ZERO else "Cr",
            # What was owed to them at that moment — stored on the entry, so
            # this is the figure as it stood, not one recomputed today.
            "payable_after": str(e.payable_after),
            "payable_balance": str(e.payable_after),
            # Per-trade / per-game rows: the ledger groups them by day on
            # screen ("View all" opens them), and they are not hand-written so
            # they carry no delete control.
            "is_auto": e.entry_type in (
                SecurityEntryType.GAMES_PNL,
                SecurityEntryType.BROKERAGE,
                SecurityEntryType.PNL_SHARE,
            ),
        })

    open_dr = opening if opening > ZERO else ZERO
    open_cr = -opening if opening < ZERO else ZERO
    sum_dr = total_dr + open_dr
    sum_cr = total_cr + open_cr
    row = await get_or_create(aid)
    return {
        "book": {
            "id": str(aid),
            "name": (u.full_name or u.user_code or "") + " — Security (" + str(u.user_code) + ")",
            "code": str(u.user_code or ""),
            "is_payment_mode": False,
        },
        "opening_balance": str(quantize_money(abs(opening))),
        "opening_side": "Dr" if opening >= ZERO else "Cr",
        "rows": rows,
        "total_debit": str(quantize_money(sum_dr)),
        "total_credit": str(quantize_money(sum_cr)),
        "closing_balance": str(quantize_money(abs(running))),
        "closing_side": "Dr" if running >= ZERO else "Cr",
        "grand_total": str(quantize_money(max(sum_dr, sum_cr))),
        "start": start.isoformat() if start else None,
        "end": end.isoformat() if end else None,
        # Alongside the collateral, so the two halves of the relationship are
        # read together rather than from two different screens.
        "payable_balance": str(row.payable_balance),
        "total_brokerage": str(row.total_brokerage),
        "total_games_in": str(row.total_games_in),
        "total_games_out": str(row.total_games_out),
    }


# ── The cap ──────────────────────────────────────────────────────────
# An admin's security is the collateral their whole book stands on. Once most
# of it has been consumed, what is left is the buffer that has to settle the
# trades already open — so their users stop OPENING new ones and stop betting.
# Operator: "kisi admin ka security money ka 90% khatam ho jaye to uske user
# trade mat kar paye and game bhi play mat kar paye."
#
# Consumed means consumed: brokerage, the P&L share and games losses. A
# WITHDRAW is the admin taking their own money back, so it lowers what they
# have lodged rather than counting as usage — measuring it as usage would shut
# an admin's book the moment they drew their float down.
SECURITY_CAP_PCT = Decimal("90")
_CAP_SETTING_KEY = "security.cap_pct"
_CAP_TTL_SEC = 60.0
_STATE_TTL_SEC = 15.0
_cap_cached: tuple[float, Decimal] | None = None
_state_cache: dict[str, tuple[float, dict]] = {}

_IN_TYPES = (SecurityEntryType.DEPOSIT.value, SecurityEntryType.SA_TOPUP.value)
_OUT_TYPES = (SecurityEntryType.WITHDRAW.value,)
_CONSUMED_TYPES = (
    SecurityEntryType.BROKERAGE.value,
    SecurityEntryType.PNL_SHARE.value,
    SecurityEntryType.GAMES_PNL.value,
)


def forget_cap_state(admin_id=None) -> None:
    """Drop the cached reading — called whenever the ledger moves, so a fresh
    deposit reopens the book on the next order rather than in fifteen seconds."""
    if admin_id is None:
        _state_cache.clear()
    else:
        _state_cache.pop(str(admin_id), None)


async def cap_pct() -> Decimal:
    """The consumed-percentage at which an admin's book closes. 90 unless the
    super-admin has stored `security.cap_pct`."""
    global _cap_cached
    import time as _t

    if _cap_cached is not None and (_t.monotonic() - _cap_cached[0]) < _CAP_TTL_SEC:
        return _cap_cached[1]
    val = SECURITY_CAP_PCT
    try:
        from app.models.platform_setting import PlatformSetting

        row = await PlatformSetting.find_one(PlatformSetting.setting_key == _CAP_SETTING_KEY)
        if row is not None and row.setting_value is not None:
            v = Decimal(str(row.setting_value))
            if Decimal("1") <= v <= Decimal("100"):
                val = v
    except Exception:  # noqa: BLE001 — a missing setting is not an outage
        logger.debug("security_cap_setting_read_failed", exc_info=True)
    _cap_cached = (_t.monotonic(), val)
    return val


async def utilisation(admin_id) -> dict:
    """How much of an admin's lodged security is gone, and whether that closes
    their book.

    `lodged`   — deposits and super-admin top-ups, less what has been returned.
    `consumed` — brokerage + P&L share + games, as it hit the collateral.
    """
    aid = PydanticObjectId(str(admin_id))
    coll = AdminSecurityEntry.get_motor_collection()
    sums: dict[str, Decimal] = {}
    async for r in coll.aggregate([
        {"$match": {"admin_id": aid}},
        {"$group": {"_id": "$entry_type", "s": {"$sum": {"$toDecimal": "$amount"}}}},
    ]):
        sums[str(r["_id"])] = Decimal(str(r["s"]))

    lodged_in = sum((sums.get(t, ZERO) for t in _IN_TYPES), ZERO)
    returned = abs(sum((sums.get(t, ZERO) for t in _OUT_TYPES), ZERO))
    consumed = -sum((sums.get(t, ZERO) for t in _CONSUMED_TYPES), ZERO)
    lodged = lodged_in - returned
    row = await get_or_create(aid)
    balance = to_decimal(row.security_balance)
    cap = await cap_pct()

    if lodged > ZERO:
        used_pct = (consumed / lodged) * Decimal("100")
    else:
        # Nothing lodged: the cap has no base to measure against. Only an
        # account that has gone NEGATIVE is closed — an admin who never posted
        # security is simply not in this scheme, and must not be shut out of it.
        used_pct = Decimal("100") if balance < ZERO else ZERO

    blocked = balance < ZERO or (lodged > ZERO and used_pct >= cap)
    return {
        "admin_id": str(aid),
        "lodged": str(quantize_money(lodged)),
        "consumed": str(quantize_money(consumed)),
        "balance": str(quantize_money(balance)),
        "used_pct": float(round(used_pct, 2)),
        "cap_pct": float(cap),
        "remaining_pct": float(round(max(ZERO, Decimal("100") - used_pct), 2)),
        "blocked": bool(blocked),
    }


async def is_blocked(admin_id) -> dict | None:
    """The utilisation reading when the admin's book is closed, else None.
    Cached briefly — this is asked on every order and every bet."""
    import time as _t

    key = str(admin_id)
    hit = _state_cache.get(key)
    if hit is not None and (_t.monotonic() - hit[0]) < _STATE_TTL_SEC:
        return hit[1] if hit[1].get("blocked") else None
    try:
        state = await utilisation(admin_id)
    except Exception:  # noqa: BLE001 — never let this gate fail closed
        logger.warning("security_cap_check_failed", exc_info=True)
        return None
    _state_cache[key] = (_t.monotonic(), state)
    return state if state.get("blocked") else None


async def blocked_for_user(user) -> dict | None:
    """Same reading for whoever owns this trader. None when there is no admin
    above them (the super-admin's own clients) or the book is open."""
    aid = getattr(user, "assigned_admin_id", None)
    if not aid:
        return None
    return await is_blocked(aid)
