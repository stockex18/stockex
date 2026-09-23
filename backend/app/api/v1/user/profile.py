"""User profile endpoint — /api/v1/user/users/me."""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException

from app.core.config import settings
from app.core.dependencies import CurrentUser
from app.models.audit_log import AuditAction
from app.models.user import User, UserRole, UserStatus
from app.schemas.common import APIResponse
from app.schemas.user import UpdateProfileRequest, UserMeOut
from app.services import branding_service
from app.services.audit_service import log_event

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/users", tags=["user-profile"])


@router.get("/me", response_model=APIResponse[UserMeOut])
async def get_me(user: CurrentUser):
    return APIResponse(data=await _me_out(user))


@router.put("/me", response_model=APIResponse[UserMeOut])
async def update_me(payload: UpdateProfileRequest, user: CurrentUser):
    if payload.full_name is not None:
        user.full_name = payload.full_name
    if payload.photo_url is not None:
        user.photo_url = payload.photo_url
    if payload.communication is not None:
        user.communication = payload.communication
    if payload.kyc is not None:
        # Only allow updating non-verified KYC fields
        if not user.kyc.is_verified:
            user.kyc = payload.kyc
    await user.save()
    return APIResponse(data=await _me_out(user))


@router.put("/me/broker", response_model=APIResponse[UserMeOut])
async def change_my_broker(payload: dict, user: CurrentUser):
    """Self-service broker switch — the user picks a new broker (from the same
    signup search) and re-stamps their hierarchy. Affects FUTURE attribution
    only; existing wallet/positions/settlements are untouched."""
    from app.services import broker_search_service

    broker = await broker_search_service.resolve_active_visible_broker(str(payload.get("broker_id") or ""))
    if broker is None:
        raise HTTPException(status_code=400, detail="Please choose a valid broker.")
    user.assigned_broker_id = broker.id
    user.assigned_admin_id = broker.assigned_admin_id
    user.broker_ancestry = (broker.broker_ancestry or []) + [broker.id]
    await user.save()
    try:
        await log_event(
            action=AuditAction.UPDATE,
            entity_type="User",
            entity_id=user.id,
            actor_id=user.id,
            new_values={"assigned_broker_id": str(broker.id)},
        )
    except Exception:  # noqa: BLE001
        pass
    return APIResponse(data=await _me_out(user))


@router.post("/me/convert-to-real", response_model=APIResponse[UserMeOut])
async def convert_to_real(user: CurrentUser):
    """Convert the logged-in DEMO account into a fresh REAL account.

    Wipes all demo trades/positions/orders/holdings, per-segment wallets and
    games data, and zeroes the balance — then flips the account to LIVE. Login
    credentials and the chosen broker are kept, so the user carries on as a real
    client with a ₹0 balance (deposit to start). 400 if not a demo account.
    """
    if not getattr(user, "is_demo", False):
        raise HTTPException(status_code=400, detail="This is already a real account.")

    from app.services import demo_service

    res = await demo_service.convert_demo_to_real(user)
    if not res.get("converted"):
        raise HTTPException(status_code=400, detail="Could not convert this account.")
    try:
        await log_event(
            action=AuditAction.UPDATE,
            entity_type="User",
            entity_id=user.id,
            actor_id=user.id,
            new_values={"account_type": "LIVE", "is_demo": False},
        )
    except Exception:  # noqa: BLE001
        pass
    fresh = await User.get(user.id) or user

    # This is the moment a visitor becomes a real client of somebody's book.
    # Signing up no longer does it — registration opens a demo — so THIS is
    # the first thing the owning admin needs to hear about, and the row is
    # what they act on: set limits, brokerage, and take the first deposit.
    try:
        from app.models.notification import AdminNotificationEventType
        from app.services import notification_service

        await notification_service.create_for_admins(
            fresh.id,
            AdminNotificationEventType.USER_REGISTERED,
            "New real account",
            f"{fresh.full_name or fresh.user_code} ({fresh.user_code}) switched "
            f"from demo to a real account. Balance is 🪙0 — awaiting their first deposit.",
            link=f"/users?q={fresh.user_code}",
            reference_type="User",
            reference_id=str(fresh.id),
        )
    except Exception:  # noqa: BLE001 — the account IS real; a bell row is not
        logger.exception("convert_to_real_notify_failed user=%s", fresh.id)

    return APIResponse(
        data=await _me_out(fresh),
        message="Your account is now real. Balance is ₹0 — add funds to start trading.",
    )


@router.get("/me/branding", response_model=APIResponse[dict])
async def get_my_branding(user: CurrentUser):
    """Return the branding payload for the logged-in user's
    ``assigned_admin_id`` (or ``None`` if the user is in the
    super-admin/platform pool).

    The frontend's ``BrandingProvider`` calls this once after login
    to apply the right logo / brand-name / favicon on the dashboard,
    and to decide whether to redirect to the admin's custom domain
    (gated on ``user.signup_origin``).
    """
    if not settings.BRANDING_ENABLED:
        return APIResponse(
            data={"branding": None, "signup_origin": user.signup_origin}
        )
    if user.assigned_admin_id is None:
        return APIResponse(
            data={"branding": None, "signup_origin": user.signup_origin}
        )
    admin = await User.get(user.assigned_admin_id)
    if (
        admin is None
        or admin.role != UserRole.ADMIN
        or admin.status != UserStatus.ACTIVE
    ):
        return APIResponse(
            data={"branding": None, "signup_origin": user.signup_origin}
        )
    return APIResponse(
        data={
            "branding": branding_service.to_branding_payload(admin),
            "signup_origin": user.signup_origin,
        }
    )


async def _me_out(user) -> UserMeOut:
    """UserMeOut + the user's current broker (name/city) resolved from
    `assigned_broker_id`."""
    out = _user_to_me(user)
    if user.assigned_broker_id:
        b = await User.get(user.assigned_broker_id)
        if b is not None:
            out.assigned_broker_id = str(b.id)
            out.broker = {
                "user_code": b.user_code,
                "full_name": b.full_name,
                "city": getattr(b, "city", None),
            }
    return out


def _user_to_me(user) -> UserMeOut:
    return UserMeOut(
        id=str(user.id),
        user_code=user.user_code,
        email=user.email,
        mobile=user.mobile,
        full_name=user.full_name,
        photo_url=user.photo_url,
        role=user.role,
        status=user.status,
        account_type=user.account_type,
        is_demo=user.is_demo,
        parent_id=str(user.parent_id) if user.parent_id else None,
        kyc=user.kyc,
        permissions=user.permissions,
        trading_hours=user.trading_hours,
        risk=user.risk,
        communication=user.communication,
        two_fa_enabled=user.two_fa_enabled,
        last_login_at=user.last_login_at,
        created_at=user.created_at,
    )
