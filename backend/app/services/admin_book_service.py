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


# ── Which of the five arrangements is this admin on? ──────────────────
# Deliberately NOT a stored setting. It is read off the SAME fields the money
# is actually split by, so a label on a ledger can never say one thing while
# the book does another. Change how an admin is paid and the label follows on
# its own.
#
#   1  Office admin        no_self_brokerage — the SA takes the whole
#                          brokerage and the whole P&L; the admin keeps 0.
#   2  Fixed brokerage,    is_fixed + P&L share 0% — the admin pays a fixed
#      admin keeps P&L     per-lot / per-crore amount and runs its own book.
#   3  Fixed brokerage,    is_fixed + P&L share 100%.
#      P&L to the SA
#   4  Fixed brokerage,    is_fixed + a share strictly between the two.
#      P&L on patti
#   5  Patti, no fixed     neither flag — brokerage and P&L both split by %.
ADMIN_TYPE_NAMES = {
    1: "Office · no brokerage",
    2: "Fixed brokerage · P&L with admin",
    3: "Fixed brokerage · P&L to super-admin",
    4: "Fixed brokerage · P&L patti",
    5: "Patti · no fixed brokerage",
}


def _pct_str(v) -> str:
    """0..100 without the trailing zeros nobody reads."""
    s = str(quantize_money(to_decimal(v)))
    return s.rstrip("0").rstrip(".") if "." in s else s


def admin_type(admin: User | None) -> dict:
    """The arrangement this admin is on: number, short label, one-line reason.

    Returns `n=0` for anyone who is not an admin-shaped node, so a caller can
    render a dash rather than inventing a type.
    """
    if admin is None:
        return {"n": 0, "label": "—", "detail": ""}

    if bool(getattr(admin, "no_self_brokerage", False)):
        return {
            "n": 1,
            "label": ADMIN_TYPE_NAMES[1],
            "detail": "The super-admin takes the whole brokerage and the whole "
                      "P&L. This admin keeps nothing of its own.",
        }

    pnl = _pct(admin, "pnl_share_pct")
    if bool(getattr(admin, "is_fixed_brokerage", False)):
        if pnl <= ZERO:
            return {
                "n": 2,
                "label": ADMIN_TYPE_NAMES[2],
                "detail": "A fixed brokerage goes to the super-admin. The admin "
                          "runs its own book and keeps all of the P&L.",
            }
        if pnl >= to_decimal(100):
            return {
                "n": 3,
                "label": ADMIN_TYPE_NAMES[3],
                "detail": "A fixed brokerage goes to the super-admin, and so "
                          "does 100% of the P&L.",
            }
        return {
            "n": 4,
            "label": ADMIN_TYPE_NAMES[4] + " " + _pct_str(pnl) + "%",
            "detail": "A fixed brokerage goes to the super-admin, and the P&L is "
                      "split — " + _pct_str(pnl) + "% to the super-admin, the rest stays here.",
        }

    bkg = _pct(admin, "admin_brokerage_share_pct", "pnl_share_pct")
    return {
        "n": 5,
        "label": ADMIN_TYPE_NAMES[5] + " " + _pct_str(pnl) + "%",
        "detail": "No fixed brokerage. The super-admin takes " + _pct_str(pnl)
                  + "% of the P&L and " + _pct_str(bkg) + "% of the brokerage.",
    }


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


def _node_brokerage(settings: dict, turnover, lots):
    """The brokerage ONE node's segment settings would charge on THIS trade —
    computed exactly like `brokerage_calculator._brokerage_from_netting`, so it is
    correct for EVERY mode (PER_LOT for options, PER_CRORE / PERCENTAGE for
    MCX / equity futures, FLAT). This is what lets the cascade work on turnover-
    based segments (MCX), where a raw `commission_value` is a per-crore rate — NOT
    a per-lot rupee amount that can be multiplied by lots."""
    from decimal import Decimal

    ctype = (settings.get("commission_type") or "PER_LOT").upper()
    value = to_decimal(settings.get("commission_value") or 0)
    if value <= ZERO:
        return ZERO
    turn = to_decimal(turnover or 0)
    lots_d = to_decimal(lots or 0)
    if ctype == "FLAT":
        b = value
    elif ctype == "PERCENTAGE":
        b = turn * value / to_decimal(100)
    elif ctype == "PER_CRORE":
        b = turn * value / Decimal("10000000")
    else:  # PER_LOT
        b = value * lots_d
    min_b = to_decimal(settings.get("min_brokerage") or 0)
    if min_b and b < min_b:
        b = min_b
    b = quantize_money(b)
    return b if b > ZERO else ZERO


