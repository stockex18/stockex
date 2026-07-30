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


async def _brokerage_cascade(user, instrument_segment, option_type, action, brok, lots):
    """PASS-THROUGH admin chain only. Split the client's brokerage down the broker
    hierarchy by MARKUP: each broker / sub-broker keeps (child per-lot rate − own
    per-lot rate) × lots; the remainder (the top broker's rate = the admin's base)
    is what flows to the SA. Rates come from each node's effective segment
    brokerage (`commission_value`). Returns (cuts: {broker_id: amount}, admin_base).
    If a level's rate can't be resolved it keeps 0 (no markup)."""
    from app.services import netting_service

    brok = to_decimal(brok)
    lots_d = to_decimal(lots or 0)
    if lots_d <= ZERO or brok <= ZERO:
        return {}, brok
    client_rate = brok / lots_d
    ancestry = list(getattr(user, "broker_ancestry", None) or [])  # root-first
    chain = list(reversed(ancestry))  # nearest (sub-broker) → root (top broker)
    cuts: dict = {}
    prev_rate = client_rate
    for bid in chain:
        try:
            resolved = await netting_service.get_effective_settings(
                bid, instrument_segment, action=action,
                option_type=option_type, product_type="NRML",
            )
            node_rate = to_decimal((resolved.get("settings") or {}).get("commission_value") or 0)
        except Exception:  # noqa: BLE001
            node_rate = prev_rate  # unresolvable → this level takes no markup
        cut_per_lot = prev_rate - node_rate
        if cut_per_lot > ZERO:
            cuts[bid] = quantize_money(cut_per_lot * lots_d)
        prev_rate = node_rate if node_rate >= ZERO else prev_rate
    admin_base = quantize_money(prev_rate * lots_d)
    if admin_base < ZERO:
        admin_base = ZERO
    return cuts, admin_base


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
    option_type: str | None = None,
    action: str | None = None,
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
        broker_cuts: dict = {}
        if is_fixed:
            bkg_pct = ZERO
            sa_bkg = _fixed_brokerage_for(admin, instrument_segment, turnover, lots)
        elif no_self:
            # Pass-through: split the client's brokerage down the broker chain by
            # markup (each broker/sub-broker keeps its cut), the admin's base flows
            # to the SA. If there are no brokers the whole amount is the SA's base.
            bkg_pct = to_decimal(100)
            broker_cuts, sa_bkg = await _brokerage_cascade(
                user, instrument_segment, option_type, action, brok, lots
            )
        else:
            bkg_pct = _pct(admin, "admin_brokerage_share_pct", "pnl_share_pct")
            sa_bkg = quantize_money(brok * bkg_pct / to_decimal(100))
        cuts_total = sum((to_decimal(v) for v in broker_cuts.values()), ZERO)
        admin_net = quantize_money(house_pnl + brok - sa_pnl - sa_bkg - cuts_total)
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

        _bkg_desc = "fixed" if is_fixed else f"{bkg_pct}%"
        _acode = getattr(admin, "user_code", "")

        if no_self:
            # ── PASS-THROUGH admin: the admin's wallet is NOT touched at all. The
            #    house PnL + base brokerage go STRAIGHT to the SA; broker/sub-broker
            #    markups straight to the brokers. So a user LOSS/PROFIT is settled
            #    directly against the SUPER-ADMIN's wallet (operator spec), and the
            #    admin shows nothing (it truly earns 0). ──
            if sa_pnl != ZERO:
                await wallet_service.adjust(
                    sa_id, sa_pnl, transaction_type=TransactionType.SA_PNL_SHARE,
                    narration=f"SA PnL 100% (pass-through {_acode}) — {ucode} ({seg})",
                    reference_type="ADMIN_BOOK", reference_id=str(trade_id),
                )
            if sa_bkg != ZERO:
                await wallet_service.adjust(
                    sa_id, sa_bkg, transaction_type=TransactionType.SA_BROKERAGE_SHARE,
                    narration=f"SA brokerage base (pass-through {_acode}) — {ucode} ({seg})",
                    reference_type="ADMIN_BOOK", reference_id=str(trade_id),
                )
            for _bid, _cut in (broker_cuts or {}).items():
                _c = to_decimal(_cut)
                if _c <= ZERO:
                    continue
                await wallet_service.adjust(
                    _bid, _c, transaction_type=TransactionType.BROKER_CASCADE_BROKERAGE,
                    narration=f"Brokerage markup — {ucode} ({seg})",
                    reference_type="ADMIN_BOOK", reference_id=str(trade_id),
                )
        else:
            # ── NORMAL / FIXED admin: book the full house result + brokerage to the
            #    admin, then the SA skims its % / fixed share (admin keeps the rest). ──
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
            if sa_pnl != ZERO:
                await wallet_service.adjust(
                    admin_id, -sa_pnl, transaction_type=TransactionType.SA_PNL_SHARE,
                    narration=f"SA PnL share {pnl_pct}% — {ucode} ({seg})",
                    reference_type="ADMIN_BOOK", reference_id=str(trade_id),
                )
                await wallet_service.adjust(
                    sa_id, sa_pnl, transaction_type=TransactionType.SA_PNL_SHARE,
                    narration=f"SA PnL share {pnl_pct}% from admin {_acode} — {ucode}",
                    reference_type="ADMIN_BOOK", reference_id=str(trade_id),
                )
            if sa_bkg != ZERO:
                await wallet_service.adjust(
                    admin_id, -sa_bkg, transaction_type=TransactionType.SA_BROKERAGE_SHARE,
                    narration=f"SA brokerage share ({_bkg_desc}) — {ucode} ({seg})",
                    reference_type="ADMIN_BOOK", reference_id=str(trade_id),
                )
                await wallet_service.adjust(
                    sa_id, sa_bkg, transaction_type=TransactionType.SA_BROKERAGE_SHARE,
                    narration=f"SA brokerage share ({_bkg_desc}) from admin {_acode} — {ucode}",
                    reference_type="ADMIN_BOOK", reference_id=str(trade_id),
                )
    except Exception:  # noqa: BLE001 — admin-book must never break a trade close
        logger.exception(
            "admin_book_distribute_failed user=%s trade=%s",
            getattr(user, "id", None), trade_id,
        )
