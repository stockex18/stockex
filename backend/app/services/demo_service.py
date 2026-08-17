"""Shared demo account lifecycle.

The login page's "Try Demo" logs every visitor into ONE shared demo account
(see `auth_service.create_demo_session` / `GLOBAL_DEMO_EMAIL`) instead of
minting a throwaway per click. That single account accumulates everyone's
trades, so it must be flattened and re-funded on a schedule — otherwise its
open positions never close and the books drift. `reset_global_demo` does that
full wipe + 🪙10L restore; `main.py` calls it every 24h via `demo_reset_loop`.
"""

from __future__ import annotations

import logging

from decimal import Decimal

from bson import Decimal128

from app.core.exceptions import AppError
from app.models.order import Order
from app.models.position import Position
from app.models.trade import Trade
from app.models.transaction import TransactionStatus, TransactionType, WalletTransaction
from app.models.user import User, UserRole
from app.services import wallet_service
from app.utils.time_utils import now_utc

logger = logging.getLogger(__name__)

# 10 lakh virtual coins. The marketing site advertises this figure on the
# demo-account section, so the two must move together.
_DEMO_FUND = Decimal128("1000000")
_ZERO = Decimal128("0")


async def reset_global_demo() -> dict:
    """Flatten the shared demo account and restore its 🪙10L virtual balance.

    Idempotent — safe to call repeatedly. Returns a small summary dict (used
    by the scheduler log and the admin manual-trigger, if any). No-op when the
    demo account hasn't been provisioned yet (nobody has clicked Try Demo).
    """
    from app.services.auth_service import GLOBAL_DEMO_EMAIL

    user = await User.find_one(User.email == GLOBAL_DEMO_EMAIL)
    if user is None:
        return {"reset": False, "reason": "global demo not provisioned yet"}

    uid = user.id

    # Full wipe — it's a demo, a clean slate every cycle keeps the account
    # light (the whole point: open demo trades were never closing and piling
    # up). Order matters little since these are independent collections.
    pos_res = await Position.find(Position.user_id == uid).delete()
    ord_res = await Order.find(Order.user_id == uid).delete()
    trd_res = await Trade.find(Trade.user_id == uid).delete()
    await WalletTransaction.find(WalletTransaction.user_id == uid).delete()

    # Restore the virtual balance: flat 🪙10L, no blocked margin, no shortfall.
    wallet = await wallet_service.get_or_create(uid)
    wallet.available_balance = _DEMO_FUND
    wallet.used_margin = _ZERO
    wallet.settlement_outstanding = _ZERO
    wallet.version = (wallet.version or 0) + 1
    await wallet.save()

    # One clean ledger row so the wallet history shows the daily credit.
    await WalletTransaction(
        user_id=uid,
        transaction_type=TransactionType.BONUS,
        amount=_DEMO_FUND,
        balance_before=_ZERO,
        balance_after=_DEMO_FUND,
        narration="Demo daily reset — 🪙10,00,000 virtual balance restored",
        status=TransactionStatus.COMPLETED,
    ).insert()

    summary = {
        "reset": True,
        "positions_cleared": getattr(pos_res, "deleted_count", None),
        "orders_cleared": getattr(ord_res, "deleted_count", None),
        "trades_cleared": getattr(trd_res, "deleted_count", None),
    }
    logger.info("demo_global_reset_done", extra=summary)
    return summary


