"""User referral API — share code/link, stats, and earnings ledger."""

from __future__ import annotations

from app.core.config import settings
from app.core.dependencies import CurrentUser
from app.models.referral import Referral
from app.models.transaction import TransactionType, WalletTransaction
from app.models.user import User
from app.schemas.common import APIResponse
from fastapi import APIRouter

router = APIRouter(prefix="/referral", tags=["user-referral"])


@router.get("/stats", response_model=APIResponse[dict])
async def referral_stats(user: CurrentUser):
    """The user's own referral code (= user_code), share link, rollup totals,
    and the list of users they've referred (with per-referral earnings)."""
    # Short 6-digit referral code (falls back to user_code for any legacy row
    # not yet backfilled). Assign lazily if somehow missing.
    code = getattr(user, "referral_number", None)
    if not code:
        from app.services.user_service import generate_referral_number

        code = await generate_referral_number()
        user.referral_number = code
        await user.save()
    base = (getattr(settings, "USER_APP_URL", "") or "").rstrip("/")
    share_link = f"{base}/register?ref={code}" if base else f"/register?ref={code}"

    refs = await Referral.find(Referral.referrer == user.id).sort("-created_at").to_list()
    referred_ids = [r.referred_user for r in refs]
    users = {}
    if referred_ids:
        for u in await User.find({"_id": {"$in": referred_ids}}).to_list():
            users[str(u.id)] = u

    # Trading-referral threshold config (super-admin) — drives the progress bar.
    from app.services import referral_service

    _enabled, threshold, reward = await referral_service._trading_referral_config()
    threshold_f = float(threshold)
    reward_f = float(reward)

    # 4x model: each segment earns its own one-time reward.
    _SEG_LABELS = [("trading", "NSE"), ("mcx", "MCX"), ("crypto", "Crypto"), ("forex", "Forex")]

    items = []
    total_earn = 0.0
    for r in refs:
        ru = users.get(str(r.referred_user))
        earn = float(str(r.earnings.to_decimal())) if r.earnings else 0.0
        total_earn += earn
        accrued = float(str(r.sa_brokerage_accrued.to_decimal())) if getattr(r, "sa_brokerage_accrued", None) else 0.0
        paid = bool(getattr(r, "trading_reward_paid", False))
        progress = 100.0 if paid else (min(100.0, accrued / threshold_f * 100.0) if threshold_f > 0 else 0.0)

        # Per-segment breakdown (NSE / MCX / Crypto / Forex) — each pays once.
        by_seg = getattr(r, "sa_brokerage_accrued_by_segment", None) or {}
        paid_segs = set(getattr(r, "trading_reward_paid_segments", None) or [])
        segments = []
        for seg_key, seg_label in _SEG_LABELS:
            raw = by_seg.get(seg_key)
            seg_accrued = float(str(raw.to_decimal())) if raw is not None else 0.0
            seg_paid = seg_key in paid_segs
            seg_progress = (
                100.0 if seg_paid
                else (min(100.0, seg_accrued / threshold_f * 100.0) if threshold_f > 0 else 0.0)
            )
            segments.append(
                {
                    "segment": seg_key,
                    "label": seg_label,
                    "accrued": round(seg_accrued, 2),
                    "paid": seg_paid,
                    "progress_pct": round(seg_progress, 1),
                }
            )
        rewards_paid_count = len(paid_segs)

        items.append(
            {
                "referred_user_code": ru.user_code if ru else None,
                "referred_name": ru.full_name if ru else None,
                "status": r.status.value if hasattr(r.status, "value") else str(r.status),
                "earnings": earn,
                "first_game_win": bool(r.first_game_win.credited),
                "trading_referral_count": r.trading_referral_count,
                # Legacy pooled progress (kept for backward compat).
                "sa_brokerage_accrued": round(accrued, 2),
                "trading_threshold": threshold_f,
                "trading_reward": reward_f,
                "trading_progress_pct": round(progress, 1),
                "trading_reward_paid": paid,
                # 4x per-segment model.
                "segments": segments,
                "trading_rewards_paid_count": rewards_paid_count,
                "trading_rewards_max": len(_SEG_LABELS),
                "joined_at": r.created_at,
            }
        )

    st = user.referral_stats
    return APIResponse(
        data={
            "code": code,
            "share_link": share_link,
            "total_referrals": st.total_referrals if st else len(refs),
            "active_referrals": st.active_referrals if st else len(refs),
            "total_earnings": (
                float(str(st.total_referral_earnings.to_decimal())) if st else total_earn
            ),
            "trading_threshold": threshold_f,
            "trading_reward": reward_f,
            "referrals": items,
        }
    )


@router.get("/earnings", response_model=APIResponse[list])
async def referral_earnings(user: CurrentUser, limit: int = 200):
    """Ledger of REFERRAL_COMMISSION credits paid to this user (trading side,
    from the main / segment wallets). Games-side referral credits live in the
    games ledger and surface on the games wallet screen."""
    limit = max(1, min(500, limit))
    rows = (
        await WalletTransaction.find(
            WalletTransaction.user_id == user.id,
            WalletTransaction.transaction_type == TransactionType.REFERRAL_COMMISSION,
        )
        .sort("-created_at")
        .limit(limit)
        .to_list()
    )
    out = []
    for t in rows:
        out.append(
            {
                "amount": float(str(t.amount.to_decimal())) if t.amount else 0.0,
                "narration": t.narration,
                "reference_type": t.reference_type,
                "created_at": t.created_at,
            }
        )
    return APIResponse(data=out)
