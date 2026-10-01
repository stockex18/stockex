"""Trade — a single fill produced by the internal matching engine.

One Order may generate multiple Trades (partial fills). Charges are split
proportionally across fills.
"""

from __future__ import annotations

from datetime import datetime

from beanie import Indexed, PydanticObjectId
from bson import Decimal128
from pydantic import Field
from pymongo import ASCENDING, DESCENDING, IndexModel

from app.models._base import OrderAction, ProductType, TimestampMixin
from app.models._types import Money
from app.models.order import InstrumentRef
from app.utils.time_utils import now_utc


def _zero() -> Decimal128:
    return Decimal128("0")


class Trade(TimestampMixin):
    trade_number: Indexed(str, unique=True)  # type: ignore[valid-type]
    # None for a fill nobody placed: an expiry settlement closes the position
    # from the clearing side, so there is no Order behind it. The only reader
    # (`admin/trading.py`) already guards with getattr.
    order_id: PydanticObjectId | None = None
    user_id: PydanticObjectId

    instrument: InstrumentRef
    action: OrderAction
    product_type: ProductType

    quantity: float
    price: Money
    value: Money = Field(default_factory=_zero)  # quantity * price

    # The only charge users pay on this platform is the platform's own
    # brokerage. No statutory pass-through (STT / exchange / SEBI / stamp /
    # DP / GST) — admin policy.
    brokerage: Money = Field(default_factory=_zero)
    total_charges: Money = Field(default_factory=_zero)  # = brokerage
    net_amount: Money = Field(default_factory=_zero)  # value ± total_charges

    # Realized P&L in INR, captured at fill time. Set only on closing fills
    # (legs that reduce or flatten a position); opening fills leave it None.
    # For USD-quoted instruments (Infoway feed) we snapshot the USD/INR
    # rate at execute time and bake the conversion in here — the History
    # tab then renders this stored value directly instead of recomputing
    # against a live LTP, so closed-trade P&L is fixed forever and shown
    # in INR regardless of how the underlying instrument is quoted.
    # Already net of the closing-leg brokerage (when `chargeOn` includes
    # the close), so the displayed P&L matches the user's true cost.
    pnl_inr: Money | None = None

    # Set True when an admin REOPEN (or DELETE) undoes the close this trade
    # belongs to. The close fill stays in the collection for the audit trail,
    # but the user-facing Closed blotter (list_closed_trade_events_fifo) hides
    # superseded fills so a reopened-then-reclosed position shows only its
    # FINAL close — matching the admin Position-doc view. The wallet P&L is
    # already netted via the reopen's REVERSAL; this only governs display.
    superseded_by_reopen: bool = False

    # ── Per-fill bracket ─────────────────────────────────────────────
    # A stop / target belonging to THIS fill, not to the whole position.
    #
    # The Active tab is a per-fill view: each row is one entry, with its own
    # price, its own P&L and its own Exit. Its SL/TP buttons wrote to the
    # parent Position, so a stop set on one row appeared on every other row
    # of the same instrument and closed all of them together — "ek me SL
    # lagaya hai, dono me lag raha hai."
    #
    # A position and its fills must never both carry a leg, or the enforcer
    # fires twice for one intention. Setting a leg from the Active tab moves
    # the position's leg onto the fills and clears it; setting one from the
    # Position tab clears the fills'. Whichever view the user last spoke
    # through is the one that holds the bracket.
    stop_loss: Money | None = None
    target: Money | None = None

    #: Day high/low at the moment this fill's leg was last set — the same
    #: watermark `Position.bracket_ref_high/low` holds, and for the same
    #: reason: the enforcer's range check may only fire on an extreme made
    #: SINCE the leg was set, never on one the day had already printed.
    bracket_ref_high: Money | None = None
    bracket_ref_low: Money | None = None

    executed_at: datetime = Field(default_factory=now_utc)

    class Settings:
        name = "trades"
        indexes = [
            IndexModel([("trade_number", ASCENDING)], unique=True),
            IndexModel([("user_id", ASCENDING), ("executed_at", DESCENDING)]),
            IndexModel([("order_id", ASCENDING)]),
            IndexModel([("instrument.token", ASCENDING), ("executed_at", DESCENDING)]),
            IndexModel([("executed_at", DESCENDING)]),
        ]
