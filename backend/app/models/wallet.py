"""Wallet — single document per user holding all balance figures.

Money is stored as Decimal128. Updates must occur inside MongoDB transactions
(see services/wallet_service.py).
"""

from __future__ import annotations

from beanie import Indexed, PydanticObjectId
from bson import Decimal128
from pydantic import Field
from pymongo import ASCENDING, IndexModel

from app.models._base import TimestampMixin
from app.models._types import Money


def _zero() -> Decimal128:
    return Decimal128("0")


class Wallet(TimestampMixin):
    user_id: Indexed(PydanticObjectId, unique=True)  # type: ignore[valid-type]

    available_balance: Money = Field(default_factory=_zero)
    used_margin: Money = Field(default_factory=_zero)
    realized_pnl: Money = Field(default_factory=_zero)
    unrealized_pnl: Money = Field(default_factory=_zero)
    credit_limit: Money = Field(default_factory=_zero)

    # Unrecovered settlement loss — when a stop-out force-close booked a
    # realized loss that exceeded available_balance + credit_limit, the
    # uncoverable shortfall sits here. Recovered automatically against the
    # next DEPOSIT (deducted before crediting available_balance). Read-only
    # for the user; modified only by wallet_service.force_debit and the
    # DEPOSIT recovery branch in wallet_service.adjust.
    settlement_outstanding: Money = Field(default_factory=_zero)

    total_deposits: Money = Field(default_factory=_zero)
    total_withdrawals: Money = Field(default_factory=_zero)
    total_brokerage: Money = Field(default_factory=_zero)
    total_charges: Money = Field(default_factory=_zero)

    # ── Games hierarchy "temporary wallet" (held earnings) ──────────────
    # Mirrors D:\Stockex's Admin.temporaryWallet. Games hierarchy commission
    # for ADMIN/BROKER tiers accrues here (NOT into available_balance) until a
    # super-admin RELEASES it into the main wallet. SUPER_ADMIN's own share is
    # the house itself and never uses this bucket. Purely additive — no
    # existing trading path reads/writes these.
    temporary_balance: Money = Field(default_factory=_zero)
    temporary_total_earned: Money = Field(default_factory=_zero)
    temporary_total_released: Money = Field(default_factory=_zero)

    # ── Kuber wallet (SUPER_ADMIN-only house pool) ──────────────────────
    # Mirrors D:\Stockex's Admin.kuberWallet. A distributable pool (capped at
    # 🪙100 cr) SEPARATE from the SA's personal `available_balance`, used to
    # fund downstream franchise / patti payouts. When the SA funds an admin's
    # share, part comes from `kuber_balance` (pooled) and part from
    # `available_balance` (personal), per the funding plan. Meaningful ONLY on
    # the SUPER_ADMIN wallet; stays 0 for everyone else. Additive.
    kuber_balance: Money = Field(default_factory=_zero)
    kuber_total_in: Money = Field(default_factory=_zero)
    kuber_total_out: Money = Field(default_factory=_zero)

    # ── SA Cash Wallet (SUPER_ADMIN-only) — the capital pool the SA tops up and
    # funds ADMINS from. SEPARATE from kuber (house/games pool). The SA Ledger
    # shows: topped-up (in) − given-to-admins (out) = balance. Top-up credits it;
    # funding an admin (admin_fund_service, actor=SA) debits it. Additive; 0 for
    # everyone but the super-admin.
    sa_cash_balance: Money = Field(default_factory=_zero)
    sa_cash_total_in: Money = Field(default_factory=_zero)   # total topped up
    sa_cash_total_out: Money = Field(default_factory=_zero)  # total funded to admins

    # Optimistic-locking version. Increment on each financial mutation.
    version: int = 0

    class Settings:
        name = "wallets"
        indexes = [IndexModel([("user_id", ASCENDING)], unique=True)]
