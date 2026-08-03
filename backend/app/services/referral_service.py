"""Referral service — user-to-user growth incentive.

Three responsibilities (built across plan phases):
  • Phase 1: signup resolution (referral_code → referrer user) + Referral doc.
  • Phase 2: shared eligibility gate (segment toggle + 1-month window + house
    hierarchy-earnings threshold).
  • Phase 3/4: pay the referrer on the referred user's game win / trade.

Distinct from `app/services/games/hierarchy.py` (admin franchise commission).
All functions are defensive: a referral failure must NEVER break signup, a
game settlement, or a trade close — callers wrap in try/except and log.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from decimal import Decimal

from beanie import PydanticObjectId
from bson import Decimal128

from app.models.games.hierarchy_earnings import SuperAdminHierarchyEarnings
from app.models.referral import Referral, ReferralStatus
from app.models.user import User, UserRole, ReferralStats
from app.utils.decimal_utils import quantize_money, to_decimal
from app.utils.time_utils import now_utc

logger = logging.getLogger(__name__)

# Referral is only paid within this window after the referred user signed up.
_REFERRAL_WINDOW_DAYS = 30
# Default trading-referral rate (% of the referred user's trade brokerage).
DEFAULT_TRADING_REFERRAL_PERCENT = 10.0


# ── Phase 1: signup resolution ─────────────────────────────────────────
async def resolve_referrer(referral_code: str | None) -> User | None:
    """Return the CLIENT user whose `user_code` matches `referral_code`, else
    None. Only ordinary users (not admins/brokers) act as referrers — an admin
    code stays with the existing white-label attribution path."""
    if not referral_code:
        return None
    code = referral_code.strip()
    if not code:
        return None
    # Match the short 6-digit referral_number first (what users now share),
    # then fall back to the full user_code (legacy links / codes).
    ref = await User.find_one(User.referral_number == code)
    if ref is None:
        ref = await User.find_one(User.user_code == code.upper())
    if ref is None or ref.role != UserRole.CLIENT:
        return None
    return ref


async def create_referral_on_signup(referrer: User, new_user: User) -> None:
    """Create the ACTIVE Referral doc linking referrer → new_user and bump the
    referrer's rollup counters. Idempotent on `referred_user` (unique index)."""
    from app.utils.time_utils import now_utc

    existing = await Referral.find_one(Referral.referred_user == new_user.id)
    if existing is not None:
        return
    try:
        await Referral(
            referrer=referrer.id,  # type: ignore[arg-type]
            referred_user=new_user.id,  # type: ignore[arg-type]
            referral_code=referrer.user_code,
            status=ReferralStatus.ACTIVE,
            activated_at=now_utc(),
        ).insert()
    except Exception:
        logger.exception("referral_signup_doc_failed referrer=%s new=%s", referrer.id, new_user.id)
        return
    # Bump the referrer's counters (best-effort).
    try:
        stats = referrer.referral_stats or ReferralStats()
        stats.total_referrals += 1
        stats.active_referrals += 1
        referrer.referral_stats = stats
        await referrer.save()
    except Exception:
        logger.exception("referral_stats_bump_failed referrer=%s", referrer.id)


# ── Hierarchy earnings rollup (feeds the threshold gate) ───────────────
async def _super_admin_id() -> PydanticObjectId | None:
    from app.services import netting_service

    return await netting_service._resolve_super_admin_id()


def _root_admin_id(user: User, sa_id: PydanticObjectId | None) -> PydanticObjectId | None:
    """The ADMIN that roots this user's subtree (for the earnings rollup)."""
    return getattr(user, "assigned_admin_id", None) or sa_id


async def bump_hierarchy_earnings(root_admin_id, segment: str, amount) -> None:
    """Add `amount` to the (super_admin, root_admin) rollup for `segment`.
    Called whenever a hierarchy commission is earned. Best-effort."""
    amt = quantize_money(to_decimal(amount))
    if amt <= 0:
        return
    seg = segment if segment in ("games", "trading", "mcx", "crypto", "forex") else "trading"
    try:
        sa_id = await _super_admin_id()
        if sa_id is None:
            return
        if root_admin_id is None:
            root_admin_id = sa_id  # user hangs directly off the platform
        coll = SuperAdminHierarchyEarnings.get_motor_collection()
        await coll.update_one(
            {"super_admin_id": sa_id, "root_admin_id": root_admin_id},
            {
                "$inc": {
                    f"earnings_by_segment.{seg}": Decimal128(str(amt)),
                    "total_earnings": Decimal128(str(amt)),
                },
                "$setOnInsert": {"created_at": now_utc()},
                "$set": {"updated_at": now_utc()},
            },
            upsert=True,
        )
    except Exception:
        logger.exception("bump_hierarchy_earnings_failed root=%s seg=%s", root_admin_id, segment)


