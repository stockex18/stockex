"""Admin auth endpoint — login + refresh + logout (with mandatory 2FA, API-key + IP guard).

Note: the API-key + IP guard is enforced by `get_current_admin` for protected
routes. The login endpoint itself is intentionally accessible without a key —
otherwise no one could log in. We rely on rate-limiting + correct credentials
+ mandatory 2FA + audit logging to harden it.
"""

from __future__ import annotations

from fastapi import APIRouter, Request, status
from pydantic import BaseModel, EmailStr, Field

from app.core.dependencies import CurrentAdmin
from app.core.exceptions import InvalidCredentialsError
from app.core.rate_limit import rate_limit
from app.models.audit_log import AuditAction
from app.models.user import User, UserRole
from app.schemas.admin.auth import AdminLoginRequest, AdminTokenPair, AdminUserOut
from app.schemas.auth import LogoutRequest, RefreshRequest, TokenPair
from app.schemas.common import APIResponse, OkResponse
from app.core.config import settings
from app.services import auth_service


async def _branding_fields_for(admin_user: User) -> dict:
    """Return the branding kwargs to pass into AdminUserOut for this row.

    Cascade rules (confirmed with operator):
      - SUPER_ADMIN → no branding ever. Sidebar shows platform default.
                      Super-admin runs the whole system and is not part
                      of any tenant.
      - ADMIN       → their OWN brand_name / logo_url.
      - BROKER      → branding INHERITED from their parent ADMIN
                      (resolved via `assigned_admin_id`). Sub-brokers
                      have the same `assigned_admin_id` populated by
                      the broker-management service when they're
                      minted, so this single hop covers any depth of
                      sub-broker nesting without walking parent_id.
                      A broker created directly under super-admin (no
                      assigned_admin_id) gets platform default.

    The helper short-circuits when `BRANDING_ENABLED=false` so admins
    on a fresh deploy see the unchanged platform sidebar until the
    operator flips the flag.
    """
    # custom_domain is always returned — needed for referral link generation
    # on the dashboard regardless of BRANDING_ENABLED. brand_name/logo_url
    # are still gated behind the flag (white-label sidebar feature).
    if admin_user.role == UserRole.ADMIN:
        return {
            "brand_name": admin_user.brand_name if settings.BRANDING_ENABLED else None,
            "logo_url": admin_user.logo_url if settings.BRANDING_ENABLED else None,
            "custom_domain": admin_user.custom_domain,
            "custom_domain_status": admin_user.custom_domain_status,
        }

    if admin_user.role == UserRole.BROKER and admin_user.assigned_admin_id is not None:
        parent_admin = await User.get(admin_user.assigned_admin_id)
        if (
            parent_admin is not None
            and parent_admin.role == UserRole.ADMIN
        ):
            return {
                "brand_name": parent_admin.brand_name if settings.BRANDING_ENABLED else None,
                "logo_url": parent_admin.logo_url if settings.BRANDING_ENABLED else None,
                "custom_domain": parent_admin.custom_domain,
                "custom_domain_status": parent_admin.custom_domain_status,
            }

    # SUPER_ADMIN, top-level brokers under super-admin pool, anything else.
    return {"brand_name": None, "logo_url": None, "custom_domain": None, "custom_domain_status": None}

router = APIRouter(prefix="/auth", tags=["admin-auth"])

#: The broker and admin logins are separate pages over the same panel, each
#: installable as its own app. The lock lives in `authenticate` so it runs
#: after the password check and before a session is minted.
_PORTAL_ROLES = {
    "broker": {UserRole.BROKER},
    "admin": {UserRole.SUPER_ADMIN, UserRole.ADMIN},
}


def _client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "0.0.0.0"


@router.post(
    "/login",
    response_model=APIResponse[AdminTokenPair],
    status_code=status.HTTP_200_OK,
    dependencies=[rate_limit("auth")],
)
async def admin_login(payload: AdminLoginRequest, request: Request):
    pair: TokenPair = await auth_service.authenticate(
        identifier=payload.identifier,
        password=payload.password,
        two_fa_code=payload.two_fa_code,
        audience="admin",
        ip=_client_ip(request),
        user_agent=request.headers.get("user-agent"),
        allowed_roles=_PORTAL_ROLES.get(payload.portal) if payload.portal else None,
    )
    if pair.user.role not in {
        UserRole.SUPER_ADMIN.value,
        UserRole.ADMIN.value,
        UserRole.BROKER.value,
    }:
        raise InvalidCredentialsError()

    admin_user = await User.get(pair.user.id)
    if admin_user is None:
        raise InvalidCredentialsError()

    return APIResponse(
        data=AdminTokenPair(
            access_token=pair.access_token,
            refresh_token=pair.refresh_token,
            expires_in=pair.expires_in,
            admin=AdminUserOut(
                id=pair.user.id,
                user_code=pair.user.user_code,
                email=pair.user.email,
                full_name=pair.user.full_name,
                role=pair.user.role,
                last_login_at=None,
                is_demo=admin_user.is_demo,
                admin_permissions=admin_user.admin_permissions,
                pnl_share_pct=(
                    str(admin_user.pnl_share_pct)
                    if admin_user.pnl_share_pct is not None
                    else None
                ),
                broker_permissions=admin_user.broker_permissions,
                assigned_broker_id=(
                    str(admin_user.assigned_broker_id)
                    if admin_user.assigned_broker_id
                    else None
                ),
                **(await _branding_fields_for(admin_user)),
            ),
        )
    )


