"""Per-admin security money — collateral, and what it settles against.

An admin lodges a security deposit with the super-admin. That collateral then
absorbs everything the super-admin is owed by, or owes to, that admin's book:

    a user of theirs LOSES a game -> security DOWN, payable UP
    a user of theirs WINS  a game -> security UP,   payable unchanged
    SA's fixed brokerage on their
    users' trades                 -> security DOWN, payable unchanged

so the balance always reads "what is left of this admin's collateral".

`payable` is the other half: what the super-admin owes this admin out of their
book's losses. It starts at ZERO — lodging collateral does NOT create it,
because that money is being HELD, not earned. It comes down one way only:

    SA tops the security up from its OWN main wallet -> security UP, payable DOWN

Brokerage never touches payable either: it is the super-admin's earning, so it
consumes collateral without changing who is owed what.

Every movement writes an `AdminSecurityEntry`, so a balance can always be
explained by replaying its rows rather than trusted on its own.
"""

from __future__ import annotations

from beanie import PydanticObjectId
from pymongo import ASCENDING, DESCENDING, IndexModel

from app.models._base import StrEnum, TimestampMixin
from app.models._types import Money
from bson import Decimal128
from pydantic import Field


def _zero() -> Decimal128:
    return Decimal128("0")


class SecurityEntryType(StrEnum):
    DEPOSIT = "DEPOSIT"          # admin lodged money      security+
    WITHDRAW = "WITHDRAW"        # returned to the admin   security-
    SA_TOPUP = "SA_TOPUP"        # SA funded from its own  security+ payable-
    GAMES_PNL = "GAMES_PNL"      # games result            security± payable+ on a loss
    BROKERAGE = "BROKERAGE"      # SA's fixed brokerage    security-
    PNL_SHARE = "PNL_SHARE"      # SA's share of the book  security- (+ when SA pays)
    ADJUSTMENT = "ADJUSTMENT"    # manual correction       security±


class AdminSecurity(TimestampMixin):
    """One row per admin. Balances are derived state — the ledger is truth."""

    admin_id: PydanticObjectId
    security_balance: Money = Field(default_factory=_zero)
    payable_balance: Money = Field(default_factory=_zero)
    # Lifetime rollups, for the card without re-aggregating the ledger.
    total_deposited: Money = Field(default_factory=_zero)
    total_games_in: Money = Field(default_factory=_zero)   # collected from losses
    total_games_out: Money = Field(default_factory=_zero)  # paid on wins
    total_brokerage: Money = Field(default_factory=_zero)  # SA's fixed brokerage taken
    #: This admin's own consumed-percentage limit. None = follow the platform
    #: figure. One admin's book can be trusted further than another's, and the
    #: super-admin sets that per account rather than for everyone at once.
    cap_pct: float | None = None

    class Settings:
        name = "admin_security"
        indexes = [IndexModel([("admin_id", ASCENDING)], unique=True)]


class AdminSecurityEntry(TimestampMixin):
    admin_id: PydanticObjectId
    entry_type: SecurityEntryType
    # Signed as applied to `security_balance`: + adds collateral, - consumes it.
    amount: Money = Field(default_factory=_zero)
    security_after: Money = Field(default_factory=_zero)
    payable_after: Money = Field(default_factory=_zero)
    narration: str = ""
    payment_mode: str | None = None      # DEPOSIT / WITHDRAW only
    game_key: str | None = None          # GAMES_PNL only
    trade_id: str | None = None          # BROKERAGE only — the trade it was charged on
    user_id: PydanticObjectId | None = None   # the player / trader it came from
    actor_id: PydanticObjectId | None = None

    class Settings:
        name = "admin_security_entries"
        indexes = [
            IndexModel([("admin_id", ASCENDING), ("created_at", DESCENDING)]),
            IndexModel([("created_at", DESCENDING)]),
        ]
