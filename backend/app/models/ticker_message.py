"""Scrolling announcement lines for the user home page.

Written and targeted by the SUPER ADMIN only. Each line either runs for every
admin's users (`target_all`) or for a chosen set of admins (`admin_ids`), so a
message meant for one pool never appears in another's.

Targeting is by ADMIN, not by user: the super admin picks admins, and a user
sees a line when one of the admins above them in the assignment chain is in
that set. Same chain `support.py` walks for the WhatsApp number.
"""

from __future__ import annotations

from beanie import PydanticObjectId
from pydantic import Field
from pymongo import ASCENDING, IndexModel

from app.models._base import TimestampMixin
from app.models.platform_setting import PlatformSetting


class TickerMessage(TimestampMixin):
    text: str

    #: Off keeps the row for reuse without showing it. Deleting is for lines
    #: that will never run again.
    enabled: bool = True

    #: Every admin's users. When true, `admin_ids` is ignored entirely - the
    #: two are not combined, so "all" cannot be silently narrowed by a stale
    #: selection left behind from before.
    target_all: bool = True

    #: The admins this line runs for when `target_all` is false. Empty with
    #: `target_all` false means it reaches nobody, which is a valid draft
    #: state - the admin UI says so rather than pretending it is live.
    admin_ids: list[PydanticObjectId] = Field(default_factory=list)

    #: Display order, ascending. Ties fall back to creation time.
    sort_order: int = 0

    class Settings:
        name = "ticker_messages"
        indexes = [
            # The user read is "enabled lines, in order" - everything else is
            # filtered in memory, because there are only ever a handful.
            IndexModel([("enabled", ASCENDING), ("sort_order", ASCENDING)]),
        ]


#: PlatformSetting key holding the strip's colours: `{"bg": ..., "text": ...}`.
#: One pair for the whole strip, not per line - the lines scroll as a single
#: band, so per-line colours would only produce a striped bar.
#: Added as per client requirement.
TICKER_STYLE_KEY = "ticker.style"


async def get_ticker_style() -> dict:
    """The saved colours, `None` for each one never set.

    `None` means "use the built-in look" (berry -> violet gradient, white
    text), so the user app falls back on its own rather than the backend
    having to know what the default looks like.
    """
    row = await PlatformSetting.find_one(PlatformSetting.setting_key == TICKER_STYLE_KEY)
    v = getattr(row, "setting_value", None)
    v = v if isinstance(v, dict) else {}
    return {"bg": v.get("bg") or None, "text": v.get("text") or None}
