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
from datetime import datetime
from decimal import Decimal

from beanie import PydanticObjectId
from bson import Decimal128

from app.core.exceptions import NotFoundError, ValidationFailedError
from app.models.ledger_book import (
    FED_KINDS,
    LedgerBook,
    LedgerBookEntry,
    LedgerKind,
    VoucherType,
)
from app.utils.decimal_utils import quantize_money, to_decimal
from app.utils.time_utils import now_utc

logger = logging.getLogger(__name__)
ZERO = Decimal("0")

#: Seeded for every owner on first use, so the five payment modes always have
#: somewhere to post even if nobody created a book by hand.
DEFAULT_BOOKS: tuple[tuple[str, LedgerKind], ...] = (
    ("Cash", LedgerKind.CASH),
    ("Cheque", LedgerKind.CHEQUE),
    ("Bank", LedgerKind.BANKING),
    ("UPI", LedgerKind.UPI),
    ("Others", LedgerKind.OTHERS),
)


def _d128(v) -> Decimal128:
    return Decimal128(str(quantize_money(to_decimal(v))))


# ── Books ────────────────────────────────────────────────────────────
async def ensure_default_books(owner_id) -> None:
    """Create the five mode books for this owner if they are missing."""
    oid = PydanticObjectId(str(owner_id))
    have = {
        b.kind
        for b in await LedgerBook.find({"owner_id": oid, "kind": {"$in": [k.value for k in FED_KINDS]}}).to_list()
    }
    for name, kind in DEFAULT_BOOKS:
        if kind in have:
            continue
        try:
            await LedgerBook(owner_id=oid, name=name, kind=kind).insert()
        except Exception:  # noqa: BLE001 — someone else seeded it first
            logger.debug("ledger_seed_race kind=%s", kind)


async def list_books(owner_id, include_archived: bool = False) -> list[dict]:
    oid = PydanticObjectId(str(owner_id))
    await ensure_default_books(oid)
    q: dict = {"owner_id": oid}
    if not include_archived:
        q["is_archived"] = {"$ne": True}
    books = await LedgerBook.find(q).sort("kind", "name").to_list()
    out = []
    for b in books:
        out.append({
            "id": str(b.id),
            "name": b.name,
            "kind": b.kind.value if hasattr(b.kind, "value") else str(b.kind),
            "opening_balance": str(b.opening_balance),
            "opening_date": b.opening_date.isoformat() if b.opening_date else None,
            "note": b.note,
            "is_archived": b.is_archived,
            "is_fed": b.kind in FED_KINDS,
        })
    return out


async def create_book(owner_id, name: str, *, kind: str = "CUSTOM",
                      opening_balance=0, opening_date: datetime | None = None,
                      note: str = "") -> LedgerBook:
    nm = (name or "").strip()
    if not nm:
        raise ValidationFailedError("Give the ledger a name")
    try:
        k = LedgerKind(str(kind or "CUSTOM").upper())
    except ValueError:
        raise ValidationFailedError("Unknown ledger kind") from None
    oid = PydanticObjectId(str(owner_id))
    if await LedgerBook.find_one({"owner_id": oid, "name": nm}) is not None:
        raise ValidationFailedError("You already keep a ledger called " + nm)
    book = LedgerBook(
        owner_id=oid, name=nm, kind=k,
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
                      opening_date=None, note=None, is_archived=None) -> LedgerBook:
    b = await _get_book(owner_id, book_id)
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
    """Drop a ledger and its lines. Refuses the auto-fed ones — money would
    keep arriving for a book that no longer exists."""
    b = await _get_book(owner_id, book_id)
    if b.kind in FED_KINDS:
        raise ValidationFailedError(
            "The " + b.name + " ledger is fed automatically — archive it instead of deleting"
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
            opening += to_decimal(e.debit) - to_decimal(e.credit)

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
        dr = to_decimal(e.debit)
        cr = to_decimal(e.credit)
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
            "kind": b.kind.value if hasattr(b.kind, "value") else str(b.kind),
            "is_fed": b.kind in FED_KINDS,
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


# ── Auto-posting ─────────────────────────────────────────────────────
async def post(owner_id, payment_mode: str | None, *, amount, is_inflow: bool,
               particulars: str = "", narration: str = "",
               source_type: str, source_id: str,
               voucher_no: str = "", when: datetime | None = None) -> bool:
    """Record one money movement in the book for its payment mode.

    `is_inflow` is from the BOOK's point of view: money arriving is a debit,
    money leaving is a credit. Returns False when there is nothing to post —
    no mode was stamped, or this movement is already in the book.

    Never raises: the money has already moved, and a bookkeeping failure must
    not undo it.
    """
    try:
        mode = (payment_mode or "").strip().upper()
        if not mode:
            return False  # not a physical-money movement — nothing to record
        try:
            kind = LedgerKind(mode)
        except ValueError:
            kind = LedgerKind.OTHERS
        if kind not in FED_KINDS:
            return False
        amt = quantize_money(to_decimal(amount))
        if amt <= ZERO:
            return False

        oid = PydanticObjectId(str(owner_id))
        await ensure_default_books(oid)
        book = await LedgerBook.find_one({"owner_id": oid, "kind": kind.value})
        if book is None:
            return False

        await LedgerBookEntry(
            book_id=book.id, owner_id=oid, entry_date=when or now_utc(),
            voucher_type=VoucherType.RECEIPT if is_inflow else VoucherType.PAYMENT,
            voucher_no=str(voucher_no or "")[:32],
            particulars=particulars, narration=narration,
            debit=_d128(amt) if is_inflow else _d128(0),
            credit=_d128(0) if is_inflow else _d128(amt),
            source_type=source_type, source_id=str(source_id), is_auto=True,
        ).insert()
        return True
    except Exception:  # noqa: BLE001 — duplicate source_id, or anything else
        logger.debug("ledger_autopost_skipped src=%s/%s", source_type, source_id, exc_info=True)
        return False