async def convert_demo_to_real(user: User) -> dict:
    """Convert a PERSONAL demo account into a fresh REAL account.

    Wipes every demo artefact — positions, orders, trades, holdings, settlements,
    watchlists, per-segment wallets, wallet ledger, and all games data — and
    zeroes the main wallet, then flips the account to LIVE. The login
    credentials, broker and hierarchy are KEPT, so the user continues as a real
    client with a ZERO balance (must deposit to trade). Safe to re-run.
    """
    if not getattr(user, "is_demo", False):
        return {"converted": False, "reason": "not a demo account"}

    uid = user.id

    # 1) Wipe trading artefacts (same delete-by-user_id pattern as the demo reset).
    from app.models.holding import Holding
    from app.models.position_settlement import PositionSettlement
    from app.models.watchlist import Watchlist

    await Position.find(Position.user_id == uid).delete()
    await Order.find(Order.user_id == uid).delete()
    await Trade.find(Trade.user_id == uid).delete()
    await WalletTransaction.find(WalletTransaction.user_id == uid).delete()
    for _M in (Holding, PositionSettlement, Watchlist):
        try:
            await _M.find(_M.user_id == uid).delete()
        except Exception:  # noqa: BLE001
            logger.debug("convert_demo_wipe_failed model=%s", _M.__name__, exc_info=True)

    # 2) Per-segment wallets — drop entirely; real trading re-creates them at 0.
    try:
        from app.models.segment_wallet import SegmentWallet

        await SegmentWallet.find(SegmentWallet.user_id == uid).delete()
    except Exception:  # noqa: BLE001
        logger.debug("convert_demo_segwallet_wipe_failed", exc_info=True)

    # 3) Games — wipe every bet + zero the (separate) games wallet.
    try:
        from app.models.games.bets import BracketTrade, JackpotBid, NumberBet, UpDownBet
        from app.models.games.wallet import GamesWallet, GamesWalletLedger

        for _M in (NumberBet, BracketTrade, JackpotBid, UpDownBet, GamesWalletLedger):
            try:
                await _M.find(_M.user_id == uid).delete()
            except Exception:  # noqa: BLE001
                logger.debug("convert_demo_game_wipe_failed model=%s", _M.__name__, exc_info=True)
        gw = await GamesWallet.find_one(GamesWallet.user_id == uid)
        if gw is not None:
            gw.balance = _ZERO
            gw.version = (getattr(gw, "version", 0) or 0) + 1
            await gw.save()
    except Exception:  # noqa: BLE001
        logger.debug("convert_demo_games_wipe_failed", exc_info=True)

    # 4) Zero the main wallet — a real account starts empty (must deposit).
    wallet = await wallet_service.get_or_create(uid)
    wallet.available_balance = _ZERO
    wallet.used_margin = _ZERO
    wallet.settlement_outstanding = _ZERO
    if hasattr(wallet, "temporary_balance"):
        wallet.temporary_balance = _ZERO
    wallet.version = (wallet.version or 0) + 1
    await wallet.save()

    # 5) Flip to a real LIVE account (login + broker + hierarchy unchanged).
    from app.models.user import AccountType

    user.is_demo = False
    user.account_type = AccountType.LIVE
    user.demo_converted_at = now_utc()
    await user.save()

    logger.info("demo_converted_to_real user=%s", uid)
    return {"converted": True}


# ── Demo BROKER lifecycle ────────────────────────────────────────────
# A public "broker demo" signup mints a real BROKER row flagged is_demo, seeded
# with 50 lakh virtual float, dropped into the platform pool (under the super-
# admin). It gets the full broker dashboard EXCEPT the ability to create users
# (users perm stays VIEW → the create endpoint 403s, the UI pops "switch to
# real"). On convert the wallet is zeroed and users is unlocked to EDIT.
_DEMO_BROKER_FUND = 5_000_000  # 🪙50,00,000 virtual


def _demo_broker_permissions():
    """Restricted broker permission set for a demo broker: sees everything, can
    set its own bank + play with settings, but CANNOT create users (VIEW only,
    while the create endpoint needs EDIT)."""
    from app.models._base import PermissionLevel as P
    from app.models.user import BrokerPermissions

    return BrokerPermissions(
        users=P.VIEW,  # see the Users section; CREATE blocked (needs EDIT) → popup
        kyc=P.VIEW,
        deposits=P.VIEW,
        withdrawals=P.VIEW,
        ledger=P.VIEW,
        reports=P.VIEW,
        trading_view=P.VIEW,
        brokerage=P.VIEW,
        sub_brokers=P.VIEW,
        banks=P.EDIT,  # can set up their own bank
        segment_settings=P.EDIT,
        risk=P.EDIT,
        netting=P.EDIT,
    )


