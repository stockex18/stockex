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
from datetime import date, datetime, time, timedelta, timezone
from typing import Any

from app.models.instrument import Instrument
from app.models.watchlist import WatchlistItem

logger = logging.getLogger(__name__)

IST = timezone(timedelta(hours=5, minutes=30))

_running = False

#: A crypto option this long past its settle time is NOT auto-settled: the
#: intrinsic fallback would price it off today's spot, not its own expiry's.
_STALE_EXPIRY_HOURS = 24


def _ist_today_date():
    """Indian trading-day boundary. We compare against IST midnight, not
    UTC, so a contract expiring on Thursday 'survives' through to Friday
    morning 00:00 IST regardless of the host machine's timezone."""
    return datetime.now(IST).date()


async def _heal_missing_expiry() -> int:
    """Give a derivative back its expiry date, or retire it if it is gone.

    The sweep below only ever looks at rows with `{"expiry": {"$ne": None}}`.
    A future or option whose `expiry` is null is therefore invisible to it —
    immortal. It stays `is_tradable` for ever, keeps its watchlist rows, and
    goes on showing whatever price it last held.

    Found live on 23 Sept: CRUDEOIL26SEPFUT, expiry null, still tradable four
    days after the September contract died. Zerodha had already delisted it —
    its own catalogue starts at 26OCT — and what our mirror held was
    ltp = bid = ask = 9158.00 on zero volume, which is what a dead contract
    looks like. A user could have opened a position on it at that number.

    Two answers, and the upstream catalogue decides which:
      • still listed  → the date was simply never filled in; copy it across.
      • not listed    → the exchange has retired it, so retire it here, and
                        let the sweep that follows do the rest.

    Equities and indices are skipped — they have no expiry and never should.
    """
    from app.services import zerodha_service

    healed = retired = 0
    rows = await Instrument.find(
        {"expiry": None, "is_active": True,
         "segment": {"$regex": "FUT|OPT", "$options": "i"}}
    ).to_list()
    if not rows:
        return 0

    # One catalogue read per exchange, not per instrument.
    catalogue: dict[str, dict[str, Any]] = {}
    for exch in {str(getattr(i.exchange, "value", i.exchange) or "") for i in rows}:
        if not exch:
            continue
        try:
            for r in await zerodha_service.zerodha.fetch_instruments(exch):
                tok = r.get("token") or r.get("instrumentToken") or r.get("instrument_token")
                if tok is not None:
                    catalogue[str(tok)] = r
        except Exception:  # noqa: BLE001 — no catalogue, no decision
            logger.warning("expiry_heal_catalogue_unavailable", extra={"exchange": exch})
            return 0

    for inst in rows:
        row = catalogue.get(str(inst.token))
        if row is None:
            # Gone from upstream. A derivative the exchange no longer lists is
            # an expired one; leaving it tradable is how a dead contract keeps
            # quoting.
            inst.is_active = False
            inst.is_tradable = False
            await inst.save()
            retired += 1
            logger.warning(
                "expiry_heal_retired_delisted",
                extra={"token": inst.token, "symbol": inst.symbol},
            )
            continue

        exp = row.get("expiry")
        if not exp:
            continue
        try:
            inst.expiry = (
                exp if isinstance(exp, datetime)
                else datetime.combine(date.fromisoformat(str(exp)[:10]), time(0, 0))
            )
            await inst.save()
            healed += 1
            logger.info(
                "expiry_heal_filled",
                extra={"token": inst.token, "symbol": inst.symbol, "expiry": str(exp)[:10]},
            )
        except Exception:  # noqa: BLE001 — a bad date must not stop the rest
            logger.debug("expiry_heal_parse_failed", extra={"token": inst.token})

    if healed or retired:
        logger.warning(
            "expiry_heal_done", extra={"filled": healed, "retired": retired}
        )
    return healed + retired


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

    # ── Orphans: expired contracts retired by SOMEONE ELSE ────────────
    # This sweep only picks up `is_active: True` rows below, and it is not the
    # only thing that retires a contract. `binance_options_service` flips a
    # crypto option inactive the moment it leaves the universe — without
    # touching watchlists — so by the time this runs the row is already
    # inactive, never becomes a candidate, and its watchlist items are never
    # yanked. Measured live: 8 watchlist rows pointing at BTC options that
    # expired 14-16 Aug, a month earlier, each rendering 0.00 on screen.
    #
    # Keyed on EXPIRED + inactive, not inactive alone: an instrument switched
    # off for any other reason (an admin block, a halted script) may come back,
    # and the user should get their watchlist row back with it.
    # A derivative with no expiry date is invisible to every query below, so
    # it can never be retired. Give it its date back — or retire it outright
    # when the exchange has already dropped it.
    try:
        await _heal_missing_expiry()
    except Exception:  # noqa: BLE001 — never block the sweep on the heal
        logger.exception("expiry_heal_failed_continuing")

    orphans_removed = 0
    try:
        dead = await Instrument.find(
            {"expiry": {"$ne": None, "$lt": today}, "is_active": False}
        ).to_list()
        dead_tokens = [str(i.token) for i in dead]
        if dead_tokens:
            res = await WatchlistItem.find(
                {"instrument_token": {"$in": dead_tokens}}
            ).delete()
            orphans_removed = getattr(res, "deleted_count", 0) or 0
            if orphans_removed:
                logger.info("expiry_cleanup_orphan_watchlist_removed=%s", orphans_removed)
    except Exception:  # noqa: BLE001 — a tidy-up must never block settlement
        logger.exception("expiry_cleanup_orphan_sweep_failed")

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
            "watchlist_items": orphans_removed,
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
    from app.services import holiday_service

    for _pos in open_in_expired:
        try:
            # No session today → no settlement. It would book the previous
            # session's price as if it were the expiry print.
            if await holiday_service.is_segment_holiday(
                getattr(_pos.instrument, "segment", None)
            ):
                continue
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
        "watchlist_items": wl_removed + orphans_removed,
        "unsubscribed": unsubbed,
        "positions_settled": settled,
        "orders_cancelled": orders_cancelled,
    }


