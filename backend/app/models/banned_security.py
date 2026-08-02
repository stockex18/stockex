"""Super-admin security ban.

One row per banned instrument × scope. When a security is banned:
  • no NEW / adding position can be opened in it (order_validator blocks it;
    closing / reducing stays allowed);
  • an existing open position's unrealized P&L FREEZES at `freeze_price` — the
    LTP captured at ban time — so it stops moving and the position can only be
    closed.

Scope:
  • scope == "GLOBAL"      → applies to every user.
  • scope == "<admin_id>"  → applies only to that admin's downline users
    (matched against the user's assigned_admin_id).

Super-admin only — created / removed from the SA "Ban Security" panel.
"""

from __future__ import annotations

from datetime import datetime

from beanie import Indexed, PydanticObjectId
from bson import Decimal128
from pymongo import ASCENDING, IndexModel

from app.models._base import TimestampMixin

GLOBAL_SCOPE = "GLOBAL"


class BannedSecurity(TimestampMixin):
    token: Indexed(str)  # type: ignore[valid-type]  # instrument token
    symbol: str
    scope: str = GLOBAL_SCOPE  # "GLOBAL" or an admin's id (str)
    freeze_price: Decimal128 = Decimal128("0")  # LTP snapshot at ban time
    banned_by: PydanticObjectId | None = None
    banned_at: datetime | None = None

    class Settings:
        name = "banned_securities"
        indexes = [
            IndexModel(
                [("token", ASCENDING), ("scope", ASCENDING)],
                unique=True,
                name="banned_security_unique_token_scope",
            ),
        ]