def _real_broker_permissions():
    """Full broker permission set granted on convert — unlocks user creation."""
    from app.models._base import PermissionLevel as P
    from app.models.user import BrokerPermissions

    return BrokerPermissions(
        users=P.EDIT,
        kyc=P.EDIT,
        deposits=P.EDIT,
        withdrawals=P.EDIT,
        ledger=P.EDIT,
        reports=P.EDIT,
        trading_view=P.EDIT,
        brokerage=P.EDIT,
        sub_brokers=P.EDIT,
        banks=P.EDIT,
        segment_settings=P.EDIT,
        risk=P.EDIT,
        netting=P.EDIT,
    )


async def create_demo_broker(*, email: str, mobile: str, password: str, full_name: str) -> User:
    """Provision a personal DEMO BROKER (platform pool, under the super-admin),
    pre-funded with 50 lakh virtual float. Restricted perms (no user-create).
    Returns the new broker; the caller mints the admin token pair."""
    from app.models.user import AccountType
    from app.services import broker_management_service

    sa = await User.find_one(User.role == UserRole.SUPER_ADMIN)
    if sa is None:
        raise AppError("Broker demo signup is unavailable — no super-admin configured.")

    broker = await broker_management_service.create_broker(
        creator=sa,
        email=email,
        mobile=mobile,
        password=password,
        full_name=full_name,
        permissions=_demo_broker_permissions(),
        pnl_share_pct=Decimal("0"),
    )
    broker.is_demo = True
    broker.account_type = AccountType.DEMO
    await broker.save()
    await wallet_service.adjust(
        broker.id,
        _DEMO_BROKER_FUND,
        transaction_type=TransactionType.BONUS,
        narration="Demo broker virtual credit",
    )
    logger.info("demo_broker_created broker=%s", broker.id)
    return broker


async def convert_demo_broker_to_real(broker: User) -> dict:
    """Convert a personal DEMO BROKER into a real broker: zero the (virtual)
    wallet, wipe its ledger, unlock full permissions (user-create), flip to
    LIVE. Login + hierarchy (platform pool, under the super-admin) are kept, so
    it carries on as a real broker with a ₹0 float — funded later by the admin."""
    if not getattr(broker, "is_demo", False) or broker.role != UserRole.BROKER:
        return {"converted": False, "reason": "not a demo broker"}

    from app.models.user import AccountType

    uid = broker.id
    wallet = await wallet_service.get_or_create(uid)
    wallet.available_balance = _ZERO
    wallet.used_margin = _ZERO
    wallet.settlement_outstanding = _ZERO
    if hasattr(wallet, "temporary_balance"):
        wallet.temporary_balance = _ZERO
    wallet.version = (wallet.version or 0) + 1
    await wallet.save()
    await WalletTransaction.find(WalletTransaction.user_id == uid).delete()

    broker.is_demo = False
    broker.account_type = AccountType.LIVE
    broker.demo_converted_at = now_utc()
    broker.broker_permissions = _real_broker_permissions()
    await broker.save()
    logger.info("demo_broker_converted_to_real broker=%s", uid)
    return {"converted": True}


async def demo_reset_loop(*, interval_sec: float = 3600.0) -> None:
    """Reset the shared demo every 24h.

    Polls hourly (the supervisor/leader wrapper in main.py owns the lifecycle)
    and fires `reset_global_demo` only once a full day has elapsed since the
    last reset. The "last reset" timestamp lives in Redis, so the 24h cadence
    survives process restarts/redeploys instead of restarting from boot. On
    the very first run (no timestamp yet) it resets immediately, then settles
    into the daily rhythm.
    """
    import asyncio
    import time

    from app.core.redis_client import cache_get, cache_set

    _KEY = "demo:last_reset_ts"
    _DAY = 24 * 3600

    while True:
        try:
            rec = await cache_get(_KEY)
            last = float(rec.get("ts")) if rec and rec.get("ts") else 0.0
            if time.time() - last >= _DAY:
                await reset_global_demo()
                # Re-read now() AFTER the reset so a long wipe doesn't shorten
                # the next cycle. TTL is 2 days so a stalled cluster re-fires.
                await cache_set(_KEY, {"ts": time.time()}, ttl_sec=_DAY * 2)
        except Exception:
            logger.exception("demo_reset_loop_iteration_failed")
        await asyncio.sleep(interval_sec)
