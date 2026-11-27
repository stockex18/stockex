"""Instrument-wise overnight premium (super admin only).

One row per instrument the super admin priced separately in Segment Settings →
Premium. `scope_admin_id` None = platform-wide (the main settings page); set =
only that admin's users (the per-admin "Segment settings · <admin>" window).

An instrument rule beats the segment-level premium; within rules, the user's
own admin's rule beats the platform one. See services/premium_charge_service.py.
"""

from __future__ import annotations

from typing import Literal

from beanie import PydanticObjectId
from pymongo import ASCENDING, IndexModel

from app.models._base import TimestampMixin


class PremiumRule(TimestampMixin):
    scope_admin_id: PydanticObjectId | None = None
    segment_name: str  # admin matrix row, e.g. "CRYPTO", "CRYPTO_OPT"
    symbol: str  # upper-case instrument symbol, e.g. "BTCUSD"

    premiumType: Literal["percentage", "fixed"] = "percentage"
    premiumCharge: float = 0.0
    premiumOn: Literal["buy", "sell", "both"] = "both"
    premiumTime: str = "22:30"  # HH:MM IST

    class Settings:
        name = "premium_rules"
        indexes = [
            IndexModel(
                [("scope_admin_id", ASCENDING), ("segment_name", ASCENDING), ("symbol", ASCENDING)],
                unique=True,
            ),
        ]
