"""Admin-book model — per-trade real-money SA↔admin settlement.

FLAG-GATED (SA platform setting `admin_book_enabled`, default OFF → zero
behaviour change). When ON, on every CLOSING trade leg:

  1. The user's house result (−realized PnL) AND the brokerage the user paid are
     booked to the user's OWNING ADMIN's MAIN wallet — the admin is the trade
     counterparty (their float IS the book capital). User loss → admin credited;
     user profit → admin debited (admin funds the win).
  2. The SUPER-ADMIN then skims its configured share from the admin:
       • PnL share      = admin.pnl_share_pct%          (signed — SA earns on a
         user loss, pays on a user profit)
       • Brokerage share = admin.admin_brokerage_share_pct% (≥ 0, always to SA)

Net: user loss 100, brokerage 5, SA share 20% →
  admin +100 +5 −20 −5 = +80,  SA +20 +5 = +25,  user −105.

Scope (Phase 1): the SA↔admin layer only. Any admin↔broker split is a separate
layer (existing pnl_sharing agreements) and is NOT handled here yet. Every move
is a real `wallet_service.adjust`, and a single idempotent `AdminBookEntry` per
trade records the exact split for the SA earnings report.

Best-effort: a failure here must NEVER break a trade close (caller wraps too).
Idempotent: the unique `trade_id` on `AdminBookEntry` is claimed FIRST, so a
re-entrant tick can't double-book.
"""

from __future__ import annotations

import logging

from beanie import PydanticObjectId
from bson import Decimal128

from app.models.transaction import TransactionType
from app.models.user import User
from app.utils.decimal_utils import ZERO, quantize_money, to_decimal
from app.utils.time_utils import now_utc

logger = logging.getLogger(__name__)

ADMIN_BOOK_ENABLED_KEY = "admin_book_enabled"


async def is_admin_book_enabled() -> bool:
    """Is the admin-book per-trade model ON? Live DB toggle (default OFF)."""
    from app.models.platform_setting import PlatformSetting

    row = await PlatformSetting.find_one(
        PlatformSetting.setting_key == ADMIN_BOOK_ENABLED_KEY
    )
    if row is None:
        return False
    return bool(row.setting_value)


def _pct(node: User | None, field: str, *fallbacks: str):
    """Read a 0..100 share % off a node. Returns the FIRST field that is set
    (not None) — an explicit 0 is a real value (a No-brokerage admin sets its
    brokerage share to 0) and is returned as-is, NOT treated as "unset". Only a
    None field falls through to `fallbacks` (legacy admins with no split inherit
    pnl_share_pct)."""
    if node is None:
        return ZERO
    for name in (field, *fallbacks):
        v = getattr(node, name, None)
        if v is not None:
            return to_decimal(v)
    return ZERO


def _fixed_brokerage_for(admin: User, instrument_segment: str | None, turnover, lots):
    """The FIXED brokerage the SA collects from a fixed-brokerage admin on ONE
    trade — per-lot or per-crore, per the admin's frozen segment rate (same math
    as Account 2). `turnover` = trade value (₹), `lots` = |qty|/lot_size."""
    try:
        from app.services.account2_service import _CRORE, _effective_rate
        from app.services.netting_service import _SEGMENT_NAME_MAP

        code = _SEGMENT_NAME_MAP.get(instrument_segment or "", instrument_segment or "")
        rates = dict(getattr(admin, "fixed_brokerage_rates", None) or {})
        entry = rates.get(code)
        if entry:
            rate, unit = _effective_rate(entry)
        else:  # legacy single-rate fallback
            rate = to_decimal(getattr(admin, "fixed_brokerage_rate", 0) or 0)
            unit = getattr(admin, "fixed_brokerage_unit", None) or "per_crore"
        rate = to_decimal(rate)
        if rate <= ZERO:
            return ZERO
        if unit == "per_lot":
            return quantize_money(to_decimal(lots or 0) * rate)
        return quantize_money((to_decimal(turnover or 0) / _CRORE) * rate)  # per_crore
    except Exception:
        logger.debug("admin_book_fixed_brokerage_failed seg=%s", instrument_segment, exc_info=True)
        return ZERO


