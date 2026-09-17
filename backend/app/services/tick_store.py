"""Every tick, stored, for two days.

The platform reads prices out of what the feed already wrote — never out of a
fresh call to Kite. `mdlive` holds thirty seconds of that and `tick_snapshots`
holds a per-minute summary for a month, but neither can answer "what exactly
did this contract print at 11:42:07". This can, for as long as anyone is
realistically going to ask.

Shape, and why:

  * ONE COLLECTION PER DAY (`ticks_2026_09_03`). Retention is then a `drop()`,
    which is instant no matter how many rows are in it. A `deleteMany` over a
    few million documents takes minutes of disk on a two-core box, and if it
    ever ran during market hours it would take the feed down with it.

  * TWO DAYS. A dispute is raised the morning after, not the same evening — a
    single day's retention would have thrown the answer away before the
    question arrived.

  * BUFFERED, NEVER PER-TICK. `record()` is a list append and nothing else, so
    the tick loop never waits on Mongo; a separate loop writes the buffer once
    a second in one bulk insert. Unbuffered this would be a few hundred
    inserts a second competing with the feed for the same two cores.

  * RAW MOTOR, NOT BEANIE. Building a Document per row costs more than the
    write does at this volume, and there is no behaviour on these rows worth
    modelling — they are read back by one admin query.

ponytail: sampled at the tick loop's 1 s cadence, which is where the feed is
already overlaid (admin spread applied) and is what the user actually saw.
Kite's full mode publishes at roughly that rate anyway — measured 0.67
ticks/sec/token in production. If sub-second granularity is ever genuinely
needed, hook `zerodha_service._handle_parsed_ticks` instead and keep this
buffer/flush as-is.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

logger = logging.getLogger(__name__)

#: Collections are named for the IST trading day they belong to, because that
#: is the day a dispute is phrased in. A UTC-named collection would split one
#: session across two names for everything after 05:30 IST.
_PREFIX = "ticks_"

#: Today plus yesterday. Anything older is dropped whole.
RETENTION_DAYS = 2

#: Rows waiting for the next flush. Leader-process memory only.
_buffer: list[dict[str, Any]] = []

#: A pathological buffer means the flush loop has stopped while the tick loop
#: kept running. Dropping the oldest rows is better than growing until the
#: worker is killed and the feed with it.
_MAX_BUFFER = 200_000

_indexed: set[str] = set()

#: token -> the epoch SECOND already stored for it. The feed pump runs about
#: four times a second, so without this every instrument wrote ~4 rows per
#: second: 111 million rows and 7.9 GB on 16 Sep, and MongoDB taking 3,393
#: inserts a second on a two-core box while user queries ran at 50. One row a
#: second still answers "what did this print at 11:42:07", which is the only
#: question this archive exists for.
_last_second: dict[str, int] = {}

#: The map only ever holds the live token set (~900). This cap is for the case
#: where instruments churn all day — clearing costs one skipped dedupe pass.
_MAX_SECOND_KEYS = 20_000


def _ist_day(now: datetime | None = None) -> str:
    ist = (now or datetime.now(timezone.utc)) + timedelta(hours=5, minutes=30)
    return ist.strftime("%Y_%m_%d")


def collection_name(now: datetime | None = None) -> str:
    return _PREFIX + _ist_day(now)


def record(items: list[tuple[str, dict[str, Any]]], now_ms: int) -> None:
    """Buffer one pass of live quotes. Synchronous, allocation-light, and it
    never raises — the tick loop must not care that this exists."""
    if not items:
        return
    ts = datetime.fromtimestamp(now_ms / 1000, tz=timezone.utc)
    second = now_ms // 1000
    if len(_last_second) > _MAX_SECOND_KEYS:
        _last_second.clear()
    for token, q in items:
        try:
            tok = str(token)
            # One row per instrument per second. The pump passes each token
            # several times a second and the extra rows say the same thing.
            if _last_second.get(tok) == second:
                continue
            ltp = float(q.get("ltp") or 0)
            if ltp <= 0:
                # No live price for this token this pass. A zero row would read
                # back as a real print of zero, which is worse than a gap.
                continue
            _last_second[tok] = second
            _buffer.append(
                {
                    "token": tok,
                    "ts": ts,
                    # The EXCHANGE's own clock where there is one. `ts` is when
                    # we saw it; this is when it happened, and it is the column
                    # that settles an argument about a fill.
                    "ets": q.get("exchange_timestamp"),
                    "ltp": ltp,
                    "bid": float(q.get("bid") or 0),
                    "ask": float(q.get("ask") or 0),
                    # The whole O/H/L/C strip the user reads on screen, stored
                    # beside the price it belonged to. Without `open` and
                    # `close` the row could show what the price was but not
                    # what the day looked like around it — and the day's range
                    # is what the order gates decide on.
                    "open": float(q.get("open") or 0),
                    "high": float(q.get("high") or 0),
                    "low": float(q.get("low") or 0),
                    # Kite's `ohlc.close` is the PREVIOUS session's close, and
                    # it is what every change% on the platform is measured
                    # from. Named as it arrives so nobody reads it as today's.
                    "prev_close": float(q.get("prev_close") or 0),
                    "volume": float(q.get("volume") or 0),
                }
            )
        except (TypeError, ValueError):
            continue

    if len(_buffer) > _MAX_BUFFER:
        dropped = len(_buffer) - _MAX_BUFFER
        del _buffer[:dropped]
        logger.warning("tick_store_buffer_overflow", extra={"dropped": dropped})


async def _ensure_index(db, name: str) -> None:
    """One compound index per day's collection, created on first write.

    `(token, ts)` is the only way these are ever read — one instrument over one
    window. Creating it up front on an empty collection costs nothing; adding
    it later to a few million rows would not.
    """
    if name in _indexed:
        return
    try:
        await db[name].create_index([("token", 1), ("ts", 1)], background=True)
        _indexed.add(name)
    except Exception:  # noqa: BLE001 — an index failure must not stop the write
        logger.debug("tick_store_index_failed", extra={"collection": name}, exc_info=True)


async def flush_once() -> int:
    """Write the buffer and clear it. Returns rows written.

    The buffer is detached BEFORE the await so ticks arriving mid-write land in
    the next batch instead of being lost with the old list.
    """
    if not _buffer:
        return 0
    batch = _buffer[:]
    del _buffer[: len(batch)]

    from app.core.database import get_db

    db = get_db()
    name = collection_name()
    await _ensure_index(db, name)
    try:
        # ordered=False so one rejected row cannot discard the rest of the batch.
        await db[name].insert_many(batch, ordered=False)
        return len(batch)
    except Exception:  # noqa: BLE001
        logger.warning(
            "tick_store_flush_failed", extra={"rows": len(batch)}, exc_info=True
        )
        return 0


async def drop_old_collections(keep_days: int = RETENTION_DAYS) -> list[str]:
    """Drop every day-collection older than the retention window.

    Safe to call at any time: it only ever drops names strictly older than the
    keep set, so today's and yesterday's are never touched however often this
    runs.
    """
    from app.core.database import get_db

    db = get_db()
    now = datetime.now(timezone.utc)
    keep = {collection_name(now - timedelta(days=d)) for d in range(keep_days)}
    dropped: list[str] = []
    try:
        for name in await db.list_collection_names():
            if not name.startswith(_PREFIX) or name in keep:
                continue
            await db[name].drop()
            _indexed.discard(name)
            dropped.append(name)
    except Exception:  # noqa: BLE001
        logger.warning("tick_store_drop_failed", exc_info=True)
    if dropped:
        logger.info("tick_store_dropped", extra={"collections": dropped})
    return dropped


async def tick_store_flush_loop(interval_sec: float = 1.0) -> None:
    """LEADER-ONLY: write the buffer once a second, and sweep old days once an
    hour. The sweep rides this loop rather than a clock job because a dropped
    collection is idempotent — running it sixteen times a day costs nothing and
    means a missed window is never a missed drop."""
    logger.info("tick_store_flush_loop_started interval_sec=%s", interval_sec)
    since_sweep = 0.0
    try:
        while True:
            try:
                await flush_once()
                since_sweep += interval_sec
                if since_sweep >= 3600:
                    since_sweep = 0.0
                    await drop_old_collections()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                logger.warning("tick_store_flush_iter_failed", exc_info=True)
            await asyncio.sleep(interval_sec)
    finally:
        logger.info("tick_store_flush_loop_stopped")


def stop_tick_store() -> None:
    """Drop the unwritten buffer on shutdown / leadership loss. At most one
    second of ticks, and the alternative is a second process writing rows the
    new leader is also writing."""
    _buffer.clear()
