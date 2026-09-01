"""Named ledger accounts, the way accounting software keeps them.

A `LedgerBook` is one account you keep — a payment mode like Cash or a bank,
or a party like "M/S DEEPAK ENTERPRISES". A `LedgerBookEntry` is one posted
line in it. The balance is never stored: it is the opening balance replayed
through the lines, so a statement can always be re-derived and can never
silently drift from the rows that explain it.

Sign convention is the ordinary one, and everything downstream depends on it:

    debit  -> the account's value goes UP   (money came in)
    credit -> the account's value goes DOWN (money went out)

    running = opening + sum(debit) - sum(credit)   positive => Dr, negative => Cr

A book flagged `is_payment_mode` doubles as a PAYMENT MODE: it appears in the
"how did this money move?" dropdowns, and any movement stamped with its `code`
posts itself into it. Nothing is preset — the super-admin creates the modes it
actually uses, and creating one is the same act as opening its ledger.

`code` is the stable identity. It is stamped onto every money movement and is
never changed, so renaming a ledger re-labels it everywhere without orphaning
a single historical row.
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


class AccountType(StrEnum):
    """What KIND of account this book is — the light version of Tally's groups.

    Enough to read a trial balance sensibly (cash and bank on one side, the
    parties who owe you on the other) without dragging in a full chart of
    accounts nobody here has asked for.
    """

    CASH = "CASH"        # notes in hand
    BANK = "BANK"        # a bank / OD account
    PARTY = "PARTY"      # a third party — an admin, a firm, a person
    EXPENSE = "EXPENSE"  # rent, salary, charges — money spent, not owed
    OTHER = "OTHER"


class VoucherType(StrEnum):
    RECEIPT = "Rcpt"
    PAYMENT = "Pymt"
    JOURNAL = "Jrnl"


class LedgerBook(TimestampMixin):
    owner_id: PydanticObjectId          # the admin who keeps this book
    name: str
    #: Uppercase slug, set once at creation and never edited. This is what gets
    #: stamped on a money movement as its payment mode.
    code: str = ""
    #: Offer this book as a payment mode in the money dropdowns.
    is_payment_mode: bool = False
    #: Cash / Bank / Party / Other — groups the trial balance.
    account_type: AccountType = AccountType.OTHER
    #: For a PARTY book, whose account it is. Lets an admin's ledger be found
    #: without matching on a name someone may later rename.
    party_user_id: PydanticObjectId | None = None
    #: Carried forward from before the first line. Signed like a debit:
    #: positive = opening Dr, negative = opening Cr.
    opening_balance: Money = Field(default_factory=_zero)
    opening_date: datetime | None = None
    note: str = ""
    is_archived: bool = False

    class Settings:
        name = "ledger_books"
        indexes = [
            # One book per name per owner — a second "Cash" that half the
            # entries land in is worse than a rejected create.
            IndexModel([("owner_id", ASCENDING), ("name", ASCENDING)], unique=True),
            IndexModel([("owner_id", ASCENDING), ("code", ASCENDING)]),
            IndexModel([("is_payment_mode", ASCENDING)]),
            IndexModel([("owner_id", ASCENDING), ("party_user_id", ASCENDING)]),
            IndexModel([("owner_id", ASCENDING), ("account_type", ASCENDING)]),
        ]


class LedgerBookEntry(TimestampMixin):
    """One LEG of a voucher — a single line in a single book.

    Legs sharing a `voucher_id` are one voucher, and their debits and credits
    sum to zero. That link is what makes a trial balance possible: without it
    "Particulars" is only free text naming a contra account nobody can follow.
    """

    book_id: PydanticObjectId
    owner_id: PydanticObjectId
    #: Ties this leg to its siblings. Null on legacy single-sided rows, which
    #: are left exactly as they were — they simply do not participate in the
    #: balance proof.
    voucher_id: PydanticObjectId | None = None
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
            IndexModel([("voucher_id", ASCENDING)]),
            IndexModel([("owner_id", ASCENDING), ("voucher_id", ASCENDING)]),
            IndexModel([("owner_id", ASCENDING), ("entry_date", DESCENDING)]),
            # The idempotency guard for auto-posting. Sparse: manual lines
            # leave both fields null and must not collide with each other.
            IndexModel(
                [("source_type", ASCENDING), ("source_id", ASCENDING)],
                unique=True, sparse=True,
            ),
        ]
