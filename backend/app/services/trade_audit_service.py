"""Check executed trades against the exchange's own one-minute candles.

The operator's question, in their words: "us time per exchange me jo rate chal
raha tha usi rate se match ho raha hai ya nahi — high aur low ke beech me wo
hai ya nahi." A fill at a price the exchange never printed in that minute is
either a stale feed or a mispriced fill, and it is the operator who has to
answer for it.

So the reference is Zerodha's historical candles, not our own tick store.
Checking our fills against our own recording only proves the recording is
self-consistent; it cannot see a minute where our feed was wrong, which is
the only interesting case.

WHY IT IS CHEAP
---------------
The naive shape — one lookup per trade — is what makes a tool like this
unusable on a busy day and hard on the box. Three things keep it small:

  • One request per TOKEN for the whole window, not one per trade and not
    one per minute. Kite returns every minute of the range in a single
    response, so 500 trades across 20 instruments cost 20 requests.
  • Those candles are cached in Redis under the exact (token, day) they
    cover. A minute that has closed can never change, so re-running the
    same window, or an overlapping one, costs nothing at all.
  • Trades are grouped by (token, minute) first, so repeated fills in the
    same minute — the common case when an order fills in pieces — are
    answered from one candle.

Kite rate-limits historical data, so the fetches run a few at a time rather
than all at once. Nothing here writes: it reads trades, reads candles, and
returns a verdict.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from beanie import PydanticObjectId

from app.models.trade import Trade
from app.models.user import User
from app.utils.decimal_utils import to_decimal

logger = logging.getLogger(__name__)

IST = timezone(timedelta(hours=5, minutes=30))

#: Kite's published ceiling is 3 requests/second for historical data. Three in
#: flight with a short spacing keeps us comfortably under it while still
#: turning a 20-instrument day around in a couple of seconds.
_MAX_PARALLEL_FETCHES = 3
_FETCH_SPACING_SEC = 0.34

#: A candle for a minute that has closed is final, so it can be cached for a
#: long time. Kept to a day so a re-run tomorrow still re-reads today's tail,
#: where the last candle may have been mid-formation when we first saw it.
_CACHE_TTL_SEC = 24 * 3600
_CACHE_KEY = "candles:{token}:{day}"

#: A fill exactly ON the high or low is correct, and floating-point arithmetic
#: on prices that arrived as strings should not turn that into a breach. Two
#: paise is below one tick on every instrument we carry.
_EPSILON = Decimal("0.02")


def _minute(dt: datetime) -> datetime:
    """The IST minute a timestamp belongs to, which is how candles are keyed."""
    d = dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    return d.astimezone(IST).replace(second=0, microsecond=0)


def _f(v: Any) -> float:
    try:
        return float(str(v))
    except Exception:  # noqa: BLE001
        return 0.0


async def _candles_for_token(
    token: str, day: date, sem: asyncio.Semaphore
) -> dict[str, dict]:
    """Every one-minute candle for one instrument on one day, keyed by HH:MM.

    Cached whole rather than per minute: one Redis round-trip answers a day,
    and the day is the unit Kite hands back anyway.
    """
    from app.core.redis_client import cache_get, cache_set

    key = _CACHE_KEY.format(token=token, day=day.isoformat())
    try:
        hit = await cache_get(key)
        if hit:
            return hit if isinstance(hit, dict) else json.loads(hit)
    except Exception:  # noqa: BLE001 — a cold cache is not an error
        pass

    from app.services import zerodha_service

    start = datetime.combine(day, datetime.min.time())
    end = start + timedelta(days=1)
    async with sem:
        await asyncio.sleep(_FETCH_SPACING_SEC)
        try:
            rows = await zerodha_service.zerodha.get_historical(
                int(token), start, end, "minute"
            )
        except Exception as e:  # noqa: BLE001 — one dead token must not sink the run
            logger.warning(
                "trade_audit_candles_failed",
                extra={"token": token, "day": day.isoformat(), "error": str(e)[:120]},
            )
            return {}

    out: dict[str, dict] = {}
    for c in rows or []:
        t = c.get("time") or c.get("date")
        if t is None:
            continue
        if isinstance(t, (int, float)):
            when = datetime.fromtimestamp(t, tz=timezone.utc).astimezone(IST)
        elif isinstance(t, datetime):
            when = t if t.tzinfo else t.replace(tzinfo=IST)
        else:
            continue
        out[when.astimezone(IST).strftime("%H:%M")] = {
            "o": _f(c.get("open")),
            "h": _f(c.get("high")),
            "l": _f(c.get("low")),
            "c": _f(c.get("close")),
            "v": _f(c.get("volume")),
        }

    if out:
        try:
            await cache_set(key, out, ttl_sec=_CACHE_TTL_SEC)
        except Exception:  # noqa: BLE001
            pass
    return out


async def audit(
    *,
    start: datetime,
    end: datetime,
    user_id: str | None = None,
    limit: int = 2000,
) -> dict[str, Any]:
    """Verify every fill in a window against the exchange's own candles.

    Returns one row per trade with a verdict, plus a summary. Reads only.
    """
    q: dict[str, Any] = {"executed_at": {"$gte": start, "$lte": end}}
    if user_id:
        try:
            q["user_id"] = PydanticObjectId(str(user_id))
        except Exception:  # noqa: BLE001 — a malformed id narrows to nothing
            return {"summary": _summary([], 0), "rows": [], "skipped": []}

    trades = (
        await Trade.find(q).sort("-executed_at").limit(int(limit)).to_list()
    )
    if not trades:
        return {"summary": _summary([], 0), "rows": [], "skipped": []}

    # Which instrument-days do we actually need? This is the whole reason the
    # tool is cheap: a day's candles answer every trade on that instrument.
    needed: set[tuple[str, date]] = set()
    for t in trades:
        tok = str(getattr(t.instrument, "token", "") or "")
        if tok:
            needed.add((tok, _minute(t.executed_at).date()))

    sem = asyncio.Semaphore(_MAX_PARALLEL_FETCHES)
    fetched = await asyncio.gather(
        *(_candles_for_token(tok, day, sem) for tok, day in sorted(needed)),
        return_exceptions=True,
    )
    candles: dict[tuple[str, date], dict] = {}
    for (tok, day), res in zip(sorted(needed), fetched):
        candles[(tok, day)] = res if isinstance(res, dict) else {}

    users: dict[Any, str] = {}
    for u in await User.find(
        {"_id": {"$in": list({t.user_id for t in trades})}}
    ).to_list():
        users[u.id] = u.user_code

    rows: list[dict] = []
    skipped: list[dict] = []
    for t in trades:
        tok = str(getattr(t.instrument, "token", "") or "")
        when = _minute(t.executed_at)
        candle = (candles.get((tok, when.date())) or {}).get(when.strftime("%H:%M"))
        price = to_decimal(t.price)

        base = {
            "trade_id": str(t.id),
            "trade_number": t.trade_number,
            "user_code": users.get(t.user_id, "—"),
            "symbol": getattr(t.instrument, "symbol", "—"),
            "exchange": str(getattr(t.instrument, "exchange", "") or ""),
            "action": str(getattr(t.action, "value", t.action) or ""),
            "quantity": _f(t.quantity),
            "price": float(price),
            "executed_at": t.executed_at,
            "minute": when.strftime("%d/%m %H:%M"),
        }

        if not candle:
            # No candle is not a verdict. An instrument the exchange does not
            # serve history for — crypto, forex — cannot be judged here, and
            # saying "wrong" about it would be worse than saying nothing.
            skipped.append({**base, "reason": "no exchange candle for this minute"})
            continue

        high = to_decimal(candle["h"])
        low = to_decimal(candle["l"])
        if price > high + _EPSILON:
            verdict, off = "ABOVE_HIGH", price - high
        elif price < low - _EPSILON:
            verdict, off = "BELOW_LOW", low - price
        else:
            verdict, off = "OK", Decimal("0")

        rows.append({
            **base,
            "verdict": verdict,
            "exchange_high": candle["h"],
            "exchange_low": candle["l"],
            "exchange_open": candle["o"],
            "exchange_close": candle["c"],
            "off_by": float(off),
            "off_pct": float(off / price * 100) if price else 0.0,
        })

    rows.sort(key=lambda r: (r["verdict"] == "OK", -abs(r["off_by"])))
    return {
        "summary": _summary(rows, len(skipped)),
        "rows": rows,
        "skipped": skipped[:200],
    }


def _summary(rows: list[dict], skipped: int) -> dict[str, Any]:
    bad = [r for r in rows if r["verdict"] != "OK"]
    return {
        "checked": len(rows),
        "ok": len(rows) - len(bad),
        "mismatched": len(bad),
        "above_high": sum(1 for r in bad if r["verdict"] == "ABOVE_HIGH"),
        "below_low": sum(1 for r in bad if r["verdict"] == "BELOW_LOW"),
        "not_checkable": skipped,
        "worst_off_by": max((abs(r["off_by"]) for r in bad), default=0.0),
    }
