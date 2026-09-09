"""Which announcement lines this user should see.

The super admin targets by ADMIN. A user therefore sees a line when one of the
admins ABOVE them is in that line's set - so the walk here has to collect every
admin-tier ancestor, not just the nearest one.

Same chain `support.py` walks for the WhatsApp number, and for the same reason:
`assigned_broker_id` / `assigned_admin_id` are what a CLIENT row actually
carries. `parent_id` is left out because most clients are created without one,
which would strand the walk at the first node and make every targeted line
invisible.
"""

from __future__ import annotations

from beanie import PydanticObjectId
from fastapi import APIRouter

from app.core.dependencies import CurrentUser
from app.models.ticker_message import TickerMessage
from app.models.user import User
from app.schemas.common import APIResponse

router = APIRouter(prefix="/ticker", tags=["user-ticker"])


async def _owning_admin_ids(user: User) -> set[PydanticObjectId]:
    """Every admin-tier account above this user, plus the user itself.

    Self is included so an admin logged into the user app sees the lines aimed
    at them. Capped at 8 hops against a corrupted chain, same as the support
    resolver.
    """
    out: set[PydanticObjectId] = set()
    cur: User | None = user
    hops = 0
    while cur is not None and hops < 8:
        if cur.id in out:
            break
        out.add(cur.id)
        nxt = cur.assigned_broker_id or cur.assigned_admin_id
        if nxt is None or nxt in out:
            break
        cur = await User.get(nxt)
        hops += 1
    return out


def _line_visible(m: TickerMessage, mine: set[PydanticObjectId]) -> bool:
    """Does this line run for a user whose admin chain is `mine`?

    `target_all` short-circuits and ignores `admin_ids` entirely - the two are
    never combined, so an "all" line cannot be silently narrowed by a stale
    selection left over from before it was switched to all.
    """
    if m.target_all:
        return True
    if not m.admin_ids:
        return False  # targeted at nobody yet - a draft, not a live line
    return any(a in mine for a in m.admin_ids)


@router.get("", response_model=APIResponse[dict])
async def my_ticker(user: CurrentUser):
    """The lines to scroll, in order. Empty list renders no strip at all."""
    rows = (
        await TickerMessage.find({"enabled": True})
        .sort("+sort_order", "+created_at")
        .to_list()
    )
    if not rows:
        return APIResponse(data={"messages": []})

    # Only walk the chain if something is actually targeted - an all-hands
    # line needs no lookup, which is the common case.
    needs_chain = any(m.target_all is False and m.admin_ids for m in rows)
    mine = await _owning_admin_ids(user) if needs_chain else set()

    return APIResponse(
        data={"messages": [m.text for m in rows if _line_visible(m, mine)]}
    )
