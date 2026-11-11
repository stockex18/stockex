"""One Zerodha-vs-Fyers price comparison, taken when a MARKET order was placed.

Written in the background after the fill; never on the order's critical path.
The raw Fyers bid / ask / LTP are kept (not just the verdict) so that if the
mismatch rule changes, old rows can be judged again under the new rule.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from beanie import PydanticObjectId
from pydantic import Field
from pymongo import ASCENDING, DESCENDING, IndexModel

from app.models._base import StrEnum, TimestampMixin
from app.models._types import Money
from app.utils.time_utils import now_utc


class PriceCheckStatus(StrEnum):
    OK = "OK"
    MISMATCH = "MISMATCH"
    #: Fyers could not answer (not connected, timeout, unknown symbol …).
    #: The reason is in `note`. The order itself filled as normal.
    NOT_CHECKED = "NOT_CHECKED"


class FyersPriceCheck(TimestampMixin):
    order_id: PydanticObjectId
    order_number: str = ""
    trade_id: PydanticObjectId | None = None
    user_id: PydanticObjectId
    user_code: str = ""
    user_name: str = ""

    token: str
    symbol: str
    exchange: str
    fyers_symbol: str | None = None
    action: str  # BUY / SELL
    quantity: float = 0
    tick_size: Money | None = None

    # Zerodha quote snapshot at placement, and the price we compared.
    zerodha_ltp: Money | None = None
    zerodha_bid: Money | None = None
    zerodha_ask: Money | None = None
    #: BUY → Zerodha ask, SELL → Zerodha bid (LTP when that side is empty).
    compared_price: Money | None = None
    #: What the order actually filled at (may include a broker spread markup).
    fill_price: Money | None = None

    # Fyers quote at placement.
    fyers_ltp: Money | None = None
    fyers_bid: Money | None = None
    fyers_ask: Money | None = None
    #: How far `compared_price` sits outside the Fyers range (0 when inside).
    difference: Money | None = None

    status: PriceCheckStatus
    note: str | None = None
    fyers_latency_ms: int | None = None

    placed_at: datetime = Field(default_factory=now_utc)
    expires_at: datetime = Field(default_factory=lambda: now_utc() + timedelta(days=90))

    class Settings:
        name = "fyers_price_checks"
        indexes = [
            IndexModel([("placed_at", DESCENDING)]),
            IndexModel([("status", ASCENDING), ("placed_at", DESCENDING)]),
            IndexModel([("user_id", ASCENDING), ("placed_at", DESCENDING)]),
            IndexModel([("order_id", ASCENDING)]),
            IndexModel([("expires_at", ASCENDING)], expireAfterSeconds=0),
        ]
