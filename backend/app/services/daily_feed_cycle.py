"""The one thing that happens every morning, on the clock.

Two jobs, both of which have to land before the first market opens:

  07:30 IST  rebuild — the expired contracts of yesterday stop being carried,
             and the option ladders are re-warmed around where the money
             actually is now.
  08:00 IST  sweep   — tick collections past the retention window are dropped.

DELIBERATELY ON THE CLOCK, NOT ON THE KITE TOKEN. The obvious hook is "when
the access token renews", and it is the wrong one: that token has failed to
renew 484 times in a row on this deployment, and on the days it does work it
has landed as late as 09:12 — three minutes before the open. Hanging the daily
reset off an event that unreliable means the reset either never happens or
happens mid-session. A clock always fires.

The windows are chosen against the earliest market: MCX opens 09:00, so 08:00
leaves an hour of slack even if a pass runs long.

FAILING SAFE. A rebuild that throws leaves yesterday's subscriptions exactly
where they are. That is the important property — an empty universe is not a
degraded platform, it is a stopped one, with every open position unpriced and
the risk enforcer blind.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, time, timedelta, timezone

logger = logging.getLogger(__name__)

IST = timezone(timedelta(hours=5, minutes=30))

REBUILD_AT = time(7, 30)
SWEEP_AT = time(8, 0)

#: How far past the mark a run still counts, so a slow tick or a restart inside
#: the window does not skip the day entirely.
_WINDOW_MIN = 20


def _now_ist() -> datetime:
    return datetime.now(IST)


def _in_window(now: datetime, at: time) -> bool:
    mark = now.replace(hour=at.hour, minute=at.minute, second=0, microsecond=0)
    return mark <= now < mark + timedelta(minutes=_WINDOW_MIN)


async def rebuild_once() -> dict[str, int]:
    """Re-warm the core option ladders and re-assert held positions.

    Both halves are idempotent and both already exist — this is the thing that
    makes them happen at a known time rather than whenever a user first looks.
    """
    out = {"core": 0, "positions": 0}
    try:
        from app.services.core_feed_warm import warm_core_feed_once

        out["core"] = await warm_core_feed_once()
    except Exception:  # noqa: BLE001
        logger.warning("daily_rebuild_core_failed", exc_info=True)
    try:
        from app.services.market_data_service import ensure_open_position_subscriptions

        res = await ensure_open_position_subscriptions()
        out["positions"] = int(res.get("positions", 0) or 0)
    except Exception:  # noqa: BLE001
        logger.warning("daily_rebuild_positions_failed", exc_info=True)
    logger.info("daily_feed_rebuild_done", extra=out)
    return out


async def sweep_once() -> list[str]:
    from app.services.tick_store import drop_old_collections

    return await drop_old_collections()


async def daily_feed_cycle_loop(interval_sec: float = 60.0) -> None:
    """LEADER-ONLY. Checks the clock every minute and runs each job at most
    once per IST day, so a restart inside a window cannot run it twice and a
    restart across one still catches it."""
    logger.info("daily_feed_cycle_loop_started")
    done_rebuild: str | None = None
    done_sweep: str | None = None
    try:
        while True:
            try:
                now = _now_ist()
                day = now.strftime("%Y-%m-%d")
                if done_rebuild != day and _in_window(now, REBUILD_AT):
                    done_rebuild = day
                    await rebuild_once()
                if done_sweep != day and _in_window(now, SWEEP_AT):
                    done_sweep = day
                    dropped = await sweep_once()
                    logger.info("daily_feed_sweep_done", extra={"dropped": dropped})
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 — never let a bad day stop the loop
                logger.warning("daily_feed_cycle_iter_failed", exc_info=True)
            await asyncio.sleep(interval_sec)
    finally:
        logger.info("daily_feed_cycle_loop_stopped")