# ── Record a paid referral reward (Referral doc + referrer rollup) ─────
async def record_referral_earning(
    referrer_id, referred_user_id, amount, *, game: str | None = None, trade: dict | None = None
) -> None:
    """Bump the Referral doc's earnings (+ first_game_win / trading_referrals)
    and the referrer's `referral_stats.total_referral_earnings`. Best-effort."""
    amt = quantize_money(to_decimal(amount))
    if amt <= 0:
        return
    try:
        ref = await Referral.find_one(Referral.referred_user == referred_user_id)
        if ref is not None:
            ref.earnings = Decimal128(str(to_decimal(ref.earnings) + amt))
            if game is not None and not ref.first_game_win.credited:
                ref.first_game_win.credited = True
                ref.first_game_win.amount = Decimal128(str(amt))
                ref.first_game_win.game = game
                ref.first_game_win.credited_at = now_utc()
            if trade is not None:
                from app.models.referral import TradingReferralEntry

                ref.trading_referrals.append(
                    TradingReferralEntry(
                        trade_id=str(trade.get("trade_id")),
                        amount=Decimal128(str(amt)),
                        brokerage=Decimal128(str(to_decimal(trade.get("brokerage", 0)))),
                        segment=str(trade.get("segment", "trading")),
                        credited_at=now_utc(),
                    )
                )
                ref.trading_referral_count += 1
            await ref.save()
        # Referrer rollup.
        referrer = await User.get(referrer_id)
        if referrer is not None:
            stats = referrer.referral_stats or ReferralStats()
            stats.total_referral_earnings = Decimal128(
                str(to_decimal(stats.total_referral_earnings) + amt)
            )
            referrer.referral_stats = stats
            await referrer.save()
    except Exception:
        logger.exception("record_referral_earning_failed referrer=%s", referrer_id)


# ── Phase 2: shared eligibility gate ───────────────────────────────────
def _segment_enabled(rde, segment: str) -> bool:
    """rde = admin.referral_distribution_enabled (or None → all enabled).
    mcx/crypto/forex additionally require the master `trading` flag."""
    if rde is None:
        return True
    if segment == "games":
        return bool(rde.games)
    if segment == "trading":
        return bool(rde.trading)
    if segment in ("mcx", "crypto", "forex"):
        return bool(rde.trading) and bool(getattr(rde, segment))
    return True


def _segment_of_instrument(segment: str | None) -> str:
    """Instrument segment → referral segment key (trading/mcx/crypto/forex)."""
    from app.services import wallet_kinds

    kind = wallet_kinds.wallet_kind_for_segment(segment)
    return {"MCX": "mcx", "CRYPTO": "crypto", "FOREX": "forex"}.get(kind, "trading")


# Referral segment key → human label shown in the ledger detail.
_SEGMENT_LABELS: dict[str, str] = {
    "trading": "NSE",
    "mcx": "MCX",
    "crypto": "Crypto",
    "forex": "Forex",
}


def _segment_label(seg: str | None) -> str:
    """Referral segment key → display label (NSE/MCX/Crypto/Forex)."""
    return _SEGMENT_LABELS.get((seg or "").lower(), "NSE")


def _dominant_referral_segment(ref: "Referral") -> str:
    """The segment key that contributed the most brokerage across this
    referred user's accrued trades. Falls back to 'trading' (NSE)."""
    totals: dict[str, Decimal] = {}
    for e in ref.trading_referrals or []:
        seg = getattr(e, "segment", None) or "trading"
        totals[seg] = totals.get(seg, Decimal("0")) + to_decimal(getattr(e, "brokerage", 0))
    if not totals:
        return "trading"
    return max(totals, key=lambda k: totals[k])


async def _super_admin_net_brokerage_share(referred: User, brokerage: Decimal) -> Decimal:
    """The SUPER-ADMIN's NET brokerage remainder from one trade of `referred`.

    Economics (recon-confirmed): each hierarchy node keeps its own `share_pct`
    of the house pool and the SUPER-ADMIN (house) keeps the REMAINDER. A broker's
    cut comes OUT of the admin's share (parent-net cascade), so the SA's net
    depends only on the OWNING ADMIN's brokerage-share %:

        SA_net = brokerage × (100 − admin.pnl_share_pct) / 100

    A user hanging directly off the platform (no admin) → SA keeps 100%.
    """
    admin_uid = getattr(referred, "assigned_admin_id", None)
    if admin_uid is None:
        return quantize_money(to_decimal(brokerage))
    admin = await User.get(admin_uid)
    if admin is None:
        return quantize_money(to_decimal(brokerage))
    # Prefer the admin's SEPARATE brokerage-share %; fall back to pnl_share_pct
    # when it was never split (keeps legacy admins byte-identical).
    admin_pct = to_decimal(
        getattr(admin, "admin_brokerage_share_pct", None)
        if getattr(admin, "admin_brokerage_share_pct", None) is not None
        else (getattr(admin, "pnl_share_pct", 0) or 0)
    )
    sa_fraction = (to_decimal(100) - admin_pct) / to_decimal(100)
    if sa_fraction < 0:
        sa_fraction = Decimal("0")
    if sa_fraction > 1:
        sa_fraction = Decimal("1")
    return quantize_money(to_decimal(brokerage) * sa_fraction)