@router.post("/refresh", response_model=APIResponse[AdminTokenPair])
async def admin_refresh(payload: RefreshRequest):
    pair = await auth_service.refresh_tokens(payload.refresh_token)
    if pair.user.role not in {
        UserRole.SUPER_ADMIN.value,
        UserRole.ADMIN.value,
        UserRole.BROKER.value,
    }:
        raise InvalidCredentialsError()
    admin_user = await User.get(pair.user.id)
    if admin_user is None:
        raise InvalidCredentialsError()
    return APIResponse(
        data=AdminTokenPair(
            access_token=pair.access_token,
            refresh_token=pair.refresh_token,
            expires_in=pair.expires_in,
            admin=AdminUserOut(
                id=pair.user.id,
                user_code=pair.user.user_code,
                email=pair.user.email,
                full_name=pair.user.full_name,
                role=pair.user.role,
                is_demo=admin_user.is_demo,
                admin_permissions=admin_user.admin_permissions,
                pnl_share_pct=(
                    str(admin_user.pnl_share_pct)
                    if admin_user.pnl_share_pct is not None
                    else None
                ),
                broker_permissions=admin_user.broker_permissions,
                assigned_broker_id=(
                    str(admin_user.assigned_broker_id)
                    if admin_user.assigned_broker_id
                    else None
                ),
                **(await _branding_fields_for(admin_user)),
            ),
        )
    )


@router.post("/logout", response_model=APIResponse[OkResponse])
async def admin_logout(payload: LogoutRequest, admin: CurrentAdmin):
    from app.services.audit_service import log_event

    await auth_service.logout(refresh_token=payload.refresh_token, user_id=str(admin.id))
    await log_event(action=AuditAction.LOGOUT, entity_type="User", entity_id=admin.id, actor_id=admin.id)
    return APIResponse(data=OkResponse(message="Admin logged out"))


class BrokerDemoRegisterRequest(BaseModel):
    full_name: str = Field(min_length=2, max_length=128)
    email: EmailStr
    mobile: str = Field(pattern=r"^[6-9]\d{9}$")
    password: str = Field(min_length=8)


@router.post(
    "/broker-demo-register",
    response_model=APIResponse[AdminTokenPair],
    status_code=status.HTTP_201_CREATED,
    dependencies=[rate_limit("auth")],
)
async def broker_demo_register(payload: BrokerDemoRegisterRequest, request: Request):
    """PUBLIC broker demo signup. Mints a personal DEMO BROKER (platform pool,
    under the super-admin) pre-funded with 🪙50,00,000 virtual float, and logs in
    to the admin app immediately. The demo broker sees the full broker dashboard
    but CANNOT create users (→ "switch to real" popup); converting to real zeroes
    the wallet and unlocks user creation."""
    from app.services import demo_service

    broker = await demo_service.create_demo_broker(
        email=payload.email,
        mobile=payload.mobile,
        password=payload.password,
        full_name=payload.full_name,
    )
    fresh = await User.get(broker.id) or broker
    pair = await auth_service.mint_login_pair(
        fresh,
        ip=_client_ip(request),
        user_agent=request.headers.get("user-agent"),
        audience="admin",
    )
    return APIResponse(
        data=AdminTokenPair(
            access_token=pair.access_token,
            refresh_token=pair.refresh_token,
            expires_in=pair.expires_in,
            admin=AdminUserOut(
                id=str(fresh.id),
                user_code=fresh.user_code,
                email=fresh.email,
                full_name=fresh.full_name,
                role=fresh.role.value,
                last_login_at=None,
                is_demo=fresh.is_demo,
                admin_permissions=fresh.admin_permissions,
                broker_permissions=fresh.broker_permissions,
                pnl_share_pct=(
                    str(fresh.broker_pnl_share_pct)
                    if fresh.broker_pnl_share_pct is not None
                    else None
                ),
                assigned_broker_id=(
                    str(fresh.assigned_broker_id) if fresh.assigned_broker_id else None
                ),
                **(await _branding_fields_for(fresh)),
            ),
        ),
        message="Demo broker account ready. 🪙50,00,000 virtual float credited.",
    )


@router.get("/me", response_model=APIResponse[AdminUserOut])
async def admin_me(admin: CurrentAdmin):
    return APIResponse(
        data=AdminUserOut(
            id=str(admin.id),
            user_code=admin.user_code,
            email=admin.email,
            full_name=admin.full_name,
            role=admin.role.value,
            last_login_at=admin.last_login_at.isoformat() if admin.last_login_at else None,
            is_demo=admin.is_demo,
            admin_permissions=admin.admin_permissions,
            broker_permissions=admin.broker_permissions,
            pnl_share_pct=(
                str(admin.pnl_share_pct) if admin.pnl_share_pct is not None else None
            ),
            assigned_broker_id=(
                str(admin.assigned_broker_id) if admin.assigned_broker_id else None
            ),
            **(await _branding_fields_for(admin)),
        )
    )
