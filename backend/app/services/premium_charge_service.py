"""Overnight PREMIUM charge on carried positions — crypto only for now.

A position that is still open at the segment's premium time (`premiumTime`,
IST) and was opened before that moment pays the premium once for that day. It
is NOT brokerage: the super admin sets it in Segment Settings → Premium, per
segment (with per-admin / script / user overrides), so it covers every
instrument in the segment:

  • premiumType    "percentage" → % of the position's value (USD-quoted
                   contracts converted to ₹ at the live USD/INR rate)
                   "fixed"      → ₹ per unit held
  • premiumCharge  the % or the ₹ amount (0 = off)
  • premiumOn      "buy" (long positions) / "sell" (short) / "both"
  • premiumTime    the daily cut-off, HH:MM IST

The user's trading wallet is debited (PREMIUM_CHARGE, same flooring as
brokerage) and the super admin's wallet is credited the same amount. Demo
accounts pay it from their demo balance; practice money is never credited.

Runs as one leader-only loop (every minute). Idempotent per position per IST
day via `Position.last_premium_charge_day`, claimed before any money moves, so
a restart or a second worker can only skip a charge, never take it twice.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from app.models.position import Position, PositionStatus
from app.models.transaction import TransactionType
from app.utils.decimal_utils import quantize_money, to_decimal
from app.utils.time_utils import IST, now_ist, now_utc, parse_hhmm

logger = logging.getLogger(__name__)

ZERO = Decimal("0")

#: Wallet kinds the premium applies to. Forex / others can join later.
PREMIUM_KINDS: tuple[str, ...] = ("CRYPTO",)

_stop = False


def premium_amount(
    *, quantity: Any, price: Any, settings: dict, fx: Any = 1
) -> Decimal:
    """The day's premium for one position, in ₹. 0 when it doesn't apply.

    `quantity` is signed (long > 0, short < 0); `price` is the mark in the
    contract's own currency and `fx` converts it to ₹ (1 for ₹ contracts).
    """
    qty = to_decimal(quantity)
    value = to_decimal(settings.get("premium_charge") or 0)
    if qty == ZERO or value <= ZERO:
        return ZERO
    on = str(settings.get("premium_on") or "both").lower()
    if (on == "buy" and qty < 0) or (on == "sell" and qty > 0):
        return ZERO
    units = abs(qty)
    if str(settings.get("premium_type") or "percentage").lower() == "percentage":
        notional = units * to_decimal(price) * to_decimal(fx)
        return quantize_money(notional * value / Decimal(100))
    return quantize_money(units * value)  # fixed ₹ per unit


def cutoff_today(premium_time: str | None, now: datetime) -> datetime | None:
    """Today's premium moment (IST), or None if `premium_time` is unreadable."""
    try:
        t = parse_hhmm(premium_time or "22:30")
    except (ValueError, TypeError):
        return None
    return datetime.combine(now.date(), t, tzinfo=IST)


def is_due(opened_at: datetime | None, cutoff: datetime, now: datetime) -> bool:
    """Charge today only once the cut-off has passed, and only a position that
    was already open at the cut-off (opened earlier the same day counts)."""
    if now < cutoff or opened_at is None:
        return False
    opened = opened_at if opened_at.tzinfo else opened_at.replace(tzinfo=UTC)
    return opened < cutoff


async def _segments() -> list[str]:
    from app.services import wallet_kinds

    out: list[str] = []
    for kind in PREMIUM_KINDS:
        out.extend(wallet_kinds.segments_for_kind(kind))
    return out