async def _trading_referral_config() -> tuple[bool, Decimal, Decimal]:
    """(enabled, threshold, reward) from the super-admin's referral_eligibility.
    Defaults: enabled True, 🪙1000 threshold, 🪙1000 reward."""
    try:
        sa_id = await _super_admin_id()
        sa = await User.get(sa_id) if sa_id else None
        elig = getattr(sa, "referral_eligibility", None) if sa else None
        if elig is None:
            return True, to_decimal(1000), to_decimal(1000)
        return (
            bool(elig.enabled),
            to_decimal(getattr(elig, "trading_threshold_amount", 1000.0) or 1000.0),
            to_decimal(getattr(elig, "trading_reward_amount", 1000.0) or 1000.0),
        )
    except Exception:
        return True, to_decimal(1000), to_decimal(1000)


# ── Phase 4: trading referral — THRESHOLD model (one-time per referred user) ─
async def credit_referral_trading_reward(
    user_id, brokerage, trade_id: str, instrument_segment: str | None
) -> None:
    """Accrue the SUPER-ADMIN's NET brokerage income from this referred user and,
    once it reaches the configured threshold, pay the referrer a ONE-TIME reward.

    Per closed brokerage-charging trade: add `SA_net_share` to
    `Referral.sa_brokerage_accrued` (idempotent by `trade_id`); when the running
    total ≥ threshold and the reward hasn't been paid yet, credit the referrer's
    Main wallet the reward amount exactly once. Never raises (caller wraps too).
    """
    try:
        brok = to_decimal(brokerage)
        if brok <= 0:
            return
        referred = await User.get(user_id)
        if referred is None or getattr(referred, "referred_by", None) is None:
            return
        # Super-admin master switch: trading-referral income can be turned OFF for
        # an ENTIRE admin's client base at once (sub-admins 3-dot). When the
        # referred user's owning admin has trading_referral_enabled=False, skip
        # all accrual + payout — one switch kills it for that admin's whole pool.
        admin_uid = getattr(referred, "assigned_admin_id", None)
        if admin_uid is not None:
            owning_admin = await User.get(admin_uid)
            if owning_admin is not None and not getattr(
                owning_admin, "trading_referral_enabled", True
            ):
                return
        referrer_id = referred.referred_by
        seg = _segment_of_instrument(instrument_segment)

        ref = await Referral.find_one(Referral.referred_user == referred.id)
        if ref is None:
            return
        # Idempotency: this trade already accrued?
        if any(e.trade_id == str(trade_id) for e in (ref.trading_referrals or [])):
            return

        # SA's net brokerage share from THIS trade.
        sa_share = await _super_admin_net_brokerage_share(referred, brok)

        # Accrue + record the trade (idempotent from here on). Accrual is now
        # PER SEGMENT: each segment (trading/mcx/crypto/forex) tracks its own
        # running SA-net total so it can pay its own one-time reward (4x model).
        from app.models.referral import TradingReferralEntry

        by_seg = dict(ref.sa_brokerage_accrued_by_segment or {})
        seg_prev = to_decimal(by_seg.get(seg, Decimal128("0")))
        seg_accrued = seg_prev + sa_share
        by_seg[seg] = Decimal128(str(seg_accrued))
        ref.sa_brokerage_accrued_by_segment = by_seg
        # Keep the pooled total updated too (legacy progress display).
        ref.sa_brokerage_accrued = Decimal128(
            str(to_decimal(ref.sa_brokerage_accrued) + sa_share)
        )
        ref.trading_referrals.append(
            TradingReferralEntry(
                trade_id=str(trade_id),
                amount=Decimal128("0"),  # per-trade payout is 0 in the threshold model
                brokerage=Decimal128(str(brok)),
                segment=seg,
                credited_at=now_utc(),
            )
        )
        ref.trading_referral_count += 1
        await ref.save()

        # House rollup (kept for analytics / other gates).
        await bump_hierarchy_earnings(_root_admin_id(referred, await _super_admin_id()), seg, brok)

        # Per-segment one-time threshold payout.
        enabled, threshold, reward = await _trading_referral_config()
        if not enabled or reward <= 0:
            return
        # Backward-compat: a referral that already got the OLD pooled reward
        # (trading_reward_paid=True, empty per-segment list) is seeded with its
        # dominant segment so we never re-pay that same segment; the other 3
        # segments remain free to earn going forward.
        if ref.trading_reward_paid and not (ref.trading_reward_paid_segments or []):
            dom = _dominant_referral_segment(ref)
            await Referral.get_motor_collection().update_one(
                {"_id": ref.id},
                {"$addToSet": {"trading_reward_paid_segments": dom}},
            )
            ref.trading_reward_paid_segments = [dom]
        if seg in (ref.trading_reward_paid_segments or []):
            return  # this segment's reward already paid
        if seg_accrued < threshold:
            return

        # Atomically claim THIS SEGMENT's one-time payout (re-entrant/concurrent
        # ticks for the same segment can't double-pay — the $ne gate + $addToSet
        # only lets one through).
        claimed = await Referral.get_motor_collection().find_one_and_update(
            {"_id": ref.id, "trading_reward_paid_segments": {"$ne": seg}},
            {"$addToSet": {"trading_reward_paid_segments": seg},
             "$inc": {"earnings": Decimal128(str(reward))},
             "$set": {"trading_reward_paid": True, "trading_reward_paid_at": now_utc(),
                      "trading_reward_amount": Decimal128(str(reward))}},
        )
        if claimed is None:
            return  # another tick already paid this segment

        from app.models.transaction import TransactionType
        from app.services import wallet_service

        seg_label = _segment_label(seg)
        await wallet_service.adjust(
            referrer_id, reward,
            transaction_type=TransactionType.REFERRAL_COMMISSION,
            narration=f"Referral reward ({seg_label}) — {referred.user_code} reached {seg_label} threshold",
            reference_type="REFERRAL_THRESHOLD", reference_id=str(referred.id),
        )
        # Referrer rollup.
        referrer = await User.get(referrer_id)
        if referrer is not None:
            stats = referrer.referral_stats or ReferralStats()
            stats.total_referral_earnings = Decimal128(
                str(to_decimal(stats.total_referral_earnings) + reward)
            )
            referrer.referral_stats = stats
            await referrer.save()
        logger.info(
            "trading_referral_reward_paid referrer=%s referred=%s reward=%s accrued=%s",
            referrer_id, referred.id, reward, ref.sa_brokerage_accrued,
        )
    except Exception:
        logger.exception("trading_referral_failed user=%s trade=%s", user_id, trade_id)


