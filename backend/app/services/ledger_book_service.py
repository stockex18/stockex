"""Keeping the ledger books: post lines into them, read a statement out.

The statement is the whole point, so it is the one thing computed carefully:
rows in date order, a running balance replayed from the opening figure, and
the closing figure carried into a grand total that squares both columns —
the way a printed ledger does it.

Auto-posting is best-effort on purpose. These books are a record of money that
has ALREADY moved; failing to write the record must never roll back or block
the movement itself.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from decimal import Decimal

from beanie import PydanticObjectId
from bson import Decimal128

from app.core.exceptions import NotFoundError, ValidationFailedError
from app.models.ledger_book import (
    AccountType,
    LedgerBook,
    LedgerBookEntry,
    VoucherType,
)
from app.models.user import User, UserRole
from app.utils.decimal_utils import quantize_money, to_decimal
from app.utils.time_utils import now_utc

logger = logging.getLogger(__name__)
ZERO = Decimal("0")



def _d128(v) -> Decimal128:
    return Decimal128(str(quantize_money(to_decimal(v))))


def slug(name: str) -> str:
    """The stable code a money movement is stamped with.

    Uppercase, non-alphanumerics folded to underscores. Derived from the name
    ONCE, at creation — after that the two are independent, so renaming a
    ledger never orphans the rows already stamped with its old code.
    """
    out = re.sub(r"[^A-Za-z0-9]+", "_", (name or "").strip()).strip("_").upper()
    return out[:32] or "MODE"


# ── Books ────────────────────────────────────────────────────────────
def cash_sides(debit, credit) -> tuple[Decimal, Decimal]:
    """(debit, credit) for a CASH / bank / UPI ledger, as this operator keeps it.

        money reaching you   -> CREDIT
        money leaving you    -> DEBIT

    Their words: "received kar raha hu, super admin ke paas paisa aa raha hai,
    matlab wo credit me hona chahiye; pay karunga wo debit me hona chahiye."
    That is the party-account orientation applied to the cash side — the exact
    mirror of the textbook cash book, where money arriving is a debit.

    Stored rows keep the textbook convention, so nothing in the database is
    rewritten and this is one line to undo. Every cash view goes through here
    so one of them cannot end up reading the opposite way from the others.

    `party_statement` deliberately does NOT use this: a party account is the
    mirror of its cash book, so the two orientations flipping together is what
    keeps them agreeing.
    """
    return (to_decimal(credit), to_decimal(debit))


async def payment_modes() -> list[dict]:
    """The vocabulary of payment modes, as the super-admin defined it.

    One list platform-wide rather than per-admin: a movement between two
    admins has to be recorded the same way on both sides, so the modes cannot
    be allowed to disagree. Each owner still keeps their OWN book per mode —
    the code is shared, the ledger is theirs.
    """
    sa = await User.find_one({"role": UserRole.SUPER_ADMIN.value})
    if sa is None:
        return []
    books = await LedgerBook.find({
        "owner_id": sa.id, "is_payment_mode": True, "is_archived": {"$ne": True},
    }).sort("name").to_list()
    return [{"code": b.code or slug(b.name), "label": b.name} for b in books]


async def list_books(owner_id, include_archived: bool = False) -> list[dict]:
    oid = PydanticObjectId(str(owner_id))
    q: dict = {"owner_id": oid}
    if not include_archived:
        q["is_archived"] = {"$ne": True}
    books = await LedgerBook.find(q).sort("-is_payment_mode", "name").to_list()
    return [{
        "id": str(b.id),
        "name": b.name,
        "code": b.code or slug(b.name),
        "is_payment_mode": bool(b.is_payment_mode),
        "account_type": getattr(b.account_type, "value", str(b.account_type)),
        "opening_balance": str(b.opening_balance),
        "opening_date": b.opening_date.isoformat() if b.opening_date else None,
        "note": b.note,
        "is_archived": b.is_archived,
    } for b in books]


async def create_book(owner_id, name: str, *, is_payment_mode: bool = False,
                      code: str | None = None, opening_balance=0,
                      opening_date: datetime | None = None,
                      account_type: str = "OTHER",
                      note: str = "") -> LedgerBook:
    """Open a ledger. Flagged as a payment mode, it also becomes a choice in
    every "how did this money move?" dropdown — creating the mode and opening
    its book are the same act, so a mode can never exist without somewhere to
    post."""
    nm = (name or "").strip()
    if not nm:
        raise ValidationFailedError("Give the ledger a name")
    oid = PydanticObjectId(str(owner_id))
    if await LedgerBook.find_one({"owner_id": oid, "name": nm}) is not None:
        raise ValidationFailedError("You already keep a ledger called " + nm)
    cd = slug(code or nm)
    if await LedgerBook.find_one({"owner_id": oid, "code": cd}) is not None:
        raise ValidationFailedError("A ledger with the code " + cd + " already exists")
    try:
        at = AccountType(str(account_type or "OTHER").upper())
    except ValueError:
        raise ValidationFailedError("Unknown account type") from None
    book = LedgerBook(
        owner_id=oid, name=nm, code=cd, is_payment_mode=bool(is_payment_mode),
        account_type=at,
        opening_balance=_d128(opening_balance),
        opening_date=opening_date, note=note or "",
    )
    await book.insert()
    return book


async def _get_book(owner_id, book_id) -> LedgerBook:
    try:
        b = await LedgerBook.get(PydanticObjectId(str(book_id)))
    except Exception as e:  # noqa: BLE001 — malformed id
        raise NotFoundError("Ledger not found") from e
    if b is None or str(b.owner_id) != str(owner_id):
        raise NotFoundError("Ledger not found")
    return b


async def update_book(owner_id, book_id, *, name=None, opening_balance=None,
                      opening_date=None, note=None, is_archived=None,
                      is_payment_mode=None) -> LedgerBook:
    """`code` is deliberately not editable — it is stamped on movements that
    have already happened, and changing it would orphan every one of them."""
    b = await _get_book(owner_id, book_id)
    if is_payment_mode is not None:
        b.is_payment_mode = bool(is_payment_mode)
    if name is not None:
        nm = str(name).strip()
        if not nm:
            raise ValidationFailedError("Give the ledger a name")
        b.name = nm
    if opening_balance is not None:
        b.opening_balance = _d128(opening_balance)
    if opening_date is not None:
        b.opening_date = opening_date
    if note is not None:
        b.note = str(note)
    if is_archived is not None:
        b.is_archived = bool(is_archived)
    await b.save()
    return b


async def delete_book(owner_id, book_id) -> int:
    """Drop a ledger and its lines.

    Refuses once anything has posted itself here: those lines are the record
    of money that actually moved, and deleting the book would take them with
    it. Archive instead — it leaves the statement readable and only takes the
    mode out of the dropdowns.
    """
    b = await _get_book(owner_id, book_id)
    if await LedgerBookEntry.find_one({"book_id": b.id, "is_auto": True}) is not None:
        raise ValidationFailedError(
            "Money has already been recorded in " + b.name + " — archive it instead of deleting"
        )
    res = await LedgerBookEntry.find({"book_id": b.id}).delete()
    await b.delete()
    return getattr(res, "deleted_count", 0)


# ── Entries ──────────────────────────────────────────────────────────
async def add_entry(owner_id, book_id, *, entry_date: datetime, debit=0, credit=0,
                    voucher_type: str = "Jrnl", voucher_no: str = "",
                    particulars: str = "", narration: str = "") -> LedgerBookEntry:
    b = await _get_book(owner_id, book_id)
    dr = quantize_money(to_decimal(debit or 0))
    cr = quantize_money(to_decimal(credit or 0))
    if dr < ZERO or cr < ZERO:
        raise ValidationFailedError("Amounts cannot be negative")
    if (dr > ZERO) == (cr > ZERO):
        # Both or neither. A line is one side or the other — anything else
        # makes the running balance meaningless.
        raise ValidationFailedError("Enter an amount in either Debit or Credit, not both")
    try:
        vt = VoucherType(voucher_type or "Jrnl")
    except ValueError:
        vt = VoucherType.JOURNAL
    e = LedgerBookEntry(
        book_id=b.id, owner_id=b.owner_id, entry_date=entry_date or now_utc(),
        voucher_type=vt, voucher_no=str(voucher_no or "").strip(),
        particulars=str(particulars or "").strip(), narration=str(narration or "").strip(),
        debit=_d128(dr), credit=_d128(cr),
    )
    await e.insert()
    return e


async def delete_entry(owner_id, entry_id) -> None:
    try:
        e = await LedgerBookEntry.get(PydanticObjectId(str(entry_id)))
    except Exception as exc:  # noqa: BLE001
        raise NotFoundError("Entry not found") from exc
    if e is None or str(e.owner_id) != str(owner_id):
        raise NotFoundError("Entry not found")
    if e.is_auto:
        raise ValidationFailedError(
            "This line was posted automatically from a money movement and cannot be deleted"
        )
    await e.delete()


# ── The statement ────────────────────────────────────────────────────
async def statement(owner_id, book_id, start: datetime | None = None,
                    end: datetime | None = None) -> dict:
    """Rows in date order with a running balance, plus the printed totals.

    The opening figure is the book's own opening PLUS everything before
    `start` — otherwise narrowing the date range would silently restate the
    balance rather than just showing a window of it.
    """
    b = await _get_book(owner_id, book_id)
    opening = to_decimal(b.opening_balance)

    if start is not None:
        async for e in LedgerBookEntry.find(
            {"book_id": b.id, "entry_date": {"$lt": start}}
        ):
            _d, _c = cash_sides(e.debit, e.credit)
            opening += _d - _c

    q: dict = {"book_id": b.id}
    if start is not None or end is not None:
        rng: dict = {}
        if start is not None:
            rng["$gte"] = start
        if end is not None:
            rng["$lte"] = end
        q["entry_date"] = rng

    rows: list[dict] = []
    running = opening
    total_dr = total_cr = ZERO
    for e in await LedgerBookEntry.find(q).sort("entry_date", "created_at").to_list():
        dr, cr = cash_sides(e.debit, e.credit)
        running += dr - cr
        total_dr += dr
        total_cr += cr
        rows.append({
            "id": str(e.id),
            "entry_date": e.entry_date.isoformat() if e.entry_date else None,
            "voucher_type": e.voucher_type.value if hasattr(e.voucher_type, "value") else str(e.voucher_type),
            "voucher_no": e.voucher_no,
            "particulars": e.particulars,
            "narration": e.narration,
            "debit": str(quantize_money(dr)),
            "credit": str(quantize_money(cr)),
            "balance": str(quantize_money(abs(running))),
            "balance_side": "Dr" if running >= ZERO else "Cr",
            "is_auto": e.is_auto,
        })

    # The opening figure joins whichever column it belongs to, exactly as a
    # printed ledger shows it, so the two totals square against the closing.
    open_dr = opening if opening > ZERO else ZERO
    open_cr = -opening if opening < ZERO else ZERO
    sum_dr = total_dr + open_dr
    sum_cr = total_cr + open_cr
    closing = running
    grand = max(sum_dr, sum_cr)
    return {
        "book": {
            "id": str(b.id), "name": b.name,
            "code": b.code or slug(b.name),
            "is_payment_mode": bool(b.is_payment_mode),
        },
        "opening_balance": str(quantize_money(abs(opening))),
        "opening_side": "Dr" if opening >= ZERO else "Cr",
        "rows": rows,
        "total_debit": str(quantize_money(sum_dr)),
        "total_credit": str(quantize_money(sum_cr)),
        "closing_balance": str(quantize_money(abs(closing))),
        "closing_side": "Dr" if closing >= ZERO else "Cr",
        "grand_total": str(quantize_money(grand)),
        "start": start.isoformat() if start else None,
        "end": end.isoformat() if end else None,
    }


async def _open_book_for(owner_id: PydanticObjectId, code: str) -> LedgerBook | None:
    """The owner's book for a mode code, created on first use.

    Named after the super-admin's label for that mode where there is one, so
    every admin's Cash ledger reads "Cash" rather than a slug.
    """
    label = code.replace("_", " ").title()
    for m in await payment_modes():
        if m["code"] == code:
            label = m["label"]
            break
    try:
        return await create_book(owner_id, label, is_payment_mode=True, code=code)
    except Exception:  # noqa: BLE001 — raced, or the name is taken by another book
        return await LedgerBook.find_one({"owner_id": owner_id, "code": code})


# ── Auto-posting ─────────────────────────────────────────────────────
async def post(owner_id, payment_mode: str | None, *, amount, is_inflow: bool,
               particulars: str = "", narration: str = "",
               source_type: str, source_id: str,
               voucher_no: str = "", when: datetime | None = None,
               is_auto: bool = True, party_user_id=None, party_name: str = "") -> bool:
    """Record one money movement in the book for its payment mode.

    `is_inflow` is from the BOOK's point of view: money arriving is a debit,
    money leaving is a credit. Returns False when there is nothing to post —
    no mode was stamped, or this movement is already in the book.

    `is_auto` marks a line the system wrote from a money movement; those are
    protected from deletion. A line the super admin typed is not auto, so it
    can be corrected the way any hand-written entry can.

    `party_user_id` names who the money moved WITH. Given one, the movement is
    written as a two-leg voucher — the cash book on one side, that party's
    account on the other — so the trial balance can prove it and the party's
    balance is the whole story rather than half of it. Without one it stays
    the single line it has always been.

    Never raises: the money has already moved, and a bookkeeping failure must
    not undo it.
    """
    try:
        code = slug(payment_mode or "")
        if not (payment_mode or "").strip():
            return False  # not a physical-money movement — nothing to record
        amt = quantize_money(to_decimal(amount))
        if amt <= ZERO:
            return False

        oid = PydanticObjectId(str(owner_id))
        book = await LedgerBook.find_one({"owner_id": oid, "code": code})
        if book is None:
            # This owner has never used this mode. Open their book for it
            # rather than dropping the line: the money moved, and a movement
            # with nowhere to land is exactly what a ledger must never allow.
            book = await _open_book_for(oid, code)
            if book is None:
                return False

        pbook = None
        if party_user_id is not None:
            pbook = await party_book(oid, user_id=party_user_id,
                                     name=party_name or particulars)
        vid = PydanticObjectId() if pbook is not None else None
        vtype = VoucherType.RECEIPT if is_inflow else VoucherType.PAYMENT

        await LedgerBookEntry(
            book_id=book.id, owner_id=oid, voucher_id=vid,
            entry_date=when or now_utc(), voucher_type=vtype,
            voucher_no=str(voucher_no or "")[:32],
            particulars=particulars or (pbook.name if pbook else ""),
            narration=narration,
            debit=_d128(amt) if is_inflow else _d128(0),
            credit=_d128(0) if is_inflow else _d128(amt),
            source_type=source_type, source_id=str(source_id), is_auto=is_auto,
        ).insert()

        if pbook is not None:
            # The mirror. Money arriving is the party's credit — they gave it
            # and can ask for it back; money going out is their debit.
            await LedgerBookEntry(
                book_id=pbook.id, owner_id=oid, voucher_id=vid,
                entry_date=when or now_utc(), voucher_type=vtype,
                voucher_no=str(voucher_no or "")[:32],
                particulars=book.name, narration=narration,
                debit=_d128(0) if is_inflow else _d128(amt),
                credit=_d128(amt) if is_inflow else _d128(0),
                source_type=source_type, source_id=str(source_id) + ":party",
                is_auto=is_auto,
            ).insert()
        return True
    except Exception:  # noqa: BLE001 — duplicate source_id, or anything else
        logger.debug("ledger_autopost_skipped src=%s/%s", source_type, source_id, exc_info=True)
        return False


# ── Party (per-admin) statement ──────────────────────────────────────
async def parties(owner_id) -> list[dict]:
    """Everyone this owner has actually moved money with, from the books.

    Read off the posted lines rather than the user list, so the picker only
    ever offers accounts that have something to show.
    """
    oid = PydanticObjectId(str(owner_id))
    # Beanie's FindMany has no .distinct() — go through the motor collection.
    coll = LedgerBookEntry.get_motor_collection()
    codes = [c for c in await coll.distinct("particulars", {"owner_id": oid}) if (c or "").strip()]
    if not codes:
        return []
    from app.services.admin_book_service import admin_type

    names: dict = {}
    types: dict = {}
    for u in await User.find({"user_code": {"$in": codes}}).to_list():
        names[u.user_code] = u.full_name or u.user_code
        # Which of the five arrangements they are on — the operator reads an
        # admin by that, not by their code.
        types[u.user_code] = admin_type(u)["n"]
    return sorted(
        ({"code": c, "name": names.get(c, c), "type_n": types.get(c, 0)} for c in codes),
        key=lambda x: x["name"].lower(),
    )


async def post_party_entry(
    owner_id, *, user_code: str, direction: str, amount, mode: str,
    entry_date: datetime | None = None, narration: str = "",
) -> dict:
    """Record money moved with ONE admin, through ONE ledger.

    This is the whole of the bookkeeping now. Adding or deducting an admin's
    coins used to write a ledger line as a side effect, which tied two things
    that are not the same event: coins are the platform's internal balance,
    while a ledger line is real money that arrived by cheque or UPI. They
    happen at different times, in different amounts, and one can happen
    without the other. So the super admin records them separately.

        RECEIVED  the admin gave you money  -> debit that ledger
        PAID      you gave the admin money  -> credit that ledger

    `is_auto=False`: the super admin typed this, so they can delete it again.
    A line the system wrote from a real movement stays protected.
    """
    d = (direction or "").strip().upper()
    if d not in ("RECEIVED", "PAID"):
        raise ValidationFailedError("Direction must be RECEIVED or PAID")
    code = (user_code or "").strip()
    if not code:
        raise ValidationFailedError("Pick the admin this entry belongs to")
    amt = quantize_money(to_decimal(amount or 0))
    if amt <= ZERO:
        raise ValidationFailedError("Enter an amount")
    if not (mode or "").strip():
        raise ValidationFailedError("Pick which ledger the money moved through")

    user = await User.find_one({"user_code": code})
    if user is None:
        raise NotFoundError("No admin with code " + code)

    when = entry_date or now_utc()
    ok = await post(
        owner_id, mode, amount=amt, is_inflow=(d == "RECEIVED"),
        particulars=code,
        narration=(narration or "").strip()
        or ("Received from " + code if d == "RECEIVED" else "Paid to " + code),
        source_type="MANUAL_PARTY",
        # Unique per line so two identical entries on one day both land — the
        # dedup that protects auto-posted rows must not swallow a real second
        # payment of the same amount.
        source_id="party:" + code + ":" + str(PydanticObjectId()),
        when=when, is_auto=False, party_user_id=user.id,
    )
    if not ok:
        raise ValidationFailedError("Could not post — check the ledger and amount")
    return {"ok": True, "code": code, "direction": d, "amount": str(amt)}


async def party_statement(owner_id, code: str, start: datetime | None = None,
                          end: datetime | None = None) -> dict:
    """One admin's account with you, across every ledger, as a party account.

        Dr  they owe you        Cr  you owe them

    Dr/Cr here follow the CASH BOOK, not its mirror. The books record only the
    cash leg of a funding, never the coin leg: "Received" takes the admin's
    money AND hands them that many coins, and only the first half reaches a
    ledger. Mirroring the cash leg therefore made the party balance read as the
    opposite of the real exposure — funding an admin showed as Cr, as though
    the platform owed them, when the coins had gone the other way.

    Operator's call, made against their own rows: funds given to an admin read
    Dr, funds pulled back read Cr. Note this carries the security rows with it
    — a security you hold now shows Dr as well.

    The cash books (Cash / UPI / bank) are untouched: money arriving there is a
    debit, which is ordinary accounting and is what their statements print.

    Type names the ledger the money actually moved through, so one line tells
    you both what happened and which account it went in and out of.
    """
    oid = PydanticObjectId(str(owner_id))
    party = (code or "").strip()
    if not party:
        raise ValidationFailedError("Pick an account")

    books = {b.id: b.name for b in await LedgerBook.find({"owner_id": oid}).to_list()}

    opening = ZERO
    if start is not None:
        for e in await LedgerBookEntry.find({
            "owner_id": oid, "particulars": party, "entry_date": {"$lt": start},
        }).to_list():
            opening += to_decimal(e.debit) - to_decimal(e.credit)

    q: dict = {"owner_id": oid, "particulars": party}
    if start is not None or end is not None:
        rng: dict = {}
        if start is not None:
            rng["$gte"] = start
        if end is not None:
            rng["$lte"] = end
        q["entry_date"] = rng

    rows: list[dict] = []
    running = opening
    total_dr = total_cr = ZERO
    for e in await LedgerBookEntry.find(q).sort("entry_date", "created_at").to_list():
        dr = to_decimal(e.debit)
        cr = to_decimal(e.credit)
        running += dr - cr
        total_dr += dr
        total_cr += cr
        rows.append({
            "id": str(e.id),
            "entry_date": e.entry_date.isoformat() if e.entry_date else None,
            "voucher_type": books.get(e.book_id, "Entry"),
            "voucher_no": e.voucher_no,
            "particulars": e.narration or ("Paid to " + party if cr > ZERO else "Received from " + party),
            "narration": "",
            "debit": str(quantize_money(dr)),
            "credit": str(quantize_money(cr)),
            "balance": str(quantize_money(abs(running))),
            "balance_side": "Dr" if running >= ZERO else "Cr",
            "is_auto": e.is_auto,
        })

    open_dr = opening if opening > ZERO else ZERO
    open_cr = -opening if opening < ZERO else ZERO
    sum_dr = total_dr + open_dr
    sum_cr = total_cr + open_cr
    name = party
    u = await User.find_one({"user_code": party})
    if u is not None:
        name = (u.full_name or party) + " (" + party + ")"
    return {
        "book": {"id": party, "name": name, "code": party, "is_payment_mode": False},
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
    }


# -- Double entry ------------------------------------------------------
async def post_voucher(
    owner_id, *, entry_date: datetime, legs: list[dict],
    voucher_type: str = "Jrnl", voucher_no: str = "", narration: str = "",
    source_type: str | None = None, source_id: str | None = None,
    is_auto: bool = False,
) -> str:
    """Write ONE voucher as two or more linked legs.

    `legs` is a list of ``{"book_id", "debit", "credit", "particulars"}``.
    Each leg lands in its own book and they all share a `voucher_id` — which
    is what turns Particulars from free text naming a contra account into a
    link something can actually follow.

    Debits and credits must sum to the same figure. That rule IS the feature:
    it is the only thing that makes a trial balance provable, so it is checked
    here rather than trusted to the caller.
    """
    if len(legs or []) < 2:
        raise ValidationFailedError("A voucher needs at least two accounts")

    prepared: list[tuple] = []
    total_dr = total_cr = ZERO
    for leg in legs:
        b = await _get_book(owner_id, leg.get("book_id"))
        dr = quantize_money(to_decimal(leg.get("debit") or 0))
        cr = quantize_money(to_decimal(leg.get("credit") or 0))
        if dr < ZERO or cr < ZERO:
            raise ValidationFailedError("Amounts cannot be negative")
        if (dr > ZERO) == (cr > ZERO):
            raise ValidationFailedError(
                "Each line is one side or the other - " + b.name + " has "
                + ("both" if dr > ZERO else "neither")
            )
        total_dr += dr
        total_cr += cr
        prepared.append((b, dr, cr, str(leg.get("particulars") or "").strip()))

    if total_dr != total_cr:
        raise ValidationFailedError(
            "Debit " + str(total_dr) + " and credit " + str(total_cr)
            + " must match - a voucher has to balance"
        )

    try:
        vt = VoucherType(voucher_type)
    except ValueError:
        vt = VoucherType.JOURNAL

    vid = PydanticObjectId()
    for i, (b, dr, cr, part) in enumerate(prepared):
        # Name the other side on every leg, so one row still reads on its own
        # the way a printed ledger line does.
        other = ", ".join(x[0].name for j, x in enumerate(prepared) if j != i)
        await LedgerBookEntry(
            book_id=b.id, owner_id=b.owner_id, voucher_id=vid,
            entry_date=entry_date or now_utc(),
            voucher_type=vt, voucher_no=str(voucher_no or "").strip(),
            particulars=part or other,
            narration=str(narration or "").strip(),
            debit=_d128(dr), credit=_d128(cr),
            source_type=source_type,
            # Legs share a source but must not collide on the unique
            # (source_type, source_id) guard, so each carries its index.
            source_id=(str(source_id) + ":" + str(i)) if source_id else None,
            is_auto=is_auto,
        ).insert()
    return str(vid)


async def party_book(owner_id, *, user_id=None, name: str = "") -> LedgerBook | None:
    """The third-party account for a person, opened on first use.

    Found by `party_user_id` rather than by name, so renaming an admin's
    ledger never orphans the rows already posted to it.
    """
    oid = PydanticObjectId(str(owner_id))
    if user_id is not None:
        uid = PydanticObjectId(str(user_id))
        found = await LedgerBook.find_one({"owner_id": oid, "party_user_id": uid})
        if found is not None:
            return found
    nm = (name or "").strip()
    if user_id is not None:
        # Name it off the user, and carry the code, so two admins who share a
        # first name cannot collide onto one account.
        u = await User.get(PydanticObjectId(str(user_id)))
        if u is not None:
            nm = ((u.full_name or u.user_code) + " · " + str(u.user_code)).strip()
    if not nm:
        return None
    found = await LedgerBook.find_one({"owner_id": oid, "name": nm})
    if found is not None:
        if user_id is not None and found.party_user_id is None:
            found.party_user_id = PydanticObjectId(str(user_id))
            await found.save()
        return found
    try:
        book = LedgerBook(
            owner_id=oid, name=nm, code=slug(nm),
            account_type=AccountType.PARTY,
            party_user_id=PydanticObjectId(str(user_id)) if user_id else None,
        )
        await book.insert()
        return book
    except Exception:  # noqa: BLE001 - raced; re-read the winner
        return await LedgerBook.find_one({"owner_id": oid, "name": nm})


async def income_book(owner_id, name: str) -> LedgerBook | None:
    """An income account, opened on first use.

    Brokerage, the share of a book's profit and the games result are EARNED
    the moment they are charged — the cash comes later, or not at all. They
    are income, so they get income accounts, and the cash book never sees
    them.
    """
    oid = PydanticObjectId(str(owner_id))
    nm = (name or "").strip()
    if not nm:
        return None
    found = await LedgerBook.find_one({"owner_id": oid, "name": nm})
    if found is not None:
        return found
    try:
        book = LedgerBook(owner_id=oid, name=nm, code=slug(nm),
                          account_type=AccountType.INCOME)
        await book.insert()
        return book
    except Exception:  # noqa: BLE001 - raced; re-read the winner
        return await LedgerBook.find_one({"owner_id": oid, "name": nm})


#: Which income account each kind of earning posts to.
EARNING_BOOKS = {
    "BROKERAGE": "Brokerage Income",
    "PNL_SHARE": "P&L Share Income",
    "GAMES_PNL": "Games Income",
}


async def post_earning(*, admin_id, kind: str, amount, narration: str = "",
                       source_id: str = "", when: datetime | None = None) -> bool:
    """Book what the super-admin earned off one admin, as a real voucher.

    Debit the admin — it is owed, not received — and credit the income
    account. A negative `amount` is the house losing (a player won), and the
    same voucher simply runs the other way.

    The money has already moved in the security ledger by the time this runs,
    so a bookkeeping failure here must never propagate.
    """
    try:
        book_name = EARNING_BOOKS.get(str(kind).upper())
        if not book_name:
            return False
        amt = quantize_money(to_decimal(amount))
        if amt == ZERO:
            return False

        sa = await User.find_one({"role": UserRole.SUPER_ADMIN.value})
        if sa is None:
            return False
        party = await party_book(sa.id, user_id=admin_id)
        income = await income_book(sa.id, book_name)
        if party is None or income is None:
            return False

        earned = amt > ZERO
        mag = abs(amt)
        await post_voucher(
            sa.id,
            entry_date=when or now_utc(),
            legs=[
                {"book_id": str(party.id),
                 "debit": mag if earned else 0, "credit": 0 if earned else mag,
                 "particulars": income.name},
                {"book_id": str(income.id),
                 "debit": 0 if earned else mag, "credit": mag if earned else 0,
                 "particulars": party.name},
            ],
            voucher_type="Jrnl",
            narration=narration or book_name,
            source_type="ADMIN_EARNING",
            source_id=source_id or ("earn:" + str(kind) + ":" + str(PydanticObjectId())),
            is_auto=True,
        )
        return True
    except Exception:  # noqa: BLE001 — the earning itself already stands
        logger.debug("earning_autopost_skipped kind=%s", kind, exc_info=True)
        return False


# -- Trial balance -----------------------------------------------------
async def trial_balance(owner_id, as_of: datetime | None = None) -> dict:
    """Every account's closing balance, and the proof that they square.

    A trial balance is only meaningful over DOUBLE-ENTRY rows. Single-sided
    legacy lines cannot balance against anything, so they are reported
    separately rather than quietly breaking the totals.
    """
    oid = PydanticObjectId(str(owner_id))
    books = await LedgerBook.find({"owner_id": oid}).to_list()
    by_id = {b.id: b for b in books}

    q: dict = {"owner_id": oid}
    if as_of is not None:
        q["entry_date"] = {"$lte": as_of}

    net: dict = {b.id: to_decimal(b.opening_balance) for b in books}
    unlinked_dr = unlinked_cr = ZERO
    for e in await LedgerBookEntry.find(q).to_list():
        _d, _c = cash_sides(e.debit, e.credit)
        net[e.book_id] = net.get(e.book_id, ZERO) + _d - _c
        if e.voucher_id is None:
            unlinked_dr += _d
            unlinked_cr += _c

    rows: list[dict] = []
    tot_dr = tot_cr = ZERO
    for bid, bal in net.items():
        b = by_id.get(bid)
        if b is None or bal == ZERO:
            continue
        dr = bal if bal > ZERO else ZERO
        cr = -bal if bal < ZERO else ZERO
        tot_dr += dr
        tot_cr += cr
        rows.append({
            "book_id": str(bid),
            "name": b.name,
            "account_type": getattr(b.account_type, "value", str(b.account_type)),
            "debit": str(quantize_money(dr)),
            "credit": str(quantize_money(cr)),
        })
    rows.sort(key=lambda r: (r["account_type"], r["name"].lower()))
    return {
        "as_of": as_of.isoformat() if as_of else None,
        "rows": rows,
        "total_debit": str(quantize_money(tot_dr)),
        "total_credit": str(quantize_money(tot_cr)),
        "difference": str(quantize_money(tot_dr - tot_cr)),
        "balanced": tot_dr == tot_cr,
        # Rows written before double entry existed. They sit in the balances
        # above but cannot square by themselves - surfaced so a mismatch has
        # an explanation instead of looking like a bug.
        "unlinked_debit": str(quantize_money(unlinked_dr)),
        "unlinked_credit": str(quantize_money(unlinked_cr)),
    }


async def day_book(owner_id, start: datetime | None = None,
                   end: datetime | None = None, limit: int = 500) -> list[dict]:
    """Every voucher in the period, newest first - one row per VOUCHER with
    its legs, not one row per line."""
    oid = PydanticObjectId(str(owner_id))
    q: dict = {"owner_id": oid}
    if start is not None or end is not None:
        rng: dict = {}
        if start is not None:
            rng["$gte"] = start
        if end is not None:
            rng["$lte"] = end
        q["entry_date"] = rng

    books = {b.id: b.name for b in await LedgerBook.find({"owner_id": oid}).to_list()}
    entries = await LedgerBookEntry.find(q).sort("-entry_date").limit(limit * 4).to_list()

    grouped: dict = {}
    order: list = []
    for e in entries:
        key = str(e.voucher_id) if e.voucher_id else "solo:" + str(e.id)
        if key not in grouped:
            grouped[key] = {
                "voucher_id": key,
                "entry_date": e.entry_date.isoformat() if e.entry_date else None,
                "voucher_type": getattr(e.voucher_type, "value", str(e.voucher_type)),
                "voucher_no": e.voucher_no,
                "narration": e.narration,
                "is_auto": e.is_auto,
                "legs": [],
                "amount": "0",
            }
            order.append(key)
        _d, _c = cash_sides(e.debit, e.credit)
        grouped[key]["legs"].append({
            "book": books.get(e.book_id, "?"),
            "debit": str(quantize_money(_d)),
            "credit": str(quantize_money(_c)),
        })

    out = []
    for key in order[:limit]:
        v = grouped[key]
        v["amount"] = str(quantize_money(
            sum((to_decimal(l["debit"]) for l in v["legs"]), ZERO)
        ))
        out.append(v)
    return out