async def distribute_on_close(
    user: User,
    raw_realized_pnl,
    brokerage,
    instrument_segment: str | None,
    trade_id: str,
    order_id: str | None = None,
    instrument_symbol: str | None = None,
    turnover=None,
    lots=None,
) -> None:
    """Book one closing trade's house result + brokerage to the owning admin and
    skim the super-admin's share. `raw_realized_pnl` is the user's SIGNED realized
    P&L (negative = user lost). No-op unless the admin-book flag is ON."""
    try:
        if not await is_admin_book_enabled():
            return

        admin_id = getattr(user, "assigned_admin_id", None)
        if admin_id is None:
            return  # user hangs directly off the platform — nothing to book

        from app.services import netting_service, wallet_service

        sa_id = await netting_service._resolve_super_admin_id()
        if sa_id is None or PydanticObjectId(str(sa_id)) == PydanticObjectId(str(admin_id)):
            return

        admin = await User.get(admin_id)
        if admin is None:
            return

        # SIGNED house result: house gains a user LOSS (positive), eats a user
        # PROFIT (negative → admin is debited). Brokerage is always a house gain.
        house_pnl = -to_decimal(raw_realized_pnl)
        brok = to_decimal(brokerage)
        brok = brok if brok > ZERO else ZERO
        if house_pnl == ZERO and brok == ZERO:
            return

        is_fixed = bool(getattr(admin, "is_fixed_brokerage", False))
        no_self = bool(getattr(admin, "no_self_brokerage", False))

        # PnL share the SA skims. A NO-BROKERAGE ("pass-through") admin nets 0 →
        # the SA takes 100% of the house PnL for EVERY user (self / broker /
        # sub-broker); the admin keeps nothing. Any other admin → its configured %.
        if no_self:
            pnl_pct = to_decimal(100)
        else:
            pnl_pct = _pct(admin, "pnl_share_pct")
        sa_pnl = quantize_money(house_pnl * pnl_pct / to_decimal(100))

        # Brokerage the SA skims from the admin — depends on the admin TYPE:
        #  • FIXED-brokerage admin (Account 2) → the FIXED per-lot / per-crore
        #    amount on THIS trade (turnover/lots), NOT a % of the user's brokerage.
        #  • NO-BROKERAGE ("pass-through") admin → SA takes 100% of the brokerage
        #    for EVERY user (self / broker / sub-broker); the admin keeps 0.
        #    Brokers/sub-brokers earn via their own layer (untouched here).
        #  • Otherwise (% admin) → admin_brokerage_share_pct% of the user's
        #    brokerage (None → inherit pnl_share_pct).
        if is_fixed:
            bkg_pct = ZERO
            sa_bkg = _fixed_brokerage_for(admin, instrument_segment, turnover, lots)
        elif no_self:
            bkg_pct = to_decimal(100)  # admin nets 0 → 100% brokerage to SA (all users)
            sa_bkg = brok
        else:
            bkg_pct = _pct(admin, "admin_brokerage_share_pct", "pnl_share_pct")
            sa_bkg = quantize_money(brok * bkg_pct / to_decimal(100))
        admin_net = quantize_money(house_pnl + brok - sa_pnl - sa_bkg)
        sa_net = quantize_money(sa_pnl + sa_bkg)

        # ── Idempotency claim: insert the record FIRST (unique trade_id). If it
        #    already exists, another tick booked this leg — bail before moving money.
        from app.models.admin_book_entry import AdminBookEntry

        entry = AdminBookEntry(
            trade_id=str(trade_id),
            order_id=str(order_id) if order_id else None,
            user_id=user.id,
            admin_id=PydanticObjectId(str(admin_id)),
            sa_id=PydanticObjectId(str(sa_id)),
            segment=str(instrument_segment or ""),
            instrument_symbol=instrument_symbol,
            pnl_pct_snapshot=Decimal128(str(pnl_pct)),
            bkg_pct_snapshot=Decimal128(str(bkg_pct)),
            house_pnl_inr=Decimal128(str(house_pnl)),
            brokerage_inr=Decimal128(str(brok)),
            sa_pnl_share_inr=Decimal128(str(sa_pnl)),
            sa_bkg_share_inr=Decimal128(str(sa_bkg)),
            admin_net_inr=Decimal128(str(admin_net)),
            sa_net_inr=Decimal128(str(sa_net)),
            booked_at=now_utc(),
        )
        try:
            await entry.insert()
        except Exception:
            # Duplicate trade_id (already booked) or a transient write race —
            # never double-move money.
            logger.debug("admin_book_entry_dup trade=%s", trade_id)
            return

        seg = str(instrument_segment or "")
        ucode = getattr(user, "user_code", "")

        # 1) Book the full house result + brokerage to the owning ADMIN.
        if house_pnl != ZERO:
            await wallet_service.adjust(
                admin_id, house_pnl, transaction_type=TransactionType.ADMIN_BOOK_PNL,
                narration=f"Admin-book P&L — {ucode} ({seg})",
                reference_type="ADMIN_BOOK", reference_id=str(trade_id),
            )
        if brok > ZERO:
            await wallet_service.adjust(
                admin_id, brok, transaction_type=TransactionType.ADMIN_BOOK_BROKERAGE,
                narration=f"Admin-book brokerage — {ucode} ({seg})",
                reference_type="ADMIN_BOOK", reference_id=str(trade_id),
            )

        # 2) SA skims its share FROM the admin (signed for PnL).
        if sa_pnl != ZERO:
            await wallet_service.adjust(
                admin_id, -sa_pnl, transaction_type=TransactionType.SA_PNL_SHARE,
                narration=f"SA PnL share {pnl_pct}% — {ucode} ({seg})",
                reference_type="ADMIN_BOOK", reference_id=str(trade_id),
            )
            await wallet_service.adjust(
                sa_id, sa_pnl, transaction_type=TransactionType.SA_PNL_SHARE,
                narration=f"SA PnL share {pnl_pct}% from admin {getattr(admin, 'user_code', '')} — {ucode}",
                reference_type="ADMIN_BOOK", reference_id=str(trade_id),
            )
        _bkg_desc = "fixed" if is_fixed else f"{bkg_pct}%"
        if sa_bkg != ZERO:
            await wallet_service.adjust(
                admin_id, -sa_bkg, transaction_type=TransactionType.SA_BROKERAGE_SHARE,
                narration=f"SA brokerage share ({_bkg_desc}) — {ucode} ({seg})",
                reference_type="ADMIN_BOOK", reference_id=str(trade_id),
            )
            await wallet_service.adjust(
                sa_id, sa_bkg, transaction_type=TransactionType.SA_BROKERAGE_SHARE,
                narration=f"SA brokerage share ({_bkg_desc}) from admin {getattr(admin, 'user_code', '')} — {ucode}",
                reference_type="ADMIN_BOOK", reference_id=str(trade_id),
            )
    except Exception:  # noqa: BLE001 — admin-book must never break a trade close
        logger.exception(
            "admin_book_distribute_failed user=%s trade=%s",
            getattr(user, "id", None), trade_id,
        )
