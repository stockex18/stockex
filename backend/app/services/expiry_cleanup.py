"""Daily instrument-expiry cleanup.

Background loop that runs every hour and applies the same rule the user
asked for:

    Expiry day  → instrument still shows / trades normally
    Day after   → instrument is removed from every user's watchlist,
                  unsubscribed from Zerodha, and marked inactive in the
                  Instrument collection so search stops returning it.

Idempotent — running twice in a row is a no-op once everything has been
swept. The loop exists so admins don't have to remember to nuke yesterday's
expired option chain manually.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from app.models.instrument import Instrument
from app.models.watchlist import WatchlistItem

logger = logging.getLogger(__name__)

IST = timezone(timedelta(hours=5, minutes=30))

_running = False


def _ist_today_date():
    """Indian trading-day boundary. We compare against IST midnight, not
    UTC, so a contract expiring on Thursday 'survives' through to Friday
    morning 00:00 IST regardless of the host machine's timezone."""
    return datetime.now(IST).date()


async def cleanup_expired_once() -> dict[str, int]:
    """Single sweep. Returns counts so the caller can log what changed.

    Strategy:
      • cutoff_date = today_IST - 1 day. Anything with `expiry < today_IST`
        is "yesterday or earlier" → cleanup target.
      • For each expired Instrument:
          - delete every WatchlistItem that references its token (across all
            users — there's no per-user opt-out for an expired contract)
          - unsubscribe the token from the Zerodha live ticker (skipped for
            non-Kite tokens)
          - mark the Instrument is_active=False so /instruments/search stops
            returning it. We DON'T hard-delete — historical orders / trades
            still reference these tokens.
    """
    today = _ist_today_date()
    from app.utils.time_utils import market_close_time_for_segment

    # Past-expiry contracts: always a cleanup target. Contracts expiring TODAY:
    # settle them once their SEGMENT's market-close time has passed, so an
    # expiring position auto-closes on its expiry DAY at close ("expiry" reason)
    # instead of surviving to the next morning (the reported MCX bug).
    now_t = datetime.now(IST).time()
    candidates = await Instrument.find(
        {"expiry": {"$ne": None, "$lte": today}, "is_active": True}
    ).to_list()

    # SETTLING and RETIRING are two different moments, and conflating them is
    # what made an expiring contract disappear off the screen mid-afternoon.
    #
    #   settle   at the segment's close on expiry day. The position must not
    #            survive the night, and its margin has to come back before the
    #            carry sweep decides what else can be carried.
    #
    #   retire   only once the day is OVER (expiry < today). Operator: "if kisi
    #            stock ki expiry aaj hai to wo raat 12 baje tak watchlist aur
    #            search me add rahe, taki user uski price dekh paye."
    #
    # So a contract expiring today settles at close and stays visible, priced
    # and searchable until midnight; tomorrow's sweep takes it off the screen.
    to_settle = []
    to_retire = []
    for _i in candidates:
        _exp = _i.expiry.date() if isinstance(_i.expiry, datetime) else _i.expiry
        if _exp < today:
            to_settle.append(_i)
            to_retire.append(_i)
        else:  # expires TODAY — settle after this segment's close, retire at midnight
            _ct = market_close_time_for_segment(getattr(_i, "segment", None))
            if _ct is not None and now_t >= _ct:
                to_settle.append(_i)
    expired = to_settle
    if not to_settle and not to_retire:
        return {
            "instruments": 0,
            "watchlist_items": 0,
            "unsubscribed": 0,
            "positions_settled": 0,
            "orders_cancelled": 0,
        }

    expired_tokens = [str(i.token) for i in expired]

    # 0) Settle any OPEN positions in these expired contracts FIRST — before
    #    we unsubscribe their tokens below. An expired contract no longer
    #    trades; once its token is unsubscribed the risk-enforcer can never
    #    price it, so it silently skips SL/TP/stop-out and the position would
    #    sit OPEN forever holding the user's margin (the risk_ltp_fetch_failed
    #    "zombie position" flood). settle_expired_position books realized P&L
    #    at the last-known price, releases the margin and flips the row CLOSED.
    #    Settling here (token still subscribed on the first sweep) gives the
    #    best chance of a fresh live price; it falls back to the position's
    #    frozen `ltp` otherwise.
    settled = 0
    from app.models.position import Position, PositionStatus
    from app.services import position_service

    open_in_expired = await Position.find(
        {
            "status": PositionStatus.OPEN.value,
            "instrument.token": {"$in": expired_tokens},
        }
    ).to_list()
    for _pos in open_in_expired:
        try:
            if await position_service.settle_expired_position(_pos) == "settled":
                settled += 1
        except Exception:  # noqa: BLE001
            logger.exception(
                "expiry_cleanup_settle_failed", extra={"position_id": str(_pos.id)}
            )

    # 0b) Cancel any still-parked orders (PENDING / OPEN / PARTIAL) on the
    #     expired contracts. Once the token is unsubscribed below the pending-
    #     order poller can never price them, so they'd sit OPEN forever holding
    #     the user's blocked margin (a "zombie order", mirror of the zombie
    #     position above). cancel_order flips them CANCELLED and RELEASES that
    #     blocked margin. Do this BEFORE unsubscribe, same as position settle.
    orders_cancelled = 0
    from app.models.order import Order, OrderStatus
    from app.services import matching_engine

    parked_orders = await Order.find(
        {
            "status": {
                "$in": [
                    OrderStatus.PENDING.value,
                    OrderStatus.OPEN.value,
                    OrderStatus.PARTIAL.value,
                ]
            },
            "instrument.token": {"$in": expired_tokens},
        }
    ).to_list()
    for _o in parked_orders:
        try:
            await matching_engine.cancel_order(_o, reason="EXPIRY_CANCELLED")
            orders_cancelled += 1
        except Exception:  # noqa: BLE001
            logger.exception(
                "expiry_cleanup_cancel_order_failed", extra={"order_id": str(_o.id)}
            )

    # ── Retirement: only for contracts whose DAY is over ──────────────
    # A contract that expired TODAY has already been settled above but is left
    # on watchlists, on the ticker and in search until midnight so the user can
    # still see what it went out at.
    retire_tokens = [str(i.token) for i in to_retire]

    # 1) Yank from every user's watchlist
    wl_removed = 0
    if retire_tokens:
        wl_result = await WatchlistItem.find(
            {"instrument_token": {"$in": retire_tokens}}
        ).delete()
        wl_removed = getattr(wl_result, "deleted_count", 0) or 0

    # 2) Unsubscribe from Zerodha — only for numeric Kite tokens
    int_tokens: list[int] = []
    for t in retire_tokens:
        try:
            int_tokens.append(int(t))
        except (TypeError, ValueError):
            pass
    unsubbed = 0
    if int_tokens:
        try:
            from app.services.zerodha_service import zerodha
            unsubbed = await zerodha.unsubscribe_tokens_on_demand(int_tokens)
        except Exception:
            logger.exception("expiry_cleanup_zerodha_unsubscribe_failed")

    # 3) Mark inactive so search stops returning them
    for inst in to_retire:
        try:
            inst.is_active = False
            inst.is_tradable = False
            await inst.save()
        except Exception:
            logger.exception(
                "expiry_cleanup_instrument_save_failed", extra={"token": inst.token}
            )

    logger.info(
        "expiry_cleanup_swept",
        extra={
            "instruments": len(to_retire),
            "settled_today": len(to_settle) - len(to_retire),
            "watchlist_items_removed": wl_removed,
            "tokens_unsubscribed": unsubbed,
            "positions_settled": settled,
            "orders_cancelled": orders_cancelled,
            "cutoff_date": str(today),
        },
    )
    return {
        "instruments": len(to_retire),
        "watchlist_items": wl_removed,
        "unsubscribed": unsubbed,
        "positions_settled": settled,
        "orders_cancelled": orders_cancelled,
    }