async def settle_expired_crypto_options() -> dict:
    """Close open CRYPTO OPTION positions once their contract has expired.

    WHEN: the super-admin's `crypto_expiry.settle_time`, read as an IST clock
    time on the contract's expiry date. It used to be hardcoded at 08:00 UTC —
    Binance's own settlement — and that is still the default, so an operator
    who never opens the setting sees no change.

    AT WHAT PRICE: the option's own LTP, which is what the operator asked for
    ("LTP me close ho jaye"). It falls back to INTRINSIC when there is no live
    LTP:

      • CALL  → intrinsic = max(0, spot − strike)
      • PUT   → intrinsic = max(0, strike − spot)

    The fallback matters. A stale premium is the one number that must not be
    used here: settling an out-of-the-money option at the last price anybody
    quoted for it pays the buyer for a contract that expired worthless. On a
    live book the two agree anyway — an option's mark AT expiry is its
    intrinsic — so this only bites when the feed has gone quiet.

    Leader-only. Skips (and retries next tick) when neither price is available.
    """
    from datetime import datetime, timezone

    from app.models.position import Position, PositionStatus
    from app.services import market_data_service, position_service
    from app.utils.decimal_utils import ZERO, to_decimal

    from app.services import crypto_expiry_settings as _ces
    from app.utils.time_utils import IST

    now = datetime.now(timezone.utc)
    settle_at = await _ces.settle_time_ist()
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
            strike_raw = getattr(inst, "strike", None)
            opt_raw = getattr(inst, "option_type", None)
            underlying = getattr(inst, "underlying_token", None)
            # The position's embedded instrument snapshot is written WITHOUT
            # expiry / strike / option type for crypto options, so reading only
            # the snapshot skipped every one of them — 11-Sep contracts still
            # OPEN past 13:30, a 6-Sep one still open five days on. The
            # Instrument row carries all three; it is kept (inactive) after
            # expiry, so it is still there to read.
            if exp is None or strike_raw is None or not opt_raw:
                row = await Instrument.find_one(Instrument.token == inst.token)
                if row is not None:
                    exp = exp or row.expiry
                    strike_raw = strike_raw if strike_raw is not None else row.strike
                    opt_raw = opt_raw or row.option_type
                    underlying = underlying or getattr(row, "underlying_token", None)
            if exp is None:
                continue
            exp_date = exp.date() if hasattr(exp, "date") else exp
            # The configured IST clock time on the expiry date, in UTC.
            exp_dt = datetime.combine(exp_date, settle_at, tzinfo=IST).astimezone(
                timezone.utc
            )
            if now < exp_dt:
                continue  # not expired yet
            if now - exp_dt > timedelta(hours=_STALE_EXPIRY_HOURS):
                # Long past expiry: the intrinsic fallback below would price it
                # off TODAY's spot, not the spot at its own expiry. Leave it for
                # an operator to settle at a known price rather than guess.
                logger.warning(
                    "crypto_opt_settle_stale_skip pos=%s token=%s expiry=%s",
                    pos.id, inst.token, exp_date,
                )
                continue

            # The option's OWN last price — what the operator asked to settle at.
            try:
                px = to_decimal(await market_data_service.get_ltp(inst.token))
            except Exception:
                px = ZERO

            strike = to_decimal(strike_raw)
            opt_type = str(getattr(opt_raw, "value", opt_raw) or "").upper()
            if px <= ZERO:
                # No live LTP. Fall back to intrinsic rather than to a stale
                # premium — see the docstring.
                try:
                    # `underlying`, not `inst.underlying_token`: the snapshot
                    # has no such field, the AttributeError landed in the
                    # except below as spot=0, and the sweep skipped silently.
                    spot = to_decimal(
                        await market_data_service.get_ltp(underlying or "CRYPTO_BTCUSD")
                    )
                except Exception:
                    spot = ZERO
                if spot <= ZERO:
                    continue  # neither price — retry next sweep
                px = (
                    max(ZERO, spot - strike)
                    if opt_type in ("CE", "C", "CALL")
                    else max(ZERO, strike - spot)
                )
            res = await position_service.settle_expired_position(
                pos, settlement_price=px, allow_zero=True, reason="CRYPTO_OPT_EXPIRY"
            )
            if res == "settled":
                settled += 1
                logger.info(
                    "crypto_opt_settled token=%s price=%s strike=%s type=%s at=%s",
                    inst.token, px, strike, opt_type, settle_at,
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


_crypto_running = False


async def crypto_settlement_loop(interval_sec: float = 60.0) -> None:
    """Fast sweep for the crypto option settlement clock.

    The hourly cleanup still calls the same sweep as a backstop, but an hourly
    tick cannot honour a clock TIME: set 11:00 and the position closes whenever
    the hour happens to come round, up to an hour late. A settlement the
    operator sets to the minute has to be checked at that resolution.

    Cheap by construction — one indexed query for open crypto option positions,
    which is empty on most books and short on the rest. Idempotent: the sweep
    itself skips anything already settled.
    """
    global _crypto_running
    if _crypto_running:
        return
    _crypto_running = True
    logger.info("crypto_settlement_loop_started", extra={"interval_sec": interval_sec})
    try:
        while _crypto_running:
            try:
                await settle_expired_crypto_options()
            except Exception:
                logger.exception("crypto_settlement_tick_failed")
            await asyncio.sleep(interval_sec)
    finally:
        _crypto_running = False
        logger.info("crypto_settlement_loop_stopped")


def stop_crypto_settlement() -> None:
    global _crypto_running
    _crypto_running = False


def stop_expiry_cleanup() -> None:
    global _running
    _running = False
