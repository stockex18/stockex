"""Position + Holding maintenance.

Called by the matching engine on each fill: updates the user's open Position
(or closes one out), maintains the per-(user,segment,instrument) tracker,
and for CNC trades writes/updates the long-term Holding record.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from beanie import PydanticObjectId
from bson import Decimal128

from app.models._base import OrderAction, ProductType
from app.models.holding import Holding
from app.models.order import InstrumentRef
from app.models.position import Position, PositionStatus, UserPositionTracker
from app.utils.decimal_utils import (
    ZERO,
    add,
    quantize_money,
    sub,
    to_decimal,
    to_decimal128,
)
from app.utils.time_utils import now_utc


async def apply_fill(
    *,
    user_id: PydanticObjectId,
    instrument: InstrumentRef,
    segment_type: str,
    action: OrderAction,
    product_type: ProductType,
    quantity: float,
    price: Decimal,
    margin_used: Decimal,
    stop_loss: Decimal | None = None,
    target: Decimal | None = None,
    is_demo: bool = False,
) -> Position:
    """Idempotent-ish: looks up an open position for this instrument+product
    and merges. For opposite-side fills it reduces and may close out."""
    pos = await Position.find_one(
        Position.user_id == user_id,
        Position.instrument.token == instrument.token,  # type: ignore[union-attr]
        Position.product_type == product_type,
        Position.status == PositionStatus.OPEN,
    )

    signed_qty = quantity if action == OrderAction.BUY else -quantity

    # Capture the prevailing USD/INR rate at the moment of fill — used later
    # to convert P&L on USD-quoted instruments (BTCUSD, EURUSD, …) into INR.
    # ``None`` for instruments already priced in INR.
    from app.services.market_data_service import get_usd_inr_rate, is_usd_quoted_segment

    open_fx_rate = (
        Decimal128(str(round(get_usd_inr_rate(), 4)))
        if is_usd_quoted_segment(segment_type) or is_usd_quoted_segment(instrument.segment)
        else None
    )

    if pos is None:
        pos = Position(
            user_id=user_id,
            instrument=instrument,
            segment_type=segment_type,
            product_type=product_type,
            quantity=signed_qty,
            # Stamp the side at open so the Closed-tab card knows whether
            # the user originally went long or short, even after quantity
            # is reduced to 0 by the closing leg.
            opened_side=action,
            opening_quantity=abs(signed_qty),
            avg_price=Decimal128(str(price)),
            ltp=Decimal128(str(price)),
            margin_used=Decimal128(str(margin_used)),
            stop_loss=Decimal128(str(stop_loss)) if stop_loss is not None else None,
            target=Decimal128(str(target)) if target is not None else None,
            open_usd_inr_rate=open_fx_rate,
            opened_at=now_utc(),
            status=PositionStatus.OPEN,
            is_demo=is_demo,
        )
        await pos.insert()
    else:
        cur_qty = pos.quantity
        new_qty = cur_qty + signed_qty
        cur_avg = to_decimal(pos.avg_price)

        # The position's `margin_used` represents how much wallet margin is
        # currently locked against this position. It must scale with
        # |quantity|, NOT just accumulate on every fill — otherwise SELL
        # legs that close a long add margin on top of the BUY margin instead
        # of releasing it, and the field grows by ~2× per round-trip cycle.
        # We compute the new margin_used below based on what kind of fill
        # this is, then assign it in one place.
        new_margin_used: Decimal | None = None

        # Whether the new order's bracket SL/TP should overwrite what's on
        # the position. Only the SAME-direction paths (fresh re-open after
        # close, same-side pyramid, or the new-direction half of a flip)
        # carry SL/TP that make sense for the surviving position. A
        # closing leg's bracket is for THAT closing trade — applying it
        # to the (still-open) original-direction position puts the SL/TP
        # on the wrong side of avg_price, which the risk-enforcer's
        # self-heal then clears the next tick. That's the
        # "SL/TP set kiya par position se gayab ho gaya" symptom.
        apply_brackets = False
        if cur_qty == 0:
            # Previously closed position being reopened on this fill.
            pos.avg_price = Decimal128(str(price))
            pos.quantity = signed_qty
            # Reopen — reset the recorded opening side to the new direction.
            pos.opened_side = action
            pos.opening_quantity = abs(signed_qty)
            new_margin_used = to_decimal(margin_used)
            apply_brackets = True
        elif (cur_qty > 0 and signed_qty > 0) or (cur_qty < 0 and signed_qty < 0):
            # Same side (pyramiding): weighted avg, ADD the new leg's margin.
            total = to_decimal(abs(cur_qty) + abs(signed_qty))
            pos.avg_price = Decimal128(
                str(quantize_money((cur_avg * to_decimal(abs(cur_qty)) + price * to_decimal(abs(signed_qty))) / total))
            )
            pos.quantity = new_qty
            pos.opening_quantity = max(float(pos.opening_quantity or 0), abs(new_qty))
            new_margin_used = to_decimal(pos.margin_used) + to_decimal(margin_used)
            apply_brackets = True
        else:
            # Opposite side: realize PnL on the closed portion + release
            # margin proportional to how much of the original was closed.
            closed_qty = min(abs(cur_qty), abs(signed_qty))
            sign = 1 if cur_qty > 0 else -1
            realized = (price - cur_avg) * to_decimal(closed_qty) * sign
            pos.realized_pnl = Decimal128(str(quantize_money(to_decimal(pos.realized_pnl) + realized)))
            pos.quantity = new_qty
            if new_qty == 0:
                # Fully closed: all locked margin against this position is freed.
                pos.status = PositionStatus.CLOSED
                pos.closed_at = now_utc()
                if pos.open_usd_inr_rate is not None and pos.close_usd_inr_rate is None:
                    pos.close_usd_inr_rate = Decimal128(str(round(get_usd_inr_rate(), 4)))
                new_margin_used = to_decimal(0)
                # Snapshot the live SL / TP BEFORE we clear them, so the
                # Closed-tab card on the user side can still surface
                # "Trade had SL 🪙X, TP 🪙Y" — even though the live fields
                # are about to be wiped to keep reopens clean. Operator's
                # 22-May spec: user ko close trade me bhi visible rahe
                # ki SL/TP kitna laga tha.
                if pos.stop_loss is not None and pos.close_stop_loss is None:
                    pos.close_stop_loss = pos.stop_loss
                if pos.target is not None and pos.close_target is None:
                    pos.close_target = pos.target
                # Position is closing — clear any SL/TP that were on it so a
                # later re-open on the same instrument doesn't inherit stale
                # brackets from a long-gone direction. `apply_brackets` stays
                # False; the closing order's own bracket is meaningless here.
                pos.stop_loss = None
                pos.target = None
            elif (cur_qty > 0 and new_qty < 0) or (cur_qty < 0 and new_qty > 0):
                # Flipped sides — the closing leg fully cleared the original
                # direction; whatever of `signed_qty` remained opened a new
                # opposite position. Margin = the portion of the new order
                # margin that backs the remaining qty.
                pos.avg_price = Decimal128(str(price))
                # Flip — record the new active direction so the Closed-tab
                # card (and anyone else reading `opened_side`) reflects the
                # surviving leg, not the one that was just flattened.
                pos.opened_side = action
                pos.opening_quantity = abs(new_qty)
                if open_fx_rate is not None:
                    pos.open_usd_inr_rate = open_fx_rate
                flip_ratio = to_decimal(abs(new_qty)) / to_decimal(abs(signed_qty))
                new_margin_used = to_decimal(margin_used) * flip_ratio
                # Direction flipped — old SL/TP were positioned for the OLD
                # direction (e.g. SL above entry for a SHORT). On the new
                # opposite-side position they'd be on the wrong side of the
                # new avg and self-heal would clear them anyway. Wipe up
                # front so the bracket from THIS order (if any) cleanly
                # replaces them via apply_brackets below.
                pos.stop_loss = None
                pos.target = None
                apply_brackets = True
            else:
                # Partial close on same side: scale the existing margin down
                # to the remaining quantity ratio. (The SELL order itself
                # doesn't add new locked margin — it releases existing.)
                scale = to_decimal(abs(new_qty)) / to_decimal(abs(cur_qty))
                new_margin_used = to_decimal(pos.margin_used) * scale
                # apply_brackets stays False — the surviving position is in
                # its original direction with its original avg, so existing
                # SL/TP remain valid (if any). The closing order's bracket
                # was sized for the closing direction and would land on the
                # wrong side if we wrote it onto the surviving position.

        pos.ltp = Decimal128(str(price))
        if new_margin_used is not None:
            # Floor at 0 so accumulated rounding can't drive it negative.
            if new_margin_used < 0:
                new_margin_used = to_decimal(0)
            pos.margin_used = Decimal128(str(quantize_money(new_margin_used)))
        # Carry over SL/TP from the originating Order ONLY on paths where
        # the new order opens / extends exposure in the surviving
        # position's direction (see apply_brackets logic above). Latest
        # bracket wins over the existing one — matches Zerodha's behaviour
        # so the user can update bracket SL/TP by placing a fresh order.
        if apply_brackets:
            if stop_loss is not None:
                pos.stop_loss = Decimal128(str(stop_loss))
            if target is not None:
                pos.target = Decimal128(str(target))
        await pos.save()

    # Tracker — RECOMPUTE from the live Position rows for this
    # (user, instrument) rather than incrementally adjusting by delta_lots.
    # Delta-based updates drift over time (partial fills retried by the
    # network, position flips where signed_qty crosses zero, mid-fill
    # backend restarts, etc.) — symptom: `holding_lots=47` on an
    # instrument with NO open position, which then blocks every future
    # buy/sell because the validator reads stale lots.
    # Recomputing from the authoritative Position docs after each fill
    # turns the tracker into a derived cache that can never drift past
    # one fill. Self-heal job (see periodic reconciler) catches any
    # historical drift.
    await _recompute_tracker(
        user_id=user_id, segment_type=segment_type, token=instrument.token
    )

    # CNC also updates long-term Holding
    if product_type == ProductType.CNC:
        await _apply_holding(
            user_id=user_id,
            instrument=instrument,
            action=action,
            quantity=quantity,
            price=price,
        )

    # Notify admin dashboards — every fill (matching-engine market fill,
    # SL/TP hit, user squareoff, admin force-close) routes through here
    # so one publish at the bottom of `apply_fill` covers all of them.
    # Fire-and-forget; failures are swallowed inside `publish_admin_event`.
    try:
        from app.services.admin_events import publish_admin_event

        await publish_admin_event(
            "position_update",
            {
                "event": "fill",
                "user_id": str(user_id),
                "position_id": str(pos.id),
                "status": pos.status.value,
            },
        )
    except Exception:  # pragma: no cover
        pass

    return pos


async def settle_expired_position(
    pos: Position,
    *,
    settlement_price: Decimal | None = None,
    reason: str = "EXPIRY_SETTLED",
    allow_zero: bool = False,
) -> str:
    """Force-close ONE open position whose underlying contract has expired.

    Why this exists: ``expiry_cleanup`` unsubscribes an expired contract's
    token from the live feed and marks the instrument inactive — but it
    never closed open positions in that contract. The result was *zombie*
    positions: the risk-enforcer can never price a dead/unsubscribed token,
    so it silently SKIPS SL/TP/stop-out for them every tick
    (``risk_ltp_fetch_failed`` flood), the position sits OPEN forever and
    the user's margin stays locked. This settles the position once at the
    last-known price and releases that margin.

    Unlike ``weekly_settlement`` (which carries the exposure forward by
    re-opening a fresh row), this does NOT re-open — the contract is dead —
    and it DOES release the locked margin.

    Settlement-price selection (never books at 0):
      1. explicit ``settlement_price`` arg, else
      2. live LTP if the token still ticks (first day-after sweep), else
      3. the position's own frozen ``ltp`` (last-good tick before expiry).
    Returns ``"skipped"`` if no usable (>0) price exists so a later run can
    retry; ``"settled"`` on success; ``"failed"`` on error.

    Idempotent at the caller level: operates only on OPEN rows and flips
    status→CLOSED, so a repeat sweep won't double-book.
    """
    import logging as _logging

    from app.core.exceptions import InsufficientFundsError
    from app.models.transaction import TransactionType
    from app.services import market_data_service, wallet_router, wallet_service
    from app.services.market_data_service import (
        get_usd_inr_rate,
        is_usd_quoted_segment,
    )

    log = _logging.getLogger(__name__)

    if pos.status != PositionStatus.OPEN:
        return "skipped"
    qty_signed = float(pos.quantity or 0)
    if abs(qty_signed) < 1e-9:
        return "skipped"

    token = pos.instrument.token

    # ── Resolve the settlement price ─────────────────────────────────
    settle = (
        quantize_money(to_decimal(settlement_price))
        if settlement_price is not None
        else ZERO
    )
    if settlement_price is not None and allow_zero:
        # EXPLICIT expiry settlement with a KNOWN price (option intrinsic value —
        # 0 for an out-of-the-money option that expires worthless). Honour it
        # as-is and skip the live/frozen fallback, so an OTM option books at 0
        # (buyer loses the full premium) instead of the last mark price.
        settle = max(ZERO, settle)
    else:
        if settle <= ZERO:
            try:
                settle = quantize_money(to_decimal(await market_data_service.get_ltp(token)))
            except Exception:  # noqa: BLE001
                settle = ZERO
        if settle <= ZERO:
            settle = quantize_money(to_decimal(pos.ltp))
        if settle <= ZERO:
            # No usable price anywhere — never settle at 0. Leave OPEN so a
            # later run (with an admin-supplied price) can settle it.
            log.info(
                "expiry_settlement_skip_no_price pos=%s token=%s symbol=%s",
                pos.id,
                token,
                pos.instrument.symbol,
            )
            return "skipped"

    # ── Realized P&L — identical formula to matching_engine / weekly ──
    avg = to_decimal(pos.avg_price)
    closed_qty = to_decimal(abs(qty_signed))
    sign = Decimal(1) if qty_signed > 0 else Decimal(-1)
    realized = (settle - avg) * closed_qty * sign

    is_usd = is_usd_quoted_segment(pos.segment_type) or is_usd_quoted_segment(
        pos.instrument.segment
    )
    fx_rate: Decimal | None = None
    if is_usd:
        fx_rate = to_decimal(round(get_usd_inr_rate(), 4))
        realized = realized * fx_rate
    realized = quantize_money(realized)

    try:
        # 1) Release the full margin locked against this (now-dead) position.
        margin = to_decimal(pos.margin_used)
        if margin > ZERO:
            await wallet_router.release_margin(pos.user_id, pos.segment_type, margin)

        # 2) Book realized P&L. Losses past available balance fall back to
        #    force_debit → settlement_outstanding (same as the stop-out path);
        #    this is a forced close so it must complete.
        if realized != ZERO:
            narration = (
                f"Expiry settlement: {'profit' if realized > 0 else 'loss'} "
                f"on {pos.instrument.symbol}"
            )
            try:
                await wallet_router.adjust(
                    pos.user_id,
                    pos.segment_type,
                    realized,
                    transaction_type=TransactionType.PNL,
                    narration=narration,
                    reference_type="EXPIRY_SETTLEMENT",
                    reference_id=str(pos.id),
                )
            except InsufficientFundsError:
                if realized < ZERO:
                    await wallet_router.force_debit(
                        pos.user_id,
                        pos.segment_type,
                        -realized,
                        transaction_type=TransactionType.PNL,
                        narration=f"{narration} (shortfall booked to outstanding)",
                        reference_type="EXPIRY_SETTLEMENT",
                        reference_id=str(pos.id),
                    )
                else:
                    raise

        # 3) Close the position for good (no re-open — contract is dead).
        now = now_utc()
        pos.status = PositionStatus.CLOSED
        pos.closed_at = now
        pos.close_reason = reason
        pos.ltp = Decimal128(str(settle))
        pos.realized_pnl = Decimal128(
            str(quantize_money(to_decimal(pos.realized_pnl) + realized))
        )
        pos.unrealized_pnl = Decimal128("0")
        pos.quantity = 0.0
        pos.margin_used = Decimal128("0")
        if (
            is_usd
            and fx_rate is not None
            and pos.open_usd_inr_rate is not None
            and pos.close_usd_inr_rate is None
        ):
            pos.close_usd_inr_rate = Decimal128(str(fx_rate))
        if pos.stop_loss is not None and pos.close_stop_loss is None:
            pos.close_stop_loss = pos.stop_loss
        if pos.target is not None and pos.close_target is None:
            pos.close_target = pos.target
        pos.stop_loss = None
        pos.target = None
        await pos.save()

        # 4) Tracker recompute — drift-immune (old OPEN row is now CLOSED).
        try:
            await _recompute_tracker(
                user_id=pos.user_id,
                segment_type=pos.segment_type,
                token=token,
            )
        except Exception:  # noqa: BLE001
            log.exception("expiry_settlement_tracker_recompute_failed pos=%s", pos.id)

        # 5) Best-effort UI refresh — never fail the settlement on Redis.
        try:
            from app.core.redis_client import publish

            await publish(
                f"user:{pos.user_id}:positions",
                {"type": "positions", "payload": {"reason": "expiry_settlement"}},
            )
        except Exception:  # noqa: BLE001
            pass

        log.info(
            "expiry_settlement_settled",
            extra={
                "user_id": str(pos.user_id),
                "position_id": str(pos.id),
                "symbol": pos.instrument.symbol,
                "settle_price": str(settle),
                "realized_pnl": str(realized),
                "margin_released": str(margin),
            },
        )
        return "settled"
    except Exception:  # noqa: BLE001
        log.exception(
            "expiry_settlement_failed pos=%s user=%s symbol=%s",
            pos.id,
            pos.user_id,
            pos.instrument.symbol,
        )
        return "failed"


async def _recompute_tracker(
    *,
    user_id: PydanticObjectId,
    segment_type: str,
    token: str,
) -> None:
    """Source-of-truth tracker rebuild.

    Sums the open `Position` rows for this (user, instrument) and writes
    the result into `UserPositionTracker`. Replaces the older
    `_bump_tracker` delta-increment path which drifted whenever a fill
    retry / position flip / mid-flow restart skewed the running counter
    (production symptom: BTCUSD `holding_lots=47` with zero open
    positions, blocking every subsequent order via the validator's
    holding-limit check).

    Idempotent — running it twice with the same DB state produces the
    same tracker row.
    """
    open_positions = await Position.find(
        Position.user_id == user_id,
        Position.instrument.token == token,  # type: ignore[union-attr]
        Position.status == PositionStatus.OPEN,
    ).to_list()

    intraday_lots = 0.0
    holding_lots = 0.0
    margin_blocked: Decimal = ZERO

    for p in open_positions:
        # Lot size 0 / missing on legacy rows → treat as 1 so |qty| ÷ 1
        # = qty (matches the pre-fix behaviour for those rows).
        lot_size = max(1, int(p.instrument.lot_size or 1))
        lots = abs(float(p.quantity or 0)) / lot_size
        if p.product_type == ProductType.MIS:
            intraday_lots += lots
        else:
            holding_lots += lots
        margin_blocked = add(margin_blocked, to_decimal(p.margin_used or 0))

    t = await UserPositionTracker.find_one(
        UserPositionTracker.user_id == user_id,
        UserPositionTracker.segment_type == segment_type,
        UserPositionTracker.instrument_token == token,
    )
    if t is None:
        t = UserPositionTracker(
            user_id=user_id, segment_type=segment_type, instrument_token=token
        )
    t.intraday_lots = intraday_lots
    t.holding_lots = holding_lots
    t.total_lots = intraday_lots + holding_lots
    t.margin_blocked = to_decimal128(margin_blocked)
    await t.save()


async def reconcile_all_trackers() -> dict[str, int]:
    """Platform-wide tracker reconciliation. Walks every tracker row in
    the system and rebuilds it from the live Position docs.

    Cheap because the unique index on `user_position_tracker` is
    (user_id, segment_type, instrument_token) — each recompute is one
    indexed Position query. On a system with N users and avg M tracker
    rows per user, total work is O(N·M) but each unit is sub-millisecond.

    Designed to be called by a slow background loop (15-30 min cadence)
    so any drift introduced by a bug or unexpected restart self-heals
    without operator intervention. Returns a summary the loop logs.
    """
    import logging

    log = logging.getLogger(__name__)
    trackers = await UserPositionTracker.find_all().to_list()
    scanned = 0
    repaired = 0
    deleted = 0
    for t in trackers:
        scanned += 1
        before = (t.intraday_lots, t.holding_lots)
        try:
            await _recompute_tracker(
                user_id=t.user_id,
                segment_type=t.segment_type,
                token=t.instrument_token,
            )
        except Exception:
            log.warning(
                "tracker_reconcile_failed user=%s token=%s",
                t.user_id,
                t.instrument_token,
                exc_info=True,
            )
            continue
        fresh = await UserPositionTracker.find_one(
            UserPositionTracker.user_id == t.user_id,
            UserPositionTracker.segment_type == t.segment_type,
            UserPositionTracker.instrument_token == t.instrument_token,
        )
        if fresh is None:
            continue
        if (fresh.intraday_lots, fresh.holding_lots) != before:
            repaired += 1
        if (
            fresh.intraday_lots == 0
            and fresh.holding_lots == 0
            and to_decimal(fresh.margin_blocked or 0) == ZERO
        ):
            still_open = await Position.find_one(
                Position.user_id == t.user_id,
                Position.instrument.token == fresh.instrument_token,  # type: ignore[union-attr]
                Position.status == PositionStatus.OPEN,
            )
            if still_open is None:
                await fresh.delete()
                deleted += 1
    if repaired or deleted:
        log.info(
            "tracker_reconcile scanned=%s repaired=%s deleted=%s",
            scanned,
            repaired,
            deleted,
        )
    return {"scanned": scanned, "repaired": repaired, "deleted": deleted}


_tracker_loop_stop = False


def stop_tracker_reconcile_loop() -> None:
    global _tracker_loop_stop
    _tracker_loop_stop = True


async def tracker_reconcile_loop(interval_sec: float = 900.0) -> None:
    """Background self-heal — recomputes every tracker row from positions
    every `interval_sec` (default 15 min). Catches any historical drift
    that would otherwise block users via the order validator's
    holding/intraday limit checks.

    Safe to run alongside live fills: `_recompute_tracker` is idempotent
    and races resolve to the latest Position state on its next pass.
    """
    import asyncio as _asyncio
    import logging

    log = logging.getLogger(__name__)
    log.info("tracker_reconcile_loop starting interval_sec=%s", interval_sec)
    # Initial 60-second delay so we don't fight boot-time tasks for the
    # connection pool.
    try:
        await _asyncio.sleep(60.0)
    except Exception:
        return
    while not _tracker_loop_stop:
        try:
            await reconcile_all_trackers()
            # Wallet used_margin reconcile runs alongside the tracker
            # reconcile so any drift introduced by an unexpected
            # restart / admin hard-delete / partial-close math
            # mismatch heals automatically within one cycle.
            try:
                from app.services import wallet_service as _ws

                await _ws.reconcile_all_used_margins()
            except Exception:
                log.warning(
                    "wallet_used_margin_reconcile_iteration_failed",
                    exc_info=True,
                )
        except Exception:
            log.warning("tracker_reconcile_loop_iteration_failed", exc_info=True)
        try:
            await _asyncio.sleep(interval_sec)
        except Exception:
            break


async def reconcile_trackers_for_user(user_id: PydanticObjectId) -> dict[str, int]:
    """Walk every tracker row this user owns and recompute it from the
    live Position docs. Returns a small summary so an admin endpoint /
    cron can log what was repaired.

    Two passes:
      1. Recompute existing tracker rows.
      2. Delete tracker rows that aren't referenced by any open position
         AND now show all-zeros — they're harmless but clutter the
         collection. We only delete the all-zero, no-position case to
         avoid racing with an in-flight fill that's just about to
         create the position.
    """
    trackers = await UserPositionTracker.find(
        UserPositionTracker.user_id == user_id
    ).to_list()
    repaired = 0
    deleted = 0
    for t in trackers:
        before = (t.intraday_lots, t.holding_lots)
        await _recompute_tracker(
            user_id=user_id, segment_type=t.segment_type, token=t.instrument_token
        )
        # Re-read (the helper may have flipped fields)
        fresh = await UserPositionTracker.find_one(
            UserPositionTracker.user_id == user_id,
            UserPositionTracker.segment_type == t.segment_type,
            UserPositionTracker.instrument_token == t.instrument_token,
        )
        if fresh is None:
            continue
        if (fresh.intraday_lots, fresh.holding_lots) != before:
            repaired += 1
        if (
            fresh.intraday_lots == 0
            and fresh.holding_lots == 0
            and to_decimal(fresh.margin_blocked or 0) == ZERO
        ):
            still_open = await Position.find_one(
                Position.user_id == user_id,
                Position.instrument.token == fresh.instrument_token,  # type: ignore[union-attr]
                Position.status == PositionStatus.OPEN,
            )
            if still_open is None:
                await fresh.delete()
                deleted += 1
    return {"scanned": len(trackers), "repaired": repaired, "deleted": deleted}


async def _apply_holding(
    *,
    user_id: PydanticObjectId,
    instrument: InstrumentRef,
    action: OrderAction,
    quantity: float,
    price: Decimal,
) -> None:
    h = await Holding.find_one(
        Holding.user_id == user_id, Holding.instrument.token == instrument.token  # type: ignore[union-attr]
    )
    qty_dec = to_decimal(quantity)
    if h is None:
        if action == OrderAction.BUY:
            h = Holding(
                user_id=user_id,
                instrument=instrument,
                quantity=quantity,
                avg_price=Decimal128(str(price)),
                ltp=Decimal128(str(price)),
                invested_value=Decimal128(str(quantize_money(price * qty_dec))),
                current_value=Decimal128(str(quantize_money(price * qty_dec))),
            )
            await h.insert()
        return

    if action == OrderAction.BUY:
        new_qty = h.quantity + quantity
        denom = to_decimal(max(1.0, new_qty))
        new_avg = quantize_money(
            (to_decimal(h.avg_price) * to_decimal(h.quantity) + price * qty_dec) / denom
        )
        h.quantity = new_qty
        h.avg_price = Decimal128(str(new_avg))
    else:
        # SELL — reduce
        h.quantity = max(0.0, h.quantity - quantity)

    h.ltp = Decimal128(str(price))
    h.invested_value = Decimal128(
        str(quantize_money(to_decimal(h.avg_price) * to_decimal(h.quantity)))
    )
    h.current_value = Decimal128(
        str(quantize_money(to_decimal(h.ltp) * to_decimal(h.quantity)))
    )
    pnl = sub(h.current_value, h.invested_value)
    h.pnl = Decimal128(str(pnl))
    invested = to_decimal(h.invested_value)
    h.pnl_percentage = float((pnl / invested) * 100) if invested > ZERO else 0.0
    if h.quantity == 0:
        await h.delete()
    else:
        await h.save()


async def list_open(user_id: str | PydanticObjectId) -> list[Position]:
    # Newest-opened position FIRST so the just-entered trade lands at
    # the top of the user's Positions tab instead of the bottom.
    # User-flagged: "abhi latest position last me ja raha hai, turat
    # vale ko sabse upar rakho aur jo sabse pehle liya hoga ve last
    # me jaye". Sorting on the server (rather than re-sorting in the
    # frontend on every render) also keeps the active-trades drilldown
    # consistent with the row order shown above it.
    return await (
        Position.find(
            Position.user_id == PydanticObjectId(user_id),
            Position.status == PositionStatus.OPEN,
        )
        .sort("-opened_at")
        .to_list()
    )


async def list_closed_today(user_id: str | PydanticObjectId) -> list[Position]:
    """Closed positions blotter — returns the most recent 200 closes,
    newest first. Previously filtered by `closed_at >= IST midnight`
    which silently hid positions closed yesterday or earlier, so the
    Closed tab rendered empty for traders who hadn't closed anything
    today. We keep the legacy name to avoid touching every caller,
    but the implementation is now date-agnostic.

    A trader who actively wants only "today" already has the dashboard
    Today's P&L cards + the realized window on /reports/pnl, so
    surfacing ALL closes here is the more useful default.
    """
    return await (
        Position.find(
            Position.user_id == PydanticObjectId(user_id),
            Position.status == PositionStatus.CLOSED,
        )
        .sort("-closed_at")
        .limit(200)
        .to_list()
    )


async def list_closed_trade_events(
    user_id: str | PydanticObjectId,
    *,
    limit: int = 200,
) -> list[dict]:
    """Per-close blotter rows reconstructed from the trade tape.

    The Closed tab used to list CLOSED *positions* only, so a PARTIAL
    close (sell 2 of 5 lots) never showed — the position stayed OPEN and
    only surfaced once it hit qty 0. This walks the user's trades in
    chronological order, mirroring ``apply_fill``'s avg / pyramid / flip
    accounting, and emits ONE event per closing fill (partial OR full).

    The money numbers (realized P&L, brokerage) are taken DIRECTLY from
    the stored ``Trade.pnl_inr`` / ``total_charges`` so they stay frozen
    exactly as booked at fill time — we never recompute P&L here. The
    FIFO walk is only used to recover each close's entry ``avg_price`` and
    the lifecycle ``opened_at`` for display.

    Returns newest-first, capped at ``limit``. Each element is a
    self-contained dict the API layer formats into its row shape.
    """
    from app.models.trade import Trade

    # Fetch the most-recent 3 000 trades (newest-first) then reverse for the
    # chronological FIFO walk below. 3 000 covers ~200 closed events even for
    # heavy traders (avg 5–15 fills per lifecycle). Loading the entire tape is
    # O(T) and blocks for 1–2 s on accounts with 10 000+ trades.
    trades = await (
        Trade.find(Trade.user_id == PydanticObjectId(user_id))
        .sort("-executed_at")
        .limit(3000)
        .to_list()
    )
    trades.reverse()  # chronological order for FIFO walk
    if not trades:
        return []

    # Per (token, product_type) running lifecycle state.
    state: dict[tuple[str, str], dict[str, Any]] = {}
    events: list[dict] = []

    def _trade_charge(tr: Any) -> float:
        """Total brokerage stamped on a trade (close + other charges),
        falling back to the raw brokerage field for very old rows."""
        try:
            return float(
                str(getattr(tr, "total_charges", None) or getattr(tr, "brokerage", None) or 0)
            )
        except (TypeError, ValueError):
            return 0.0

    for t in trades:
        key = (t.instrument.token, t.product_type.value)
        qty = abs(float(t.quantity))
        if qty <= 0:
            continue
        price = float(str(t.price))
        signed = qty if t.action == OrderAction.BUY else -qty
        st = state.get(key)

        if st is None or abs(st["qty"]) < 1e-9:
            # Fresh open (or re-open on a flat lifecycle).
            state[key] = {
                "qty": signed,
                "avg": price,
                "opened_at": t.executed_at,
                # Opening-leg brokerage pool — accumulated on open / pyramid
                # fills and allocated proportionally to each closing fill so
                # the user's Closed-tab P&L nets the FULL lifecycle brokerage
                # (open + close), matching the admin Positions view exactly.
                "open_brk": _trade_charge(t),
                "open_qty": qty,
            }
            continue

        cur = st["qty"]
        same_side = (cur > 0 and signed > 0) or (cur < 0 and signed < 0)
        if same_side:
            # Pyramiding — weighted-average the entry, keep opened_at.
            denom = abs(cur) + abs(signed)
            st["avg"] = (
                (st["avg"] * abs(cur) + price * abs(signed)) / denom
                if denom
                else price
            )
            st["qty"] = cur + signed
            st["open_brk"] = float(st.get("open_brk", 0.0)) + _trade_charge(t)
            st["open_qty"] = float(st.get("open_qty", abs(cur))) + qty
            continue

        # Opposite side → this fill closes (this trade carries pnl_inr for
        # exactly the closed portion).
        closed_qty = min(abs(cur), qty)
        # Allocate a proportional slice of the still-unconsumed opening
        # brokerage to THIS closing fill. Summed across every closing fill
        # of a fully-closed lifecycle this equals the total opening
        # brokerage, so user_net = gross − (open + close brokerage) ==
        # admin Net P&L. Partial closes carry only their pro-rata slice.
        open_qty_pool = float(st.get("open_qty", abs(cur))) or abs(cur)
        open_brk_pool = float(st.get("open_brk", 0.0))
        open_brk_alloc = (
            open_brk_pool * (closed_qty / open_qty_pool) if open_qty_pool > 0 else 0.0
        )
        events.append(
            {
                "trade": t,
                "entry_avg": st["avg"],
                "opened_at": st["opened_at"],
                "closed_qty": closed_qty,
                "close_price": price,
                # Direction the user originally held (BUY = long, SELL = short).
                "opened_side": OrderAction.BUY.value if cur > 0 else OrderAction.SELL.value,
                # Pro-rata opening-leg brokerage for the closed quantity.
                "open_brokerage_alloc": open_brk_alloc,
            }
        )
        # Drain the consumed slice from the opening pool.
        st["open_brk"] = max(0.0, open_brk_pool - open_brk_alloc)
        st["open_qty"] = max(0.0, open_qty_pool - closed_qty)
        new_qty = cur + signed
        if abs(new_qty) < 1e-9:
            st["qty"] = 0.0
        elif (cur > 0) != (new_qty > 0):
            # Flipped — leftover opens a fresh opposite-direction lifecycle.
            # The flip fill's brokerage was booked as a CLOSE charge above,
            # so the new leg starts with an empty opening-brokerage pool.
            st["qty"] = new_qty
            st["avg"] = price
            st["opened_at"] = t.executed_at
            st["open_brk"] = 0.0
            st["open_qty"] = abs(new_qty)
        else:
            # Partial close — surviving leg keeps its avg + opened_at.
            st["qty"] = new_qty

    events.reverse()  # newest-first
    return events[:limit]


async def resync_closed_position_fills(position: Position) -> int:
    """Push an admin-edited CLOSED position's prices/P&L back onto its
    underlying Trade fills so the user-facing Closed blotter reflects it.

    WHY: the user "Closed" tab is rebuilt FIFO from `Trade` documents
    (entry = opening fill price, close = closing fill price, realised =
    (close-entry)*qty). `admin_edit_position` only rewrites the `Position`
    doc + a wallet REVERSAL — it never touched the fills, so an admin's
    open/close-price correction showed on the admin Position view but the
    user's history kept the OLD price/P&L. This syncs the fills.

    Targeting (no Position→Trade FK exists): fills for the same
    (user, token, product_type) executed inside the position's
    [opened_at, closed_at] window (±10s slack). Opening fills (pnl_inr is
    None) take the new avg_price; closing fills (pnl_inr set) take the new
    close price and a recomputed pnl_inr so P&L-based consumers (reports,
    reopen unwind) stay aligned. Best-effort — returns the number of fills
    updated; the caller logs and never lets a miss fail the edit.
    """
    from datetime import timedelta
    from app.models.trade import Trade
    from app.services import market_data_service as _mds

    if position.opened_at is None or position.closed_at is None:
        return 0

    lo = position.opened_at - timedelta(seconds=10)
    hi = position.closed_at + timedelta(seconds=10)
    trades = await Trade.find(
        {
            "user_id": position.user_id,
            "instrument.token": position.instrument.token,
            "product_type": position.product_type.value,
            "executed_at": {"$gte": lo, "$lte": hi},
        }
    ).to_list()
    if not trades:
        return 0

    new_avg = to_decimal(position.avg_price)
    new_close = to_decimal(position.ltp)
    opened_side = str(getattr(position, "opened_side", None) or "BUY").upper()
    sign = Decimal(1) if opened_side == "BUY" else Decimal(-1)

    # Mirror the admin recalc's FX basis: USD-quoted segments book P&L in
    # INR using the rate snapshotted at open (fallback to the live rate).
    is_usd = _mds.is_usd_quoted_segment(position.segment_type) or _mds.is_usd_quoted_segment(
        position.instrument.segment
    )
    fx = to_decimal(position.open_usd_inr_rate or _mds.get_usd_inr_rate()) if is_usd else Decimal(1)

    updated = 0
    for t in trades:
        qty = abs(to_decimal(t.quantity))
        if t.pnl_inr is None:
            # Opening fill → new entry price.
            t.price = to_decimal128(new_avg)
            t.value = to_decimal128(new_avg * to_decimal(t.quantity))
        else:
            # Closing fill → new close price + recomputed realised. Keep the
            # fill's own brokerage; pnl_inr stays net of the close leg to
            # match the matching-engine convention.
            gross = (new_close - new_avg) * qty * sign * fx
            close_brk = to_decimal(t.total_charges or t.brokerage or 0)
            t.price = to_decimal128(new_close)
            t.value = to_decimal128(new_close * to_decimal(t.quantity))
            t.pnl_inr = to_decimal128(quantize_money(gross - close_brk))
        await t.save()
        updated += 1
    return updated


async def list_closed_trade_events_fifo(
    user_id: str | PydanticObjectId,
    *,
    skip: int = 0,
    limit: int = 25,
) -> tuple[list[dict], int]:
    """FIFO per-opening-fill closed blotter.

    Unlike ``list_closed_trade_events`` (which uses a running weighted-avg),
    this function tracks a QUEUE of individual opening fills per instrument.
    When a closing trade fires, it is matched FIFO against the queue and
    produces ONE output row per (opening-fill × closing-fill) pairing.

    Example — user holds:
        Fill A: BUY 100 @ 4339.89
        Fill B: BUY 100 @ 4339.99
    User sells 150 qty → two rows:
        Row 1: 100 @ entry 4339.89 → close px
        Row 2:  50 @ entry 4339.99 → close px

    P&L per row = (close_price - entry_price) × qty  (for BUY positions).
    Brokerage is split proportionally across the sub-rows that a single
    closing trade produces.

    Returns (page_events, total_count) — newest-close-first, paginated.
    """
    from collections import deque
    from app.models.trade import Trade

    trades = await (
        Trade.find(Trade.user_id == PydanticObjectId(user_id))
        .sort("-executed_at")
        .limit(3000)
        .to_list()
    )
    trades.reverse()  # chronological for FIFO walk
    if not trades:
        return [], 0

    # Load this user's CLOSED Position docs ONCE — used to (a) interleave
    # WEEKLY_SETTLEMENT boundaries into the FIFO walk below and (b) enrich
    # the trade-derived events with close_reason. The Saturday mark-to-market
    # engine closes each open Position and re-opens an identical one at the
    # settlement price but writes NO Trade rows, so the FIFO walk can't see
    # those closes on its own.
    from datetime import datetime as _datetime
    from app.models.position import Position, PositionStatus

    closed_pos = await Position.find(
        Position.user_id == PydanticObjectId(user_id),
        Position.status == PositionStatus.CLOSED,
    ).to_list()

    def _naive(dt: Any) -> Any:
        return dt.replace(tzinfo=None) if dt else _datetime.min

    # One boundary per WEEKLY_SETTLEMENT close, to be merged into the walk.
    _settle_boundaries: list[dict] = []
    for _p in closed_pos:
        if _p.close_reason != "WEEKLY_SETTLEMENT" or not _p.closed_at:
            continue
        # quantity is left intact on a settlement close; fall back to
        # opening_quantity for any legacy/edited row that zeroed it.
        _sq = abs(float(_p.quantity or 0)) or abs(
            float(getattr(_p, "opening_quantity", 0) or 0)
        )
        if _sq <= 0:
            continue
        _sside = (
            _p.opened_side.value
            if getattr(_p, "opened_side", None) is not None
            else ("BUY" if float(_p.quantity or 0) >= 0 else "SELL")
        )
        _settle_boundaries.append({
            "ts": _p.closed_at,
            "key": (_p.instrument.token, _p.product_type.value),
            "entry_price": float(str(_p.avg_price)),  # this cycle's entry
            "settle_price": float(str(_p.ltp)),       # settlement LTP = new avg
            "qty": _sq,
            "side": _sside,
            "instrument": _p.instrument,
            "product_type": _p.product_type,
            "pid": _p.id,
        })

    def _charge(tr: Any) -> float:
        try:
            return float(
                str(getattr(tr, "total_charges", None) or getattr(tr, "brokerage", None) or 0)
            )
        except Exception:
            return 0.0

    # Per (token, product_type): deque of open fills (front = oldest = next to close).
    # Each fill: {"price": float, "qty": float, "opened_at": datetime, "side": "BUY"|"SELL"}
    open_queues: dict[tuple[str, str], deque] = {}
    events: list[dict] = []

    # Merge real trades with settlement boundaries into ONE chronological
    # stream. A weekly settlement = "close the whole position at the
    # settlement price, then re-open it there", so when the walk reaches one
    # we (1) emit its closed-blotter row and (2) reset that token's FIFO
    # basis to the settlement price. Without the reset, a later manual close
    # would pair against the now-stale ORIGINAL entry and report inflated,
    # double-counted P&L (the settlement row + an over-stated close row).
    # The (ts, kind-order, index) sort key avoids ever comparing the raw
    # Trade objects (which aren't orderable).
    _timeline: list[tuple] = []
    for _i, t in enumerate(trades):
        _timeline.append((_naive(t.executed_at), 0, _i, "trade", t))
    for _i, b in enumerate(_settle_boundaries):
        _timeline.append((_naive(b["ts"]), 1, _i, "settle", b))
    _timeline.sort(key=lambda x: (x[0], x[1], x[2]))

    for _ts, _ord, _idx, _kind, _obj in _timeline:
        if _kind == "settle":
            b = _obj
            sign = 1.0 if b["side"] == "BUY" else -1.0
            # Same gross formula the trade-FIFO path uses (no FX — closed
            # rows render P&L raw, matching the rest of this blotter).
            gross = (b["settle_price"] - b["entry_price"]) * b["qty"] * sign
            events.append({
                "_row_id": f"wsettle_{b['pid']}",
                "_closed_at": b["ts"],
                "_superseded": False,
                "instrument": b["instrument"],
                "product_type": b["product_type"],
                "opened_side": b["side"],
                "entry_price": b["entry_price"],
                "close_price": b["settle_price"],
                "qty": b["qty"],
                "gross_pnl": gross,
                "brokerage": 0.0,  # weekly settlement charges no brokerage
                "opened_at": b["ts"],
                "closed_at": b["ts"],
                "instrument_token": b["key"][0],
                "close_reason": "WEEKLY_SETTLEMENT",
            })
            # Reset the FIFO basis: the original opening fills are now closed
            # out by this settlement; the position carries on from the
            # settlement price. Clear the queue and reseed one fill there so
            # the next close prices off the settlement price.
            _sq = open_queues.setdefault(b["key"], deque())
            _sq.clear()
            _sq.append({
                "price": b["settle_price"],
                "qty": b["qty"],
                "opened_at": b["ts"],
                "side": b["side"],
                "open_brk": 0.0,
                "original_qty": b["qty"],
            })
            continue

        t = _obj
        key = (t.instrument.token, t.product_type.value)
        qty = abs(float(t.quantity))
        if qty <= 0:
            continue
        price = float(str(t.price))
        is_buy = t.action == OrderAction.BUY
        side_str = "BUY" if is_buy else "SELL"

        q = open_queues.setdefault(key, deque())

        # Cross-product-type fallback: admin force-closes sometimes record
        # the closing fill with a different product_type than the opening fill
        # (e.g. MIS open closed as NRML). The exact (token, product_type) queue
        # is empty, but another queue for the same token has the open position.
        # Only kick in when pnl_inr is set (definitive closing signal).
        if not q and t.pnl_inr is not None:
            alt_key = next(
                (k for k in open_queues if k[0] == t.instrument.token and open_queues[k]),
                None,
            )
            if alt_key:
                q = open_queues[alt_key]

        # Primary signal: pnl_inr set = closing fill; None = opening fill.
        # Fallback: if pnl_inr is None but queue has the OPPOSITE side,
        # treat as a closing fill whose pnl_inr the matching engine missed
        # (e.g. partial close recorded without pnl_inr due to an engine bug).
        queue_side = q[0]["side"] if q else None
        is_closing = t.pnl_inr is not None or (
            queue_side is not None and queue_side != side_str
        )

        if not is_closing:
            q.append({
                "price": price,
                "qty": qty,
                "opened_at": t.executed_at,
                "side": side_str,
                "open_brk": _charge(t),  # stored for pro-rata allocation on close
                "original_qty": qty,     # original fill qty for correct pro-rata on partial closes
            })
            continue

        # ── Closing fill: consume from queue ─────────────────────────────
        if not q:
            # Queue is empty — no opening fill to pair against. This is the
            # EXPECTED state after an admin REOPEN: reopen flips the position
            # back to OPEN reusing the original entry but writes NO new
            # opening Trade, so the earlier stop-out / square-off closes
            # already drained the FIFO queue. When the user then closes the
            # reopened position the closing fill lands here with an empty
            # queue. The old code `continue`d — silently dropping the
            # re-close — so a profitable reopen→close (operator: "wallet me
            # +profit aaya par history me nahi dikha") never appeared in the
            # Closed blotter even though the wallet booked it.
            #
            # Recover the entry price ALGEBRAICALLY from the trade itself —
            # no Position lookup needed and it's exact: the matching engine
            # stores pnl_inr = raw_gross - brokerage, and
            #   raw_gross = (close - entry) * qty   for a long  (closed by SELL)
            #   raw_gross = (entry - close) * qty   for a short (closed by BUY)
            # so `entry` falls straight out. price>0 guards the phantom
            # zero-priced fills the matching engine sometimes writes.
            if t.pnl_inr is not None and qty > 0 and price > 0:
                close_brk = _charge(t)
                gross = float(str(t.pnl_inr)) + close_brk  # back out brokerage → raw gross
                # The closing action is the OPPOSITE of the opening side.
                opened_side = "SELL" if is_buy else "BUY"
                if opened_side == "BUY":
                    entry_price = price - (gross / qty)
                else:
                    entry_price = price + (gross / qty)
                events.append({
                    "_row_id": f"fifo_{t.id}_0",
                    "_closed_at": t.executed_at,
                    "_superseded": getattr(t, "superseded_by_reopen", False),
                    "instrument": t.instrument,
                    "product_type": t.product_type,
                    "opened_side": opened_side,
                    "entry_price": entry_price,
                    "close_price": price,
                    "qty": qty,
                    "gross_pnl": gross,
                    "brokerage": close_brk,
                    # No surviving opening-fill timestamp for a reopened cycle
                    # — fall back to the close time so the row still renders.
                    "opened_at": t.executed_at,
                    "closed_at": t.executed_at,
                    "instrument_token": t.instrument.token,
                })
            continue

        close_brk = _charge(t)
        remaining = qty
        sub_idx = 0

        while remaining > 1e-9 and q:
            front = q[0]
            consume = min(front["qty"], remaining)

            # Gross P&L for this (opening-fill × closing-fill) pairing
            if front["side"] == "BUY":
                gross = (price - front["price"]) * consume   # long close
            else:
                gross = (front["price"] - price) * consume   # short close

            # Total brokerage = pro-rata open-leg + pro-rata close-leg
            orig_qty = front.get("original_qty") or consume
            open_brk_alloc = front.get("open_brk", 0.0) * (consume / orig_qty) if orig_qty > 0 else 0.0
            close_brk_alloc = close_brk * (consume / qty) if qty > 0 else 0.0
            brk_alloc = open_brk_alloc + close_brk_alloc

            events.append({
                "_row_id": f"fifo_{t.id}_{sub_idx}",
                "_closed_at": t.executed_at,
                "_superseded": getattr(t, "superseded_by_reopen", False),
                "instrument": t.instrument,
                "product_type": t.product_type,
                "opened_side": front["side"],
                "entry_price": front["price"],
                "close_price": price,
                "qty": consume,
                "gross_pnl": gross,
                "brokerage": brk_alloc,
                "opened_at": front["opened_at"],
                "closed_at": t.executed_at,
                "instrument_token": t.instrument.token,
            })

            front["qty"] -= consume
            remaining -= consume
            sub_idx += 1

            if front["qty"] < 1e-9:
                q.popleft()

    # Drop closing fills an admin REOPEN/DELETE later undid. They stay in the
    # collection (audit) and were processed above so the FIFO pairing of the
    # SURVIVING fills stayed correct (each undone close still consumed its
    # opening fill in order) — but they must not render, otherwise a
    # reopened-then-reclosed position shows every intermediate close instead
    # of just its final one. This makes the user Closed blotter match the
    # admin Position-doc view.
    events = [e for e in events if not e.get("_superseded")]

    # Enrich events with close_reason from Position documents so the user
    # panel can distinguish STOP_OUT / SL_HIT / TP_HIT from USER closes.
    # The FIFO loop only touches Trade records; close_reason lives on Position.
    # (Settlement events were already stamped WEEKLY_SETTLEMENT inline above;
    # the 30s match below leaves them untouched.)
    if events:
        # (token, product_type) → [(closed_at, close_reason), ...]
        _pos_map: dict[tuple, list] = {}
        for _p in closed_pos:
            _k = (_p.instrument.token, _p.product_type.value)
            if _p.closed_at:
                _pos_map.setdefault(_k, []).append((_p.closed_at, _p.close_reason or "USER"))
        for ev in events:
            if ev.get("close_reason"):
                continue  # already set (e.g. inline settlement rows)
            _k = (ev["instrument_token"], ev["product_type"].value)
            _entries = _pos_map.get(_k)
            if _entries:
                _cat = ev["closed_at"]
                _best = min(
                    _entries,
                    key=lambda x: abs((x[0].replace(tzinfo=None) - _cat.replace(tzinfo=None)).total_seconds()),
                )
                if abs((_best[0].replace(tzinfo=None) - _cat.replace(tzinfo=None)).total_seconds()) < 30:
                    ev["close_reason"] = _best[1]

    # Newest-close first. Sort explicitly because the list mixes trade-derived
    # events with inline settlement events that were emitted at their own
    # timestamps — the old `events.reverse()` only worked for a purely
    # chronological list.
    def _close_sort_key(e: dict) -> Any:
        c = e.get("_closed_at")
        return c.replace(tzinfo=None) if c else _datetime.min

    events.sort(key=_close_sort_key, reverse=True)
    total = len(events)
    return events[skip : skip + limit], total


async def refresh_unrealized_pnl(
    position: Position,
    ltp: Decimal,
    *,
    prefetched_quote: dict | None = None,
) -> Position:
    """Mark unrealised P&L against the CLOSE-side price.

    A long is closed by SELLING (hits the bid); a short by BUYING (hits the
    ask). So mark-to-market must use the bid for longs and the ask for
    shorts — the price the user would actually realise right now. The
    last-traded LTP can lag the live quote on thin contracts (MCX silver /
    crude) and overstate the move; that mismatch made a SILVERM long show
    🪙-11,621 (against a lagging LTP) when the live bid implied only 🪙-4,535
    (CL62329114 / PANKAJ).

    The quote is cached (700 ms TTL) and the caller's get_ltp fan-out
    already populated it this tick, so the extra get_quote is ~free. Falls
    back to `ltp` when the close side isn't published (illiquid / equity
    feeds with no depth).

    NOTE: there is NO USD→INR conversion. `is_usd_quoted_segment` returns
    False platform-wide (operator spec: Infoway prices are treated as INR
    directly), so the old `× usd_inr_rate` branch was already dead and is
    removed.

    ── Zero-mark guard ── A missing tick / stale cache / failed fetch can
    hand us `ltp == 0`. `(0 - avg) × qty` would then equal the WHOLE
    notional and the risk enforcer would read a colossal phantom drawdown
    (21-May COPPER incident, loss_pct 9124 %). On a non-positive mark we
    leave the last good values and let the next valid tick refresh them.
    """
    if ltp is None or to_decimal(ltp) <= 0:
        return position

    qty = to_decimal(position.quantity)
    mark = to_decimal(ltp)
    # Prefer the close-side price: bid for a long, ask for a short.
    # `prefetched_quote` lets the risk enforcer pass in the WS-state dict
    # directly (zero network), bypassing get_quote / _overlay_all / REST.
    try:
        if prefetched_quote is not None:
            q = prefetched_quote
        else:
            from app.services.market_data_service import get_quote
            q = await get_quote(position.instrument.token)
        side_raw = q.get("bid") if qty > 0 else q.get("ask")
        side = to_decimal(side_raw) if side_raw not in (None, 0, "0") else None
        if side is not None and side > 0:
            mark = side
    except Exception:
        pass

    # ── Banned security → FREEZE P&L at the ban-time price ─────────
    # A super-admin ban makes the position close-only and locks its mark at the
    # freeze price captured when the ban was applied, so its unrealized P&L
    # stops moving (+/- frozen) until the user closes it.
    try:
        from app.services import banned_security_service

        _fp = await banned_security_service.freeze_price_for_position(position)
        if _fp is not None:
            mark = _fp
    except Exception:  # noqa: BLE001 — freeze must never break the mark refresh
        pass

    position.ltp = Decimal128(str(mark))
    pnl = (mark - to_decimal(position.avg_price)) * qty
    position.unrealized_pnl = Decimal128(str(quantize_money(pnl)))
    return position


async def list_holdings(user_id: str | PydanticObjectId) -> list[Holding]:
    return await Holding.find(Holding.user_id == PydanticObjectId(user_id)).to_list()


# ── Intraday → carryforward auto-rollover ───────────────────────────
async def _charge_carry_forward(pos, s: dict) -> None:
    """Debit the segment's carry-forward charge — % of the position's notional —
    for holding it overnight. Called once per position per rollover (both a
    MIS→NRML conversion and an already-NRML carry). No-op when the % is 0."""
    import logging as _lg

    try:
        pct = float((s or {}).get("carry_forward_charge_percent") or 0.0)
    except (TypeError, ValueError):
        pct = 0.0
    if pct <= 0:
        return
    try:
        from app.models.transaction import TransactionType
        from app.services import wallet_router

        price = to_decimal(pos.ltp)
        if price <= ZERO:
            price = to_decimal(pos.avg_price)
        notional = abs(to_decimal(pos.quantity)) * price
        charge = quantize_money(notional * to_decimal(pct) / to_decimal(100))
        if charge <= ZERO:
            return
        await wallet_router.adjust(
            pos.user_id,
            pos.segment_type,
            -charge,
            transaction_type=TransactionType.ADJUSTMENT,
            narration=f"Carry-forward charge {pct:g}% · {pos.instrument.symbol}",
        )
        _lg.getLogger(__name__).info(
            "carry_forward_charged user=%s sym=%s pct=%s charge=%s",
            pos.user_id, pos.instrument.symbol, pct, charge,
        )
    except Exception:
        _lg.getLogger(__name__).exception(
            "carry_forward_charge_failed pos=%s", getattr(pos, "id", None)
        )


async def convert_intraday_to_carry(segment_set: frozenset[str] | set[str]) -> dict[str, int]:
    """At market close for a segment group, flip every open MIS position in
    that group to NRML. For each position we re-resolve the NRML margin
    against the user's effective segment settings; if the wallet can't
    afford the overnight delta, the position is force-squareoff'd before
    the type flip (so we never leave it in NRML while under-margined).

    Also sweeps already-open NRML positions in the group: any whose wallet
    can't cover the (correctly-resolved) carry margin is force-closed too.
    This catches carry positions that slipped through under-funded earlier
    (e.g. the option_type=None margin bug) and flattens them at the next EOD.
    Affordable NRML positions are left untouched.

    Returns a small summary dict for logging / audit:
        {"converted": N, "force_closed": M, "skipped": K}

    Used by the `intraday_to_carry_loop` lifespan task. The loop calls this
    once per IST day per segment group, right after the exchange's close
    minute.
    """
    from app.core.redis_client import cache_delete_pattern
    from app.models._base import ProductType as _PT
    from app.models.audit_log import AuditAction
    from app.services import (
        audit_service,
        netting_service,
        order_service,
        wallet_router,
        wallet_service,
    )
    from app.services.market_data_service import is_usd_quoted_segment

    if not segment_set:
        return {"converted": 0, "force_closed": 0, "skipped": 0}

    # Fetch BOTH MIS and NRML positions in this segment group. MIS rows
    # get the normal rollover treatment; NRML rows are only touched when
    # admin has set `allowOvernight=false` on the segment, in which case
    # we force-close them too (the segment-spec says nothing can carry
    # past close).
    rows = await Position.find(
        {
            "status": PositionStatus.OPEN.value,
            "product_type": {"$in": [_PT.MIS.value, _PT.NRML.value]},
            "instrument.segment": {"$in": list(segment_set)},
        }
    ).to_list()

    # Snapshot each affected user's settlement_outstanding BEFORE closing
    # anything, so the post-batch close-ordering correction nets only the
    # phantom this rollover books — not pre-existing / genuine shortfall.
    phantom_before: dict = {}
    for _uid in {p.user_id for p in rows}:
        try:
            _w0 = await wallet_service.get_or_create(_uid)
            phantom_before[_uid] = to_decimal(_w0.settlement_outstanding)
        except Exception:  # noqa: BLE001
            pass

    converted = 0
    force_closed = 0
    skipped = 0

    for pos in rows:
        # Resolve NRML-side margin via the same resolver that runs at
        # order-placement time. Single source of truth — admin's segment
        # override stack is honoured.
        try:
            # Derive CE/PE from the symbol (the Position's InstrumentRef
            # snapshot has no option_type field) so the resolver applies the
            # admin's per-side option overrides (e.g. Opt Sell Mode=Fixed,
            # Opt Sell Overnight=🪙15000) instead of silently falling back to
            # the generic segment Times/% margin. Without this the carry
            # margin is massively UNDER-computed (~20% of notional vs the
            # configured 🪙15000/lot), so `delta` looks affordable and an
            # under-funded option position is NEVER force-closed at EOD —
            # it rolls into NRML uncovered. Mirrors the positions endpoint.
            _osym = (pos.instrument.symbol or "").upper()
            _otype = (
                ("CE" if _osym.endswith("CE") else "PE" if _osym.endswith("PE") else None)
                if len(_osym) >= 3 and _osym[-3].isdigit()
                else None
            )
            resolved = await netting_service.get_effective_settings(
                pos.user_id,
                pos.instrument.segment,
                action="BUY" if pos.quantity >= 0 else "SELL",
                option_type=_otype,
                product_type="NRML",
                symbol=pos.instrument.symbol,
            )
        except Exception:  # noqa: BLE001
            skipped += 1
            continue
        s = resolved.get("settings") or {}

        # Hard close-out path: admin disabled overnight carrying for this
        # segment (`allowOvernight=false`). Nothing carries past close —
        # squareoff every open position regardless of product type. Runs
        # before the type-flip / margin-recompute below so we don't bother
        # locking new margin on a position we're about to close.
        allow_overnight = bool(s.get("selling_overnight", True))
        if not allow_overnight:
            from app.models._base import OrderAction as _OA, OrderType as _OT
            from app.models.user import User as _User

            try:
                user_doc = await _User.get(pos.user_id)
                if user_doc is None:
                    skipped += 1
                    continue
                qty_open = abs(pos.quantity)
                lots_open = max(0.01, qty_open / max(1, pos.instrument.lot_size or 1))
                action = _OA.SELL if pos.quantity > 0 else _OA.BUY
                await order_service.place_order(
                    user=user_doc,
                    payload={
                        "token": pos.instrument.token,
                        "action": action.value,
                        "order_type": _OT.MARKET.value,
                        "product_type": pos.product_type.value,
                        "lots": lots_open,
                        "force_quantity": qty_open,
                        "is_squareoff": True,
                        "placed_from": "OVERNIGHT_DISABLED_CLOSE",
                    },
                )
                # Stamp a specific close_reason so the user sees WHY the
                # position closed.  "EOD_OVERNIGHT_DISABLED" — segment
                # doesn't allow carry-forward at all (intraday-only
                # product).  More informative than the legacy "AUTO".
                try:
                    refreshed = await Position.get(pos.id)
                    if refreshed and refreshed.status == PositionStatus.CLOSED and not refreshed.close_reason:
                        refreshed.close_reason = "EOD_OVERNIGHT_DISABLED"
                        await refreshed.save()
                except Exception:  # noqa: BLE001
                    pass
                force_closed += 1
            except Exception:  # noqa: BLE001
                skipped += 1
            continue

        # `allowOvernight=true`: compute the overnight requirement for BOTH
        # MIS and already-open NRML positions. A MIS position converts to NRML
        # when affordable; ANY position (MIS or NRML) whose wallet can't cover
        # the carry is force-closed in the branch below. Extending the check to
        # NRML squares off under-funded carry positions that slipped through
        # earlier (e.g. the option_type=None margin bug let them roll in
        # uncovered) at the next EOD instead of leaving them stuck open. An
        # already-NRML position that IS affordable is left exactly as-is (no
        # type flip, no re-lock) — see the MIS-only gate before the flip.

        # Compute the overnight margin requirement against the same
        # notional that's currently locked. Mirrors order_validator's
        # fixed-mode vs percent-vs-times logic — BUT we read the
        # `overnight_*` triple, not the product-aware `leverage` /
        # `margin_percentage` / `fixed_margin_per_lot`. In Times mode the
        # resolver deliberately keeps those product-aware fields on the
        # INTRADAY value (the "symmetric-Times patch"), so reading them
        # here returned 500× for an MCX FUT row whose admin had set
        # 500× intraday / 70× overnight — and the loop computed
        # delta=0 and silently skipped force-close. Reading the
        # explicit overnight fields gives the rollover the right
        # requirement so a wallet that can't cover the carry actually
        # triggers the force-squareoff branch below.
        cur_avg = to_decimal(pos.avg_price)
        cur_qty_abs = to_decimal(abs(pos.quantity))
        notional = cur_avg * cur_qty_abs

        ovn_fixed_per_lot = to_decimal(s.get("overnight_fixed_margin_per_lot") or 0)
        if (s.get("margin_calc_mode") == "fixed") and ovn_fixed_per_lot > 0:
            lot_size = max(1, int(pos.instrument.lot_size or 1))
            lots = cur_qty_abs / to_decimal(lot_size)
            new_margin = ovn_fixed_per_lot * lots
        else:
            ovn_margin_pct = to_decimal(s.get("overnight_margin_percentage") or 100.0) / to_decimal(100)
            ovn_leverage = to_decimal(s.get("overnight_leverage") or 1.0) or to_decimal(1)
            new_margin = notional * ovn_margin_pct / ovn_leverage

        # USD-quoted instruments lock margin in INR; same conversion as
        # order_validator.validate. Skipped for fixed-per-lot (already INR).
        if (
            is_usd_quoted_segment(pos.segment_type)
            or is_usd_quoted_segment(pos.instrument.segment)
        ):
            if not ((s.get("margin_calc_mode") == "fixed") and ovn_fixed_per_lot > 0):
                from app.services.market_data_service import get_usd_inr_rate

                new_margin = new_margin * to_decimal(get_usd_inr_rate())

        new_margin = quantize_money(new_margin)
        old_margin = to_decimal(pos.margin_used)
        delta = new_margin - old_margin

        # Floating P&L is part of the carry buying power (operator: "1L free +
        # 20k profit → carry budget is 1.2L"). A profit makes more carriable; a
        # loss makes less. Marked off the LIVE close price. Reused by the partial
        # branch below so both the affordability gate and the carriable-qty math
        # count the same profit.
        _sign = to_decimal(1 if pos.quantity > 0 else -1)
        try:
            from app.services import market_data_service as _mds0

            _ltp_now = to_decimal(await _mds0.get_ltp(pos.instrument.token))
        except Exception:  # noqa: BLE001
            _ltp_now = to_decimal(0)
        # The carry runs at MARKET CLOSE — the exact moment the feed can be down,
        # so get_ltp returns 0. Fall back to the position's LAST stored mark
        # (`pos.ltp`, refreshed by the risk enforcer on every tick), NOT its avg
        # price: falling to avg made unreal = (avg−avg)×qty = 0, so the carry
        # IGNORED the P&L entirely ("software not considering the pnl"). avg is
        # only the last resort when even the stored mark is missing.
        if _ltp_now <= 0:
            _ltp_now = to_decimal(getattr(pos, "ltp", None) or 0)
        if _ltp_now <= 0:
            _ltp_now = cur_avg
        unreal = (_ltp_now - cur_avg) * cur_qty_abs * _sign
        # USD-quoted instruments (crypto / forex) quote price + P&L in USD, but
        # the wallet and `new_margin` above are INR — convert the P&L to INR too
        # (same rate as new_margin), else it's ~83× too small and the carry
        # budget effectively drops the profit/loss.
        if is_usd_quoted_segment(pos.segment_type) or is_usd_quoted_segment(pos.instrument.segment):
            from app.services.market_data_service import get_usd_inr_rate

            unreal = unreal * to_decimal(get_usd_inr_rate())

        wallet = await wallet_router.get(pos.user_id, pos.segment_type)
        affordable = (
            to_decimal(wallet.available_balance)
            + to_decimal(wallet.credit_limit)
            + unreal
        ) >= delta

        if delta > 0 and not affordable:
            # ── PARTIAL CARRY ────────────────────────────────────────────
            # Can't cover the overnight margin for the WHOLE position → carry
            # only as much as the wallet backs and square off ONLY the excess
            # (operator spec). Funds available to back the carry:
            #   free balance + THIS position's locked margin (frees as we
            #   reduce) + its mark-to-market PnL + credit_limit.
            # Overnight margin is LINEAR in quantity, so:
            #   carriable_qty = floor_to_lot( qty × funds ÷ full_carry_margin )
            # Floor to whole lots (safe — the carried part is always covered).
            # If it can't cover even 1 lot → square the WHOLE position.
            from app.models._base import OrderAction as _OA, OrderType as _OT
            from app.models.user import User as _User

            try:
                user_doc = await _User.get(pos.user_id)
                if user_doc is None:
                    skipped += 1
                    continue
                lot_size = max(1, int(pos.instrument.lot_size or 1))
                # `unreal` (live floating P&L) already computed above — the carry
                # budget is free balance + this position's freed MIS margin +
                # profit + credit; overnight margin is linear in qty.
                funds = (
                    to_decimal(wallet.available_balance)
                    + old_margin
                    + unreal
                    + to_decimal(wallet.credit_limit)
                )

                # Min tradeable lot STEP for this instrument — crypto/forex trade
                # fractional lots (min_lot 0.01); NSE/MCX = 1. Floor the carriable
                # amount to this step, NOT to whole lots. Flooring 0.55→0 (whole
                # lots) wrongly force-closed a crypto position that could carry
                # 0.55 lot — the "pura close ho gaya" bug. min_qty = smallest
                # carriable contracts (step × lot_size).
                step_lot = to_decimal(s.get("min_lot") or 1)
                if step_lot <= 0:
                    step_lot = to_decimal(1)
                min_qty = quantize_money(step_lot * to_decimal(lot_size))

                carriable_qty = to_decimal(0)
                if funds > 0 and new_margin > 0:
                    raw_lots = (cur_qty_abs * funds / new_margin) / to_decimal(lot_size)
                    steps = int(raw_lots / step_lot)  # floor to whole min-lot steps
                    carriable_qty = quantize_money(to_decimal(steps) * step_lot * to_decimal(lot_size))
                    if carriable_qty > cur_qty_abs:
                        carriable_qty = cur_qty_abs

                action = _OA.SELL if pos.quantity > 0 else _OA.BUY
                if carriable_qty < min_qty:
                    # Can't carry even the MINIMUM lot step → square the WHOLE.
                    square_qty = cur_qty_abs
                    close_reason = "CARRY_FORWARD_FAIL"
                    do_convert = False
                else:
                    square_qty = cur_qty_abs - carriable_qty
                    close_reason = "CARRY_FORWARD_PARTIAL"
                    do_convert = True

                # 1) Square the excess (or whole) at market.
                if square_qty > 0:
                    lots_sq = max(0.01, float(square_qty) / lot_size)
                    await order_service.place_order(
                        user=user_doc,
                        payload={
                            "token": pos.instrument.token,
                            "action": action.value,
                            "order_type": _OT.MARKET.value,
                            "product_type": pos.product_type.value,
                            "lots": lots_sq,
                            "force_quantity": float(square_qty),
                            "is_squareoff": True,
                            "placed_from": "INTRADAY_ROLLOVER",
                        },
                    )
                    # Stamp the close_reason ONLY if the position fully closed
                    # (whole-square case). On a partial reduce the position
                    # stays OPEN and rolls to NRML below.
                    try:
                        _closed = await Position.get(pos.id)
                        if _closed and _closed.status == PositionStatus.CLOSED and not _closed.close_reason:
                            _closed.close_reason = close_reason
                            await _closed.save()
                    except Exception:  # noqa: BLE001
                        pass
                    force_closed += 1

                # 2) Carry the REMAINING (now affordable) position → NRML.
                if do_convert:
                    refreshed = await Position.get(pos.id)
                    if (
                        refreshed
                        and refreshed.status == PositionStatus.OPEN
                        and refreshed.product_type == _PT.MIS
                    ):
                        red_qty_abs = to_decimal(abs(refreshed.quantity))
                        # Overnight margin scales linearly with qty.
                        red_new_margin = quantize_money(new_margin * red_qty_abs / cur_qty_abs)
                        red_old_margin = to_decimal(refreshed.margin_used)
                        red_delta = red_new_margin - red_old_margin
                        try:
                            if red_delta > 0:
                                await wallet_router.block_margin(
                                    refreshed.user_id, refreshed.segment_type, red_delta
                                )
                            elif red_delta < 0:
                                await wallet_router.release_margin(
                                    refreshed.user_id, refreshed.segment_type, -red_delta
                                )
                            refreshed.product_type = _PT.NRML
                            refreshed.margin_used = Decimal128(str(red_new_margin))
                            await refreshed.save()
                            await _recompute_tracker(
                                user_id=refreshed.user_id,
                                segment_type=refreshed.segment_type,
                                token=refreshed.instrument.token,
                            )
                            await _charge_carry_forward(refreshed, s)
                            converted += 1
                        except Exception:  # noqa: BLE001
                            skipped += 1
            except Exception:  # noqa: BLE001
                skipped += 1
            continue

        # This position IS carrying overnight (it passed the affordability
        # check above). Debit the segment's carry-forward charge (% of notional)
        # once — for BOTH a MIS→NRML conversion and an already-NRML carry.
        await _charge_carry_forward(pos, s)

        # Affordable + already NRML → nothing to do (it's already carrying
        # on overnight margin; we don't re-lock the affordable ones to avoid
        # surprise wallet changes). Only MIS positions convert to NRML.
        if pos.product_type != _PT.MIS:
            continue

        # Type flip + margin reconciliation.
        try:
            if delta > 0:
                await wallet_router.block_margin(pos.user_id, pos.segment_type, delta)
            elif delta < 0:
                await wallet_router.release_margin(pos.user_id, pos.segment_type, -delta)

            pos.product_type = _PT.NRML
            pos.margin_used = Decimal128(str(new_margin))
            await pos.save()

            # Tracker counters — same magnitude, different bucket.
            # Recompute (don't increment) — same drift-immunity reasoning as
            # apply_fill above. After product_type flips MIS→NRML on the
            # Position doc, _recompute_tracker reads the new state and
            # rewrites the (intraday_lots, holding_lots) split exactly.
            await _recompute_tracker(
                user_id=pos.user_id,
                segment_type=pos.segment_type,
                token=pos.instrument.token,
            )

            try:
                await audit_service.log_event(
                    action=AuditAction.UPDATE,
                    entity_type="Position",
                    entity_id=pos.id,
                    actor_id=None,
                    target_user_id=pos.user_id,
                    metadata={
                        "kind": "INTRADAY_TO_CARRY_CONVERSION",
                        "symbol": pos.instrument.symbol,
                        "old_margin": str(old_margin),
                        "new_margin": str(new_margin),
                        "delta": str(delta),
                    },
                )
            except Exception:  # noqa: BLE001
                pass

            converted += 1
        except Exception:  # noqa: BLE001
            skipped += 1

    # Per-user effective-settings cache no longer matches reality (the
    # product_type changed); wipe so the next read re-resolves.
    try:
        await cache_delete_pattern("netting_eff:*")
    except Exception:  # noqa: BLE001
        pass

    # Close-ordering correction: net any phantom settlement the force-close
    # branches above booked while a sibling position's margin was still
    # locked (same fix as the risk_enforcer stop-out path). Self-correcting
    # — no-op for users with no phantom; genuine capital-exhausted shortfall
    # is left intact. Only runs when something was actually force-closed.
    if force_closed and phantom_before:
        try:
            await wallet_service.net_phantom_settlement_for_users(phantom_before)
        except Exception:  # noqa: BLE001
            pass

    return {"converted": converted, "force_closed": force_closed, "skipped": skipped}


# Module-level kill switch + state — same pattern as risk_enforcer_loop.
_intraday_loop_stop = False
_last_rollover_day: dict[str, str] = {}


def stop_intraday_to_carry_loop() -> None:
    global _intraday_loop_stop
    _intraday_loop_stop = True


async def intraday_to_carry_loop(interval_sec: float = 60.0) -> None:
    """Wake every minute; at each segment group's close minute (once per
    IST day), run `convert_intraday_to_carry` against that group.

    Segment groups + close times come from time_utils:
        • Indian equity + F&O → 15:30 IST
        • MCX                 → 23:55 IST
        • Forex (CDS) + crypto → no close, skipped entirely

    Weekends are skipped (Indian exchanges are closed). The per-day
    bookkeeping `_last_rollover_day` ensures we only fire once per group
    even if the loop sleeps drift slightly past the close-minute mark.
    """
    import asyncio as _asyncio
    import logging as _logging

    from app.utils.time_utils import (
        INDIAN_EQUITY_FNO_SEGMENTS,
        MCX_SEGMENTS,
        is_weekend,
        market_close_time_for_segment,
        now_ist,
    )

    _log = _logging.getLogger(__name__)
    global _intraday_loop_stop
    _intraday_loop_stop = False

    groups = (
        ("INDIAN_EQUITY_FNO", INDIAN_EQUITY_FNO_SEGMENTS),
        ("MCX", MCX_SEGMENTS),
    )

    while not _intraday_loop_stop:
        try:
            now = now_ist()
            if not is_weekend(now.date()):
                day_key = now.strftime("%Y%m%d")
                for group_name, group_set in groups:
                    if _last_rollover_day.get(group_name) == day_key:
                        continue
                    close_t = market_close_time_for_segment(next(iter(group_set)))
                    if close_t is None:
                        continue
                    # Fire the minute after close — gives any straggler
                    # orders one tick to settle before we sweep.
                    fire_after = (close_t.hour, close_t.minute + 1)
                    if (now.hour, now.minute) >= fire_after:
                        summary = await convert_intraday_to_carry(group_set)
                        _last_rollover_day[group_name] = day_key
                        _log.info(
                            "intraday_to_carry_rolled",
                            extra={"group": group_name, **summary},
                        )
            # Crypto: 24×7 has NO calendar close, so its carry-forward fires at
            # the super-admin MARKET CONTROL close time (when set + enabled).
            # Runs all 7 days (crypto trades weekends). Same convert path as the
            # others: MIS→NRML carry, and force-close any position the wallet
            # can't carry (the operator's "no carry margin → auto close").
            try:
                from app.models.market_control import MarketControl
                from app.services import wallet_kinds
                from app.utils.time_utils import parse_hhmm as _parse_hhmm

                _ck = now.strftime("%Y%m%d")
                if _last_rollover_day.get("CRYPTO") != _ck:
                    _mc = await MarketControl.find_one(MarketControl.segment_name == "CRYPTO")
                    if _mc and _mc.enabled and _mc.close_time:
                        _cct = _parse_hhmm(_mc.close_time)
                        if (now.hour, now.minute) >= (_cct.hour, _cct.minute + 1):
                            _summary = await convert_intraday_to_carry(
                                set(wallet_kinds.segments_for_kind("CRYPTO"))
                            )
                            _last_rollover_day["CRYPTO"] = _ck
                            _log.info(
                                "intraday_to_carry_rolled",
                                extra={"group": "CRYPTO", **_summary},
                            )
            except Exception:  # noqa: BLE001
                _log.exception("crypto_carry_rollover_failed")
        except Exception:  # noqa: BLE001
            _log.exception("intraday_to_carry_loop_failed")
        try:
            await _asyncio.sleep(interval_sec)
        except _asyncio.CancelledError:
            return
