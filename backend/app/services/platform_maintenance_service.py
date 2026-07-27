"""Per-admin platform-maintenance sweeps (daily, leader-only).

Two independent, admin-configured behaviours — both default OFF, so this whole
module is a no-op until an admin turns one on (settings live on the admin's own
User doc: see `platform_charge_*` / `zero_balance_autoclose_enabled`):

  1. DAILY PLATFORM CHARGE — when an admin enables it and sets an amount, every
     ACTIVE end-user under that admin is debited `platform_charge_amount` from
     their MAIN wallet ONCE per IST day; the collected fee is credited to the
     owning admin's MAIN wallet. Idempotent per day via `last_platform_charge_day`
     (self-heals across restarts / multiple ticks). Users who can't cover the
     full fee are charged only what they have (never driven negative, never a
     settlement-outstanding debt) — a bare 🪙0 wallet is simply skipped.

  2. ZERO-BALANCE AUTO-CLOSE — when an admin enables it, any of that admin's
     users whose ENTIRE balance (main + every segment wallet) has sat at 🪙0 for
     ≥ 7 consecutive days, with no open positions, is SOFT-closed
     (status → CLOSED — recoverable, NOT hard-deleted). `zero_balance_since`
     records when 🪙0 was first observed and is cleared the instant any money
     returns, so the 7-day clock only runs while genuinely empty.

Wired into the FastAPI lifespan as a single leader-only loop
(`platform_maintenance_loop`, ~30 min) so exactly one worker runs it.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from decimal import Decimal

from beanie import PydanticObjectId

from app.models.position import Position, PositionStatus
from app.models.transaction import TransactionType
from app.models.user import User, UserRole, UserStatus
from app.services import segment_wallet_service, wallet_service
from app.utils.decimal_utils import to_decimal
from app.utils.time_utils import now_ist, now_utc

logger = logging.getLogger(__name__)

ZERO = Decimal("0")
_ZERO_BALANCE_CLOSE_DAYS = 7

# End-user roles a per-admin sweep applies to (never other admins/brokers).
_END_USER_ROLES = [UserRole.CLIENT, UserRole.DEALER, UserRole.MASTER]


async def _admin_end_users(admin_id: PydanticObjectId) -> list[User]:
    return await User.find(
        User.assigned_admin_id == admin_id,
        {"role": {"$in": [r.value for r in _END_USER_ROLES]}},
        User.status == UserStatus.ACTIVE,
    ).to_list()


async def _total_balance(user_id: PydanticObjectId) -> Decimal:
    """Whole-account cash across MAIN + every segment wallet (available +
    locked margin). Used by the zero-balance check so an account with money
    tied up in a position is NOT treated as empty."""
    total = ZERO
    try:
        for w in await segment_wallet_service.list_all(user_id):
            total += to_decimal(w.get("available_balance") or 0)
            total += to_decimal(w.get("used_margin") or 0)
    except Exception:
        logger.exception("platform_total_balance_failed user=%s", user_id)
        # On error, return a positive sentinel so we NEVER wrongly close an
        # account we couldn't fully price.
        return Decimal("1")
    return total


# ── 1. Daily per-user platform charge ────────────────────────────────────
async def run_platform_charge_sweep() -> int:
    """Charge every eligible admin's users their daily platform fee (once/day).
    Returns the number of users charged this sweep."""
    # The enabled flag lives only on admin-tier docs (set via the admin API),
    # so the flag itself is the gate — no role filter needed.
    admins = await User.find(
        User.platform_charge_enabled == True,  # noqa: E712
    ).to_list()
    if not admins:
        return 0

    # Recipient of the collected charge. Default: the owning admin (legacy).
    # When the admin-book model is ON, the super-admin holds the money — so the
    # platform charge is credited to the SA instead of the admin (operator spec:
    # "platform fees super-admin ke wallet me jaaye, admin me nahi"). Resolved
    # once per sweep. Falls back to the owning admin if the SA can't be resolved.
    to_sa = False
    sa_id = None
    try:
        from app.services.admin_book_service import is_admin_book_enabled

        if await is_admin_book_enabled():
            from app.services import netting_service

            sa_id = await netting_service._resolve_super_admin_id()
            to_sa = sa_id is not None
    except Exception:
        to_sa = False

    today = now_ist().strftime("%Y-%m-%d")
    charged = 0
    for admin in admins:
        fee = to_decimal(admin.platform_charge_amount)
        if fee <= ZERO:
            continue
        users = await _admin_end_users(admin.id)
        for u in users:
            if u.last_platform_charge_day == today:
                continue  # already charged today
            try:
                mw = await wallet_service.get_or_create(u.id)
                avail = to_decimal(mw.available_balance)
                take = fee if avail >= fee else avail  # never negative, no debt
                if take > ZERO:
                    await wallet_service.adjust(
                        u.id, -take,
                        transaction_type=TransactionType.PLATFORM_CHARGE,
                        narration=f"Daily platform charge (admin {admin.user_code})",
                        reference_type="PLATFORM_CHARGE",
                        reference_id=str(admin.id),
                        actor_id=admin.id,
                    )
                    _recipient = sa_id if to_sa else admin.id
                    _recv_note = (
                        f"Platform charge collected from {u.user_code} (admin {admin.user_code})"
                        if to_sa
                        else f"Platform charge collected from {u.user_code}"
                    )
                    await wallet_service.adjust(
                        _recipient, take,
                        transaction_type=TransactionType.PLATFORM_CHARGE,
                        narration=_recv_note,
                        reference_type="PLATFORM_CHARGE",
                        reference_id=str(u.id),
                        actor_id=admin.id,
                    )
                    charged += 1
                # Stamp the day even on a 🪙0 take so a broke user isn't
                # re-probed every tick; next day it retries.
                await User.get_motor_collection().update_one(
                    {"_id": u.id}, {"$set": {"last_platform_charge_day": today, "updated_at": now_utc()}}
                )
            except Exception:
                logger.exception(
                    "platform_charge_user_failed admin=%s user=%s", admin.user_code, u.user_code
                )
    if charged:
        logger.info("platform_charge_sweep_done charged=%d", charged)
    return charged


# ── 2. Zero-balance 7-day auto-close ──────────────────────────────────────
async def run_zero_balance_autoclose_sweep() -> int:
    """Maintain each eligible admin's users' zero-balance clock and soft-close
    those empty for ≥ 7 days. Returns the number of accounts closed."""
    admins = await User.find(
        User.zero_balance_autoclose_enabled == True,  # noqa: E712
    ).to_list()
    if not admins:
        return 0

    now = now_utc()
    closed = 0
    for admin in admins:
        users = await _admin_end_users(admin.id)
        for u in users:
            try:
                total = await _total_balance(u.id)
                if total > ZERO:
                    # Has money → reset the clock if it was running.
                    if u.zero_balance_since is not None:
                        await User.get_motor_collection().update_one(
                            {"_id": u.id}, {"$set": {"zero_balance_since": None, "updated_at": now}}
                        )
                    continue
                # Zero balance. Don't close an account still holding a position.
                open_pos = await Position.find(
                    Position.user_id == u.id, Position.status == PositionStatus.OPEN
                ).count()
                if open_pos > 0:
                    continue
                since = u.zero_balance_since
                if since is None:
                    await User.get_motor_collection().update_one(
                        {"_id": u.id}, {"$set": {"zero_balance_since": now, "updated_at": now}}
                    )
                    continue
                # tz-safe age
                since_aware = since if since.tzinfo else since.replace(tzinfo=now.tzinfo)
                if now - since_aware >= timedelta(days=_ZERO_BALANCE_CLOSE_DAYS):
                    await User.get_motor_collection().update_one(
                        {"_id": u.id},
                        {"$set": {"status": UserStatus.CLOSED.value, "updated_at": now}},
                    )
                    closed += 1
                    logger.info(
                        "zero_balance_autoclosed user=%s admin=%s since=%s",
                        u.user_code, admin.user_code, since_aware.isoformat(),
                    )
            except Exception:
                logger.exception(
                    "zero_balance_autoclose_user_failed admin=%s user=%s",
                    admin.user_code, u.user_code,
                )
    if closed:
        logger.info("zero_balance_autoclose_sweep_done closed=%d", closed)
    return closed


# ── Background loop ───────────────────────────────────────────────────────
_stop = False


async def platform_maintenance_loop(interval_sec: float = 1800.0) -> None:
    """Leader-only loop (default 30 min). Runs both sweeps each tick; both are
    idempotent per IST day / self-healing, so the exact cadence isn't critical —
    it only needs to fire at least once after each midnight rollover."""
    global _stop
    _stop = False
    logger.info("platform_maintenance_loop_started", extra={"interval_sec": interval_sec})
    while not _stop:
        try:
            await run_platform_charge_sweep()
            await run_zero_balance_autoclose_sweep()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("platform_maintenance_tick_failed")
        for _ in range(int(interval_sec)):
            if _stop:
                break
            await asyncio.sleep(1)
    logger.info("platform_maintenance_loop_stopped")


def stop_platform_maintenance() -> None:
    global _stop
    _stop = True
