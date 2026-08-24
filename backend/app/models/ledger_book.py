"""Named ledger accounts, the way accounting software keeps them.

A `LedgerBook` is one account you keep — Cash, Cheque, a bank OD, a party like
"M/S DEEPAK ENTERPRISES". A `LedgerBookEntry` is one posted line in it. The
balance is never stored: it is the opening balance replayed through the lines,
so a statement can always be re-derived and can never silently drift from the
rows that explain it.

Sign convention is the ordinary one, and everything downstream depends on it:

    debit  -> the account's value goes UP   (cash came in)
    credit -> the account's value goes DOWN (cash went out)

    running = opening + Σdebit - Σcredit      positive => Dr, negative => Cr

The five payment modes the platform already records on money movements
(Cash / Cheque / Banking / UPI / Others) each get a `kind`, so a movement
stamped with that mode posts itself into the matching book automatically.
`CUSTOM` books have no feed and hold only what you enter by hand.
"""

from __future__ import annotations

from datetime import datetime

from beanie import PydanticObjectId
from bson import Decimal128
from pydantic import Field
from pymongo import ASCENDING, DESCENDING, IndexModel

from app.models._base import StrEnum, TimestampMixin
from app.models._types import Money


def _zero() -> Decimal128:
    return Decimal128("0")


class LedgerKind(StrEnum):
    """What feeds this book. The first five mirror the platform's payment modes."""

    CASH = "CASH"
    CHEQUE = "CHEQUE"
    BANKING = "BANKING"
    UPI = "UPI"
    OTHERS = "OTHERS"
    CUSTOM = "CUSTOM"      # manual only — a party or any account you name


#: The modes that auto-post. A book of any other kind is hand-kept.
FED_KINDS = (LedgerKind.CASH, LedgerKind.CHEQUE, LedgerKind.BANKING, LedgerKind.UPI, LedgerKind.OTHERS)


class VoucherType(StrEnum):
    RECEIPT = "Rcpt"
    PAYMENT = "Pymt"
    JOURNAL = "Jrnl"


class LedgerBook(TimestampMixin):
    owner_id: PydanticObjectId          # the admin who keeps this book
    name: str
    kind: LedgerKind = LedgerKind.CUSTOM
    #: Carried forward from before the first line. Signed like a debit:
    #: positive = opening Dr, negative = opening Cr.
    opening_balance: Money = Field(default_factory=_zero)
    opening_date: datetime | None = None
    note: str = ""
    is_archived: bool = False

    class Settings:
        name = "ledger_books"
        indexes = [
            # One book per name per owner — re-running the seed must not
            # quietly create a second "Cash" that half the entries land in.
            IndexModel([("owner_id", ASCENDING), ("name", ASCENDING)], unique=True),
            IndexModel([("owner_id", ASCENDING), ("kind", ASCENDING)]),
        ]


class LedgerBookEntry(TimestampMixin):
    book_id: PydanticObjectId
    owner_id: PydanticObjectId
    entry_date: datetime
    voucher_type: VoucherType = VoucherType.JOURNAL
    voucher_no: str = ""
    particulars: str = ""               # the contra account / who it was with
    narration: str = ""
    debit: Money = Field(default_factory=_zero)
    credit: Money = Field(default_factory=_zero)
    #: Set on auto-posted lines so they can be traced back, and so the same
    #: money movement can never be posted twice.
    source_type: str | None = None      # "ADMIN_FUND" / "ADMIN_SECURITY" / None = manual
    source_id: str | None = None
    is_auto: bool = False

    class Settings:
        name = "ledger_book_entries"
        indexes = [
            IndexModel([("book_id", ASCENDING), ("entry_date", ASCENDING)]),
            IndexModel([("owner_id", ASCENDING), ("entry_date", DESCENDING)]),
            # The idempotency guard for auto-posting. Sparse: manual lines
            # leave both fields null and must not collide with each other.
            IndexModel(
                [("source_type", ASCENDING), ("source_id", ASCENDING)],
                unique=True, sparse=True,
            ),
        ]
