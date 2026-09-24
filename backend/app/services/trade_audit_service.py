"""Check executed trades against the exchange, and against our own quotes.

The operator's question, in their words: "us time per exchange me jo rate chal
raha tha usi rate se match ho raha hai ya nahi." Answering it needs two
separate questions, because a fill can go wrong in two unrelated ways, and
running them together is what makes a checker cry wolf.

  1. WAS OUR FEED RIGHT?  Compare the prices our own feed printed that minute
     against the exchange's own one-minute candle. If our LTP wandered outside
     what the exchange actually traded, the feed was wrong and every fill in
     that minute is suspect -- this is the only case the exchange can settle.

  2. WAS THE FILL ON OUR OWN QUOTE?  Compare the fill against the bid and ask
     WE were showing in that same minute. A buy fills at the ask, a sell at
     the bid; a fill outside the band we ourselves published is a mispriced
     fill no matter what the exchange did.

Keeping them apart matters. A candle's high and low are TRADED prices, so an
ask always sits above the high and a bid below the low -- by the spread. Judge
a market buy against the candle alone and every single one reads "above high",
which is not a finding, it is arithmetic. Seen live on OFSS26SEPFUT, 24 Sept
10:33: exchange candle 10849-10863, our own feed for that minute 10849-10863
to the rupee, ask 10855-10873, and the buy filled at 10869 -- on our ask,
exactly as a market buy should. Correct trade, and the first cut of this tool
called it wrong.

WHY IT IS CHEAP
---------------
  * One upstream request per TOKEN per DAY, not one per trade or per minute.
    Kite returns the whole day in one response, so 500 trades across 20
    instruments cost 20 requests.
  * Those candles are cached in Redis under the (token, day) they cover. A
    minute that has closed can never change, so re-running the same window --
    or an overlapping one -- costs nothing.
  * Our own side comes from `tick_snapshots`, which the aggregator already
    writes per minute, read in one batched query. No tick replay.

Nothing here writes. It reads trades, reads candles, reads snapshots, and
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

from app.models.tick_snapshot import TickSnapshot
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

#: A price exactly ON a boundary is correct, and decimal arithmetic on figures
#: that arrived as strings should not turn that into a breach. Two paise is
#: below one tick on every instrument we carry.
_EPSILON = Decimal("0.02")

#: Snapshots are only kept for 30 days (TTL on `tick_snapshots`). Past that we
#: have no record of what we were quoting, and guessing is worse than saying so.
_SNAPSHOT_RETENTION_DAYS = 30

#: Mongo dislikes unbounded `$or`s, and the trade limit allows a few thousand.
_SNAPSHOT_CHUNK = 500


def _ist_minute(dt: datetime) -> datetime:
    """The IST minute a timestamp belongs to -- how candles are keyed."""
    d = dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    return d.astimezone(IST).replace(second=0, microsecond=0)


def _utc_minute(dt: datetime) -> datetime:
    """The naive-UTC minute -- how `tick_snapshots` are keyed."""
    d = dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    return d.astimezone(timezone.utc).replace(second=0, microsecond=0, tzinfo=None)


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
    except Exception:  # noqa: BLE001 -- a cold cache is not an error
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
        except Exception as e:  # noqa: BLE001 -- one dead token must not sink the run
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


def _neighbourhood(
    day_candles: dict[str, dict], when: datetime
) -> tuple[Decimal, Decimal] | None:
    """The traded range over the fill's minute and the one either side.

    Our sampler reads the feed about once a second and bins by our own clock,
    so a print the exchange filed under 10:33 can land in our 10:34. Widening
    the reference by one minute each way removes that boundary artefact
    without inventing a fudge tolerance -- and the candles are already in
    memory, so it costs nothing.
    """
    lows: list[Decimal] = []
    highs: list[Decimal] = []
    for delta in (-1, 0, 1):
        c = day_candles.get((when + timedelta(minutes=delta)).strftime("%H:%M"))
        if c:
            lows.append(to_decimal(c["l"]))
            highs.append(to_decimal(c["h"]))
    if not lows:
        return None
    return min(lows), max(highs)


async def _our_quotes(
    pairs: set[tuple[str, datetime]],
) -> dict[tuple[str, datetime], TickSnapshot]:
    """What WE were quoting, for exactly the minutes we need."""
    if not pairs:
        return {}
    wanted = sorted(pairs)
    out: dict[tuple[str, datetime], TickSnapshot] = {}
    for i in range(0, len(wanted), _SNAPSHOT_CHUNK):
        clauses = [
            {"token": tok, "timestamp": ts}
            for tok, ts in wanted[i : i + _SNAPSHOT_CHUNK]
        ]
        try:
            for s in await TickSnapshot.find({"$or": clauses}).to_list():
                out[(s.token, _utc_minute(s.timestamp))] = s
        except Exception:  # noqa: BLE001 -- no snapshot just means we cannot judge
            logger.warning("trade_audit_snapshot_read_failed", exc_info=True)
    return out


def _fill_band(snap: TickSnapshot) -> tuple[Decimal, Decimal]:
    """The widest price we ourselves published in that minute: our bid low to
    our ask high. A buy belongs near the top of it and a sell near the bottom,
    but anything inside it is a price we were genuinely showing.
    """
    lo = [to_decimal(v) for v in (snap.bid_low, snap.ask_low, snap.low) if _f(v) > 0]
    hi = [to_decimal(v) for v in (snap.bid_high, snap.ask_high, snap.high) if _f(v) > 0]
    return (min(lo) if lo else Decimal("0")), (max(hi) if hi else Decimal("0"))


async def audit(
    *,
    start: datetime,
    end: datetime,
    user_id: str | None = None,
    limit: int = 2000,
) -> dict[str, Any]:
    """Verify every fill in a window -- our feed against the exchange, and the
    fill against our own quote. One row per trade, plus a summary.
    """
    q: dict[str, Any] = {"executed_at": {"$gte": start, "$lte": end}}
    if user_id:
        try:
            q["user_id"] = PydanticObjectId(str(user_id))
        except Exception:  # noqa: BLE001 -- a malformed id narrows to nothing
            return {"summary": _summary([], 0), "rows": [], "skipped": []}

    trades = await Trade.find(q).sort("-executed_at").limit(int(limit)).to_list()
    if not trades:
        return {"summary": _summary([], 0), "rows": [], "skipped": []}

    # Which instrument-days do we need? This is the whole reason the tool is
    # cheap: a day's candles answer every trade on that instrument.
    needed: set[tuple[str, date]] = set()
    snap_pairs: set[tuple[str, datetime]] = set()
    for t in trades:
        tok = str(getattr(t.instrument, "token", "") or "")
        if not tok:
            continue
        needed.add((tok, _ist_minute(t.executed_at).date()))
        snap_pairs.add((tok, _utc_minute(t.executed_at)))

    sem = asyncio.Semaphore(_MAX_PARALLEL_FETCHES)
    fetched, snaps, user_rows = await asyncio.gather(
        asyncio.gather(
            *(_candles_for_token(tok, day, sem) for tok, day in sorted(needed)),
            return_exceptions=True,
        ),
        _our_quotes(snap_pairs),
        User.find({"_id": {"$in": list({t.user_id for t in trades})}}).to_list(),
    )
    candles: dict[tuple[str, date], dict] = {
        key: (res if isinstance(res, dict) else {})
        for key, res in zip(sorted(needed), fetched)
    }
    users = {u.id: u.user_code for u in user_rows}
    snapshot_cutoff = datetime.utcnow() - timedelta(days=_SNAPSHOT_RETENTION_DAYS)

    rows: list[dict] = []
    skipped: list[dict] = []
    for t in trades:
        tok = str(getattr(t.instrument, "token", "") or "")
        when = _ist_minute(t.executed_at)
        day_candles = candles.get((tok, when.date())) or {}
        candle = day_candles.get(when.strftime("%H:%M"))
        snap = snaps.get((tok, _utc_minute(t.executed_at)))
        price = to_decimal(t.price)

        base = {
            "trade_id": str(t.id),
            "trade_number": t.trade_number,
            "user_code": users.get(t.user_id, "-"),
            "symbol": getattr(t.instrument, "symbol", "-"),
            "exchange": str(getattr(t.instrument, "exchange", "") or ""),
            "action": str(getattr(t.action, "value", t.action) or "").upper(),
            "quantity": _f(t.quantity),
            "price": float(price),
            "executed_at": t.executed_at,
            "minute": when.strftime("%d/%m %H:%M"),
        }

        if not candle and not snap:
            # Neither reference exists. An instrument the exchange serves no
            # history for -- crypto, forex -- with no snapshot either cannot be
            # judged, and saying "wrong" about it is worse than saying nothing.
            skipped.append({
                **base,
                "reason": (
                    "older than our 30-day quote record, and no exchange candle"
                    if t.executed_at < snapshot_cutoff
                    else "no exchange candle and no quote record for this minute"
                ),
            })
            continue

        row: dict[str, Any] = {**base, "verdict": "OK", "off_by": 0.0, "reason": ""}

        # ---- 1. our feed against the exchange --------------------------
        if candle:
            row["exchange_low"] = candle["l"]
            row["exchange_high"] = candle["h"]
        if candle and snap and _f(snap.high) > 0:
            band = _neighbourhood(day_candles, when)
            if band:
                ex_low, ex_high = band
                our_low, our_high = to_decimal(snap.low), to_decimal(snap.high)
                drift = max(our_high - ex_high, ex_low - our_low, Decimal("0"))
                row["our_low"] = _f(snap.low)
                row["our_high"] = _f(snap.high)
                if drift > _EPSILON:
                    row["verdict"] = "FEED_OFF"
                    row["off_by"] = float(drift)
                    row["reason"] = (
                        f"our feed showed {_f(snap.low):g}-{_f(snap.high):g} "
                        f"while the exchange traded {float(ex_low):g}-{float(ex_high):g}"
                    )

        # ---- 2. the fill against the quote we published ----------------
        if snap:
            lo, hi = _fill_band(snap)
            row["our_bid"] = [_f(snap.bid_low), _f(snap.bid_high)]
            row["our_ask"] = [_f(snap.ask_low), _f(snap.ask_high)]
            if hi > 0:
                gap = max(price - hi, lo - price, Decimal("0"))
                if gap > _EPSILON and gap > to_decimal(row["off_by"]):
                    row["verdict"] = "FILL_OFF"
                    row["off_by"] = float(gap)
                    row["reason"] = (
                        f"filled at {float(price):g}, outside the "
                        f"{float(lo):g}-{float(hi):g} we were quoting that minute"
                    )
        elif row["verdict"] == "OK":
            # A candle but no quote record: we can see the exchange was fine,
            # but not what we showed, and the fill sits on a side the candle
            # cannot speak for. That is not a pass.
            skipped.append({**base, "reason": "no quote record for this minute"})
            continue

        row["off_pct"] = (
            float(to_decimal(row["off_by"]) / price * 100) if price else 0.0
        )
        rows.append(row)

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
        "feed_off": sum(1 for r in bad if r["verdict"] == "FEED_OFF"),
        "fill_off": sum(1 for r in bad if r["verdict"] == "FILL_OFF"),
        "not_checkable": skipped,
        "worst_off_by": max((abs(r["off_by"]) for r in bad), default=0.0),
    }