# Binance crypto options settle at 08:00 UTC on their expiry date.
_BINANCE_OPT_EXPIRY_UTC_HOUR = 8


async def settle_expired_crypto_options() -> dict:
    """Settle open CRYPTO OPTION positions at their true INTRINSIC value once the
    contract has expired (past 08:00 UTC on its expiry date).

      • CALL  → intrinsic = max(0, spot − strike)
      • PUT   → intrinsic = max(0, strike − spot)
      • spot  = live BTC index (the option's underlying)

    Unlike the generic IST-midnight cleanup (which force-closes at the last MARK
    price ~10.5 h late — over-crediting an out-of-the-money option), this settles
    ON TIME and at the correct intrinsic: an OTM option books at 0 (buyer loses
    the full premium), an ITM option at its exercise value. Leader-only, run each
    cleanup tick. Skips (retries next tick) when the BTC spot isn't available.
    """
    from datetime import datetime, time as _dtime, timezone

    from app.models.position import Position, PositionStatus
    from app.services import market_data_service, position_service
    from app.utils.decimal_utils import ZERO, to_decimal

    now = datetime.now(timezone.utc)
    try:
        positions = await Position.find(
            {
                "status": PositionStatus.OPEN.value,
                "segment_type": {"$regex": "^CRYPTO_OPTION"},
            }
        ).to_list()
    except Exception:
        logger.exception("crypto_opt_settle_query_failed")
        return {"settled": 0}

    settled = 0
    for pos in positions:
        try:
            inst = pos.instrument
            exp = getattr(inst, "expiry", None)
            if exp is None:
                continue
            exp_date = exp.date() if hasattr(exp, "date") else exp
            exp_dt = datetime.combine(
                exp_date, _dtime(_BINANCE_OPT_EXPIRY_UTC_HOUR, 0), tzinfo=timezone.utc
            )
            if now < exp_dt:
                continue  # not expired yet
            try:
                spot = to_decimal(
                    await market_data_service.get_ltp(inst.underlying_token or "CRYPTO_BTCUSD")
                )
            except Exception:
                spot = ZERO
            if spot <= ZERO:
                continue  # no spot yet — retry next sweep
            strike = to_decimal(inst.strike)
            opt_type = str(getattr(inst.option_type, "value", inst.option_type) or "").upper()
            intrinsic = max(ZERO, spot - strike) if opt_type in ("CE", "C", "CALL") else max(ZERO, strike - spot)
            res = await position_service.settle_expired_position(
                pos, settlement_price=intrinsic, allow_zero=True, reason="CRYPTO_OPT_EXPIRY"
            )
            if res == "settled":
                settled += 1
                logger.info(
                    "crypto_opt_settled token=%s intrinsic=%s spot=%s strike=%s type=%s",
                    inst.token, intrinsic, spot, strike, opt_type,
                )
        except Exception:
            logger.exception("crypto_opt_settle_failed pos=%s", getattr(pos, "id", None))
    if settled:
        logger.info("crypto_opt_settlement_swept settled=%s", settled)
    return {"settled": settled}


async def expiry_cleanup_loop(interval_sec: float = 3600.0) -> None:
    """Hourly sweep. An hourly cadence is enough because expiry happens at
    instrument granularity (date), not minute — but it's frequent enough
    that users never see day-old contracts after the boundary. Idempotent
    — second call returns immediately."""
    global _running
    if _running:
        return
    _running = True
    logger.info("expiry_cleanup_loop_started", extra={"interval_sec": interval_sec})
    try:
        # First sweep happens immediately on boot — picks up anything that
        # expired while the server was down.
        try:
            await cleanup_expired_once()
            await settle_expired_crypto_options()
        except Exception:
            logger.exception("expiry_cleanup_initial_sweep_failed")
        while _running:
            await asyncio.sleep(interval_sec)
            try:
                await cleanup_expired_once()
                await settle_expired_crypto_options()
            except Exception:
                logger.exception("expiry_cleanup_tick_failed")
    finally:
        _running = False
        logger.info("expiry_cleanup_loop_stopped")


def stop_expiry_cleanup() -> None:
    global _running
    _running = False