async def charge_position(pos: Position, now: datetime, sa_id) -> Decimal:
    """Charge one position if today's premium is due. Returns what was charged."""
    from app.models.user import User
    from app.services import market_data_service, netting_service, wallet_router, wallet_service
    from app.services.position_service import _opt_type_of

    resolved = await netting_service.get_effective_settings(
        pos.user_id,
        pos.instrument.segment,
        action="BUY" if pos.quantity >= 0 else "SELL",
        option_type=_opt_type_of(pos.instrument.symbol),
        product_type=getattr(pos.product_type, "value", pos.product_type),
        symbol=pos.instrument.symbol,
    )
    s = resolved.get("settings") or {}
    if to_decimal(s.get("premium_charge") or 0) <= ZERO:
        return ZERO
    cutoff = cutoff_today(s.get("premium_time"), now)
    if cutoff is None or not is_due(pos.opened_at or pos.created_at, cutoff, now):
        return ZERO

    price = to_decimal(pos.ltp)
    if price <= ZERO:
        price = to_decimal(pos.avg_price)
    fx: Any = 1
    if market_data_service.is_usd_quoted_segment(pos.instrument.segment):
        fx = market_data_service.get_usd_inr_rate()
    amount = premium_amount(quantity=pos.quantity, price=price, settings=s, fx=fx)
    if amount <= ZERO:
        return ZERO

    # Claim the day BEFORE moving money (see module docstring).
    today = now.strftime("%Y-%m-%d")
    claim = await Position.get_motor_collection().update_one(
        {
            "_id": pos.id,
            "status": PositionStatus.OPEN.value,
            "last_premium_charge_day": {"$ne": today},
        },
        {"$set": {"last_premium_charge_day": today, "updated_at": now_utc()}},
    )
    if claim.modified_count != 1:
        return ZERO

    kind = str(s.get("premium_type") or "percentage").lower()
    rate = f"{s.get('premium_charge'):g}%" if kind == "percentage" else f"₹{s.get('premium_charge'):g}/unit"
    side = "BUY" if pos.quantity > 0 else "SELL"
    await wallet_router.adjust(
        pos.user_id,
        pos.instrument.segment,
        -amount,
        transaction_type=TransactionType.PREMIUM_CHARGE,
        narration=f"Overnight premium {rate} · {side} {pos.instrument.symbol} x{abs(pos.quantity):g}",
        reference_type="POSITION",
        reference_id=str(pos.id),
    )
    user = await User.get(pos.user_id)
    if sa_id is not None and not pos.is_demo and not getattr(user, "is_demo", False):
        await wallet_service.adjust(
            sa_id,
            amount,
            transaction_type=TransactionType.PREMIUM_CHARGE,
            narration=(
                f"Overnight premium from {getattr(user, 'user_code', pos.user_id)}"
                f" · {pos.instrument.symbol}"
            ),
            reference_type="POSITION",
            reference_id=str(pos.id),
        )
    logger.info(
        "premium_charged",
        extra={"position_id": str(pos.id), "symbol": pos.instrument.symbol, "amount": str(amount)},
    )
    return amount


async def run_premium_sweep(now: datetime | None = None) -> int:
    """One pass over every open position in the premium segments. Returns how
    many were charged."""
    from app.services import netting_service

    now = now or now_ist()
    segs = await _segments()
    if not segs:
        return 0
    rows = await Position.find(
        {
            "status": PositionStatus.OPEN.value,
            "quantity": {"$ne": 0},
            "instrument.segment": {"$in": segs},
            "last_premium_charge_day": {"$ne": now.strftime("%Y-%m-%d")},
        }
    ).to_list()
    if not rows:
        return 0
    sa_id = await netting_service._resolve_super_admin_id()
    charged = 0
    for pos in rows:
        try:
            if await charge_position(pos, now, sa_id) > ZERO:
                charged += 1
        except Exception:  # noqa: BLE001 — one bad row must not stop the sweep
            logger.exception("premium_charge_failed", extra={"position_id": str(pos.id)})
    return charged


async def premium_charge_loop(interval_sec: float = 60.0) -> None:
    """Leader-only loop: sweep every `interval_sec`."""
    global _stop
    _stop = False
    logger.info("premium_charge_loop_started", extra={"interval_sec": interval_sec})
    while not _stop:
        try:
            n = await run_premium_sweep()
            if n:
                logger.info("premium_charge_sweep", extra={"charged": n})
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            logger.exception("premium_charge_tick_failed")
        for _ in range(int(interval_sec)):
            if _stop:
                break
            await asyncio.sleep(1)
    logger.info("premium_charge_loop_stopped")


def stop_premium_charge_loop() -> None:
    global _stop
    _stop = True
