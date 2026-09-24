"""Check Trades — verify fills against the exchange's own one-minute candles.

Super-admin only. It answers one question per fill: at the minute this traded,
did the exchange print a price that covers it? A fill outside that minute's
high-low never happened on the exchange, and the operator needs to see it, the
exact figures, and how far off it was.

Read-only by design. It reports; correcting a trade is a separate, deliberate
action on the trade itself.
"""

from __future__ import annotations

from datetime import datetime, time, timedelta, timezone

from fastapi import APIRouter, Query

from app.core.dependencies import SuperAdmin
from app.core.exceptions import ValidationFailedError
from app.schemas.common import APIResponse
from app.services import trade_audit_service

router = APIRouter(prefix="/check-trades", tags=["admin-trade-audit"])

IST = timezone(timedelta(hours=5, minutes=30))

#: A window is bounded because the cost is linear in instrument-days, and an
#: open-ended range on a busy book is how a "just checking" click turns into
#: hundreds of upstream requests.
_MAX_DAYS = 7


def _bound(s: str | None, *, end: bool) -> datetime | None:
    if not s:
        return None
    try:
        d = datetime.fromisoformat(s).date()
    except ValueError:
        raise ValidationFailedError(f"Could not read the date {s!r}") from None
    t = time(23, 59, 59, 999999) if end else time(0, 0)
    return datetime.combine(d, t, tzinfo=IST).astimezone(timezone.utc).replace(tzinfo=None)


@router.get("", response_model=APIResponse[dict])
async def check_trades(
    admin: SuperAdmin,
    date_from: str | None = None,
    date_to: str | None = None,
    user_id: str | None = None,
    limit: int = Query(default=2000, ge=1, le=5000),
):
    """Verify every fill in a window against the exchange.

    Defaults to today when no dates are given. `user_id` narrows it to one
    client; `limit` caps how many fills are examined, newest first.
    """
    now_ist = datetime.now(IST)
    start = _bound(date_from, end=False) or _bound(
        now_ist.date().isoformat(), end=False
    )
    end = _bound(date_to, end=True) or _bound(now_ist.date().isoformat(), end=True)
    if start is None or end is None:
        raise ValidationFailedError("Pick a date range")
    if end < start:
        raise ValidationFailedError("The end date is before the start date")
    if (end - start) > timedelta(days=_MAX_DAYS):
        raise ValidationFailedError(
            f"Check at most {_MAX_DAYS} days at a time — a wider window means "
            "hundreds of upstream requests for one click."
        )

    out = await trade_audit_service.audit(
        start=start, end=end, user_id=user_id, limit=limit
    )
    return APIResponse(
        data={
            "range": {"from": date_from or now_ist.date().isoformat(),
                      "to": date_to or now_ist.date().isoformat()},
            **out,
        }
    )