async def process_conditional_referral_payout(
    referred_user: User, amount, segment: str, meta: dict | None = None
) -> bool:
    """Return True if a referral reward for `referred_user` in `segment` should
    be PAID now, False if it must be HELD/skipped. Checks: (1) has a referrer,
    (2) within the 1-month window, (3) segment enabled for the subtree,
    (4) house hierarchy-earnings threshold reached. Never raises."""
    try:
        if getattr(referred_user, "referred_by", None) is None:
            return False
        # 1-month window from signup.
        created = getattr(referred_user, "created_at", None)
        if created is not None and (now_utc() - created) > timedelta(days=_REFERRAL_WINDOW_DAYS):
            return False
        sa_id = await _super_admin_id()
        # Segment enable toggle (on the user's ADMIN, else the super-admin).
        admin_uid = getattr(referred_user, "assigned_admin_id", None) or sa_id
        admin = await User.get(admin_uid) if admin_uid else None
        rde = getattr(admin, "referral_distribution_enabled", None) if admin else None
        if not _segment_enabled(rde, segment):
            return False
        # Threshold gate (config on the super-admin).
        sa = await User.get(sa_id) if sa_id else None
        elig = getattr(sa, "referral_eligibility", None) if sa else None
        if elig is not None and elig.enabled:
            root_admin = _root_admin_id(referred_user, sa_id)
            row = await SuperAdminHierarchyEarnings.find_one(
                SuperAdminHierarchyEarnings.super_admin_id == sa_id,
                SuperAdminHierarchyEarnings.root_admin_id == root_admin,
            )
            total = to_decimal(row.total_earnings) if row else Decimal("0")
            if not SuperAdminHierarchyEarnings.threshold_reached(
                total, elig.threshold_amount, elig.threshold_unit
            ):
                logger.info(
                    "referral_held_below_threshold user=%s seg=%s total=%s",
                    referred_user.id, segment, total,
                )
                return False
        return True
    except Exception:
        logger.exception("referral_gate_failed user=%s seg=%s", getattr(referred_user, "id", None), segment)
        return False
