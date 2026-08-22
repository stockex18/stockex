"""Per-admin security money + payable ledger.

An admin lodges a security deposit with the super-admin. That deposit then
ABSORBS the games exposure of the admin's own users:

    a user of theirs LOSES   -> the house collected  -> security goes UP
    a user of theirs WINS    -> the house paid out   -> security goes DOWN

so the balance always reads "what is left of this admin's collateral after
their book's games result".

`payable` is the other half of the same relationship — what the super-admin
owes this admin back:

    admin hands over security      -> payable UP   (it is their money)
    SA tops the security up from
    its OWN main wallet            -> payable DOWN (SA put its own money in)

Games settlement never touches payable: it moves the collateral, not who owns
it.

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
    DEPOSIT = "DEPOSIT"          # admin lodged money      security+ payable+
    WITHDRAW = "WITHDRAW"        # returned to the admin   security- payable-
    SA_TOPUP = "SA_TOPUP"        # SA funded from its own  security+ payable-
    GAMES_PNL = "GAMES_PNL"      # games result            security±
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
    user_id: PydanticObjectId | None = None   # the player, for GAMES_PNL
    actor_id: PydanticObjectId | None = None

    class Settings:
        name = "admin_security_entries"
        indexes = [
            IndexModel([("admin_id", ASCENDING), ("created_at", DESCENDING)]),
            IndexModel([("created_at", DESCENDING)]),
        ]
