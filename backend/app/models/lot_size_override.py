"""Super-admin lot sizes: how many shares / units make one lot.

The platform's built-in lot sizes are coded tables (services/index_lots.py
for NSE / BSE / MCX F&O, services/infoway_lots.py for forex / crypto /
metals / international). A row here wins over those tables and over the
Zerodha CSV, so the super-admin can change a contract size without a code
change. Delete the row to go back to the built-in value.

One row per (market, underlying):

  * INDIAN — NSE / BSE / MCX futures and options. `underlying` is the
    contract's root, the letters before the expiry: NIFTY, BANKNIFTY,
    RELIANCE, GOLDM, CRUDEOIL. Equity cash is always 1 share = 1 lot.
  * INTERNATIONAL — the Infoway feed (forex, crypto, spot metals and
    energy, international indices and stocks). `underlying` is the symbol:
    EURUSD, XAUUSD, BTCUSD. BTC options use BTC.

Resolved by services/lot_overrides.py.
"""

from __future__ import annotations

from beanie import PydanticObjectId
from pymongo import ASCENDING, IndexModel

from app.models._base import StrEnum, TimestampMixin


class LotMarket(StrEnum):
    INDIAN = "INDIAN"
    INTERNATIONAL = "INTERNATIONAL"


class LotSizeOverride(TimestampMixin):
    market: LotMarket
    #: Upper-case root (INDIAN) or symbol (INTERNATIONAL).
    underlying: str
    lot_size: int
    note: str = ""
    updated_by: PydanticObjectId | None = None

    class Settings:
        name = "lot_size_overrides"
        indexes = [
            IndexModel([("market", ASCENDING), ("underlying", ASCENDING)], unique=True),
        ]
