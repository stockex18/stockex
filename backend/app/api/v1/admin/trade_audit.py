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


def _clock(s: str | None, *, end: bool) -> time:
    """An HH:MM from the picker, or the edge of the day when it is left blank.

    The operator asked to narrow a check to a stretch of the session -- "us
    time se check kar paye" -- so a blank stays the whole day and a time
    means exactly that minute, inclusive at both ends.
    """
    if not s:
        return time(23, 59, 59, 999999) if end else time(0, 0)
    try:
        h, m = (int(x) for x in str(s).split(":")[:2])
        return time(h, m, 59, 999999) if end else time(h, m)
    except Exception:
        raise ValidationFailedError(f"Could not read the time {s!r}") from None


def _bound(s: str | None, clock: str | None, *, end: bool) -> datetime | None:
    if not s:
        return None
    try:
        d = datetime.fromisoformat(s).date()
    except ValueError:
        raise ValidationFailedError(f"Could not read the date {s!r}") from None
    t = _clock(clock, end=end)
    return datetime.combine(d, t, tzinfo=IST).astimezone(timezone.utc).replace(tzinfo=None)


@router.get("", response_model=APIResponse[dict])
async def check_trades(
    admin: SuperAdmin,
    date_from: str | None = None,
    date_to: str | None = None,
    time_from: str | None = None,
    time_to: str | None = None,
    user_id: str | None = None,
    limit: int = Query(default=2000, ge=1, le=5000),
):
    """Verify every fill in a window against the exchange.

    Defaults to today, whole day, when nothing is given. `time_from` /
    `time_to` are HH:MM in IST and narrow the range to a stretch of the
    session. `user_id` narrows it to one client; `limit` caps how many fills
    are examined, newest first.
    """
    now_ist = datetime.now(IST)
    today = now_ist.date().isoformat()
    start = _bound(date_from or today, time_from, end=False)
    end = _bound(date_to or today, time_to, end=True)
    if start is None or end is None:
        raise ValidationFailedError("Pick a date range")
    if end < start:
        raise ValidationFailedError("The end of the range is before its start")
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
            "range": {
                "from": date_from or today,
                "to": date_to or today,
                "time_from": time_from,
                "time_to": time_to,
            },
            **out,
        }
    )
