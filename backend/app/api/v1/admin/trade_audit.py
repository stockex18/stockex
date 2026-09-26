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

#: Two days, and not a day older, because that is exactly how long the raw
#: tick store keeps what we were quoting (`tick_store.RETENTION_DAYS`). Inside
#: it every fill is judged against our quote at its own SECOND; outside it we
#: would be back to a whole minute's band, which is wide enough for a wrong
#: fill to hide in. Keeping the window and the evidence the same length means
#: every check the operator can run is the precise one — and it is what keeps
#: this page off the server's back (operator: "2 din ka hi max check kar paye
#: ... jisse server me load bhi na pade").
_MAX_DAYS = 2


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
            f"Check at most {_MAX_DAYS} days at a time — today and yesterday."
        )
    # The tick store keeps two days. Older than that and there is nothing left
    # to check a fill against second by second, so say so rather than quietly
    # answering a weaker question.
    oldest = _bound(
        (now_ist.date() - timedelta(days=_MAX_DAYS - 1)).isoformat(), None, end=False
    )
    if oldest is not None and start < oldest:
        raise ValidationFailedError(
            f"Only the last {_MAX_DAYS} days can be checked — today and "
            "yesterday. That is how long we keep every tick, and it is the "
            "tick that says what we were quoting at the second a fill happened."
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
