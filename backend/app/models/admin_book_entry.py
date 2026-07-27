"""Admin-book per-trade attribution record.

One row per CLOSING trade leg while the admin-book model is enabled. Records
exactly how a single trade's house result + brokerage was booked to the owning
admin and how much the super-admin (SA) skimmed as its PnL / brokerage share.

This is the source for the SA "Earnings" drill-down report (admin → user →
trade). It is written alongside the actual wallet moves (ADMIN_BOOK_* /
SA_*_SHARE transactions) so the report is an exact mirror of the money that
moved — never a recomputed estimate.

Sign conventions (all Decimal128, IST-stored-UTC timestamps):
  • house_pnl_inr   = −(user realized PnL). Positive when the user LOST.
  • brokerage_inr   = brokerage the user paid on this trade (≥ 0).
  • sa_pnl_share_inr = house_pnl_inr × pnl_pct%.  Signed (SA earns on user loss,
                       SA pays on user profit).
  • sa_bkg_share_inr = brokerage_inr × bkg_pct%.  Always ≥ 0.
  • admin_net_inr   = house_pnl_inr + brokerage_inr − sa_pnl_share − sa_bkg_share.
  • sa_net_inr      = sa_pnl_share_inr + sa_bkg_share_inr.
"""

from __future__ import annotations

from datetime import datetime

from beanie import Indexed, PydanticObjectId
from bson import Decimal128
from pymongo import ASCENDING, DESCENDING, IndexModel

from app.models._base import TimestampMixin


class AdminBookEntry(TimestampMixin):
    trade_id: str
    order_id: str | None = None
    user_id: Indexed(PydanticObjectId)   # type: ignore[valid-type]
    admin_id: Indexed(PydanticObjectId)  # type: ignore[valid-type]  # book holder (owning admin)
    sa_id: PydanticObjectId              # super-admin that skims

    segment: str                          # instrument segment string
    instrument_symbol: str | None = None

    # Locked snapshots of the share % applied (audit — an admin's % may change).
    pnl_pct_snapshot: Decimal128 = Decimal128("0")
    bkg_pct_snapshot: Decimal128 = Decimal128("0")

    # The money (see module docstring for signs).
    house_pnl_inr: Decimal128 = Decimal128("0")
    brokerage_inr: Decimal128 = Decimal128("0")
    sa_pnl_share_inr: Decimal128 = Decimal128("0")
    sa_bkg_share_inr: Decimal128 = Decimal128("0")
    admin_net_inr: Decimal128 = Decimal128("0")
    sa_net_inr: Decimal128 = Decimal128("0")

    booked_at: datetime | None = None

    class Settings:
        name = "admin_book_entries"
        use_state_management = True
        indexes = [
            # Idempotency: never book the same closing leg twice.
            IndexModel([("trade_id", ASCENDING)], unique=True, name="uniq_trade"),
            IndexModel([("admin_id", ASCENDING), ("created_at", DESCENDING)]),
            IndexModel([("admin_id", ASCENDING), ("user_id", ASCENDING), ("created_at", DESCENDING)]),
            IndexModel([("sa_id", ASCENDING), ("created_at", DESCENDING)]),
        ]