async def _brokerage_cascade(user, instrument_segment, option_type, action, brok, lots, turnover=None, apply_admin_floor=True):
    """PASS-THROUGH admin chain only. Split the client's brokerage down the broker
    hierarchy by MARKUP: each broker / sub-broker keeps (its child's brokerage on
    this trade − its OWN brokerage on this trade); the remainder (the top broker's
    own brokerage = the admin's base) flows to the SA. Each node's brokerage is
    recomputed from its effective segment settings (`commission_type` +
    `commission_value`) on THIS trade's turnover / lots — so it is correct for
    per-lot (options) AND per-crore / percentage (MCX, futures) segments alike.
    Returns (cuts: {broker_id: amount}, admin_base). A level whose settings can't
    be resolved keeps 0 (no markup); its child's brokerage passes straight up."""
    from app.services import netting_service

    brok = to_decimal(brok)
    if brok <= ZERO:
        return {}, brok
    ancestry = list(getattr(user, "broker_ancestry", None) or [])  # root-first
    chain = list(reversed(ancestry))  # nearest (sub-broker) → root (top broker)
    cuts: dict = {}
    prev_brok = brok  # the client's actual brokerage sits at the top of the chain
    for bid in chain:
        try:
            resolved = await netting_service.get_effective_settings(
                bid, instrument_segment, action=action,
                option_type=option_type, product_type="NRML",
            )
            node_brok = _node_brokerage(resolved.get("settings") or {}, turnover, lots)
        except Exception:  # noqa: BLE001
            node_brok = prev_brok  # unresolvable → this level takes no markup
        # A node can never keep more than its child paid, nor go negative.
        if node_brok > prev_brok:
            node_brok = prev_brok
        cut = prev_brok - node_brok
        if cut > ZERO:
            cuts[bid] = quantize_money(cut)
        prev_brok = node_brok
    # SA's take for a pass-through admin = the admin's OWN effective segment rate
    # (what the super-admin set for THIS admin via its Segment settings), NOT the
    # top broker's rate. When brokers exist and the admin's rate sits BELOW the
    # top broker's, the top broker absorbs the residual down to the admin's floor
    # — so "SA collects exactly the brokerage it set for the admin, from every
    # client" holds even when a broker's per-lot / per-crore rate is far above the
    # admin's (e.g. crypto: broker 1200, admin 20 → SA must get the admin's 20,
    # the broker keeps the 1180 markup — NOT SA getting the broker's 1200).
    if apply_admin_floor and chain:
        admin_id = getattr(user, "assigned_admin_id", None)
        if admin_id is not None:
            try:
                ra = await netting_service.get_effective_settings(
                    admin_id, instrument_segment, action=action,
                    option_type=option_type, product_type="NRML",
                )
                admin_brok = _node_brokerage(ra.get("settings") or {}, turnover, lots)
            except Exception:  # noqa: BLE001
                admin_brok = None
            if admin_brok is not None and ZERO < admin_brok < prev_brok:
                root_bid = chain[-1]
                cuts[root_bid] = quantize_money(
                    to_decimal(cuts.get(root_bid, ZERO)) + (prev_brok - admin_brok)
                )
                prev_brok = admin_brok
    admin_base = quantize_money(prev_brok)
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
        # A demo account's trades are virtual money. Booking them moved REAL
        # coins to the super admin and the broker chain (operator: demo ka
        # kuch bhi admin, super admin ke ledger ya wallet me nahi aana
        # chahiye). The games already skip demo players the same way.
        if getattr(user, "is_demo", False):
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
            # Brokers / sub-brokers keep their client-brokerage markup — each
            # node keeps (its child's rate − its own rate). apply_admin_floor
            # =False: the cascade stops at the TOP broker's rate (that's the base
            # the admin books); the SA then takes its FIXED per-segment amount
            # and the admin keeps the rest. A broker only earns when its own rate
            # is BELOW its child's — set broker < sub-broker to give it a markup;
            # equal rates = no markup by design (not a bug).
            broker_cuts, _cb = await _brokerage_cascade(
                user, instrument_segment, option_type, action, brok, lots,
                turnover=turnover, apply_admin_floor=False,
            )
        elif no_self:
            # Pass-through: split the client's brokerage down the broker chain by
            # markup (each broker/sub-broker keeps its cut), the admin's base flows
            # to the SA. If there are no brokers the whole amount is the SA's base.
            bkg_pct = to_decimal(100)
            broker_cuts, sa_bkg = await _brokerage_cascade(
                user, instrument_segment, option_type, action, brok, lots,
                turnover=turnover, apply_admin_floor=True,
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
            # The admin books only the NON-broker portion of the brokerage; the
            # brokers / sub-brokers keep their own markup (cascade). For a fixed /
            # % admin with no brokers, cuts_total is 0 and the admin books the full
            # amount exactly as before.
            _admin_brok = quantize_money(brok - cuts_total)
            if _admin_brok > ZERO:
                await wallet_service.adjust(
                    admin_id, _admin_brok, transaction_type=TransactionType.ADMIN_BOOK_BROKERAGE,
                    narration=f"Admin-book brokerage — {ucode} ({seg})",
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
            if sa_pnl != ZERO:
                # Settled against the admin's collateral when they lodged any —
                # same rule as the SA's brokerage below, so the Security ledger
                # shows what the SA's share took and the balance draws down with
                # it. No collateral → the wallet, exactly as before.
                from app.services import admin_security_service as _sec

                _pnl_charged = await _sec.charge_pnl_share(
                    admin_id, sa_pnl,
                    narration=f"SA P&L share {pnl_pct}% — {ucode} ({seg})",
                    trade_id=str(trade_id), user_id=user.id,
                )
                if not _pnl_charged:
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
                # A fixed-brokerage admin who lodged security money settles the
                # SA's take against that collateral instead of their wallet —
                # the collateral is what the SA holds against this admin's book,
                # so the brokerage it earns should draw it down. Falls back to
                # the wallet for everyone else, which is the old behaviour.
                from app.services import admin_security_service

                charged = await admin_security_service.charge_brokerage(
                    admin_id, sa_bkg,
                    narration=f"SA brokerage ({_bkg_desc}) — {ucode} ({seg})",
                    trade_id=str(trade_id), user_id=user.id,
                )
                if not charged:
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
