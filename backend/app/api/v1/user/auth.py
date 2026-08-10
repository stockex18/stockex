"""User auth endpoints — register, login, refresh, logout, 2FA, password reset."""

from __future__ import annotations

from fastapi import APIRouter, Request, status

from app.core.dependencies import CurrentUser
from app.core.exceptions import (
    InvalidCredentialsError,
    NotFoundError,
    ValidationFailedError,
)
from app.core.config import settings
from app.core.rate_limit import rate_limit
from app.models.audit_log import AuditAction
from app.models.user import UserRole, UserStatus
from app.schemas.auth import (
    AuthUserOut,
    ChangePasswordRequest,
    ForgotPasswordRequest,
    LoginRequest,
    LogoutRequest,
    OtpRequest,
    OtpVerifyRequest,
    RefreshRequest,
    RegisterRequest,
    ResetPasswordRequest,
    TokenPair,
    TwoFADisableRequest,
    TwoFAEnableRequest,
    TwoFASetupResponse,
)
from app.schemas.common import APIResponse, OkResponse
from app.services import auth_service, branding_service, referral_service, user_service
from app.services.audit_service import log_event
from app.utils.otp import issue_otp, verify_otp

router = APIRouter(prefix="/auth", tags=["user-auth"])


def _client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "0.0.0.0"


def _signup_host(request: Request) -> str:
    """Resolve the host the user is ACTUALLY on, for white-label signup
    attribution.

    The browser sits on the tenant's custom domain (e.g. ``stockcafe.live``)
    but the API lives on a shared host (``api.stockex.com``), so the
    request's ``Host`` header is the API host — NOT the tenant. The
    cross-origin fetch DOES carry ``Origin`` (and ``Referer``) = the tenant
    domain (the same signal the branding CORS middleware keys off), so we
    prefer those and fall back to ``Host`` only for same-origin / platform
    signups. Without this, EVERY custom-domain signup resolved to the API
    host, matched no admin, and silently landed in the super-admin pool
    instead of the domain owner's (the STOCKCAFE / stockcafe.live bug).
    """
    from urllib.parse import urlparse

    for header in ("origin", "referer"):
        raw = request.headers.get(header)
        if raw:
            try:
                host = urlparse(raw).hostname
            except Exception:
                host = None
            if host:
                return host.lower()
    return (request.headers.get("host") or "").split(":", 1)[0].lower()


async def _resolve_signup_placement(payload: RegisterRequest, request: Request | None = None):
    """Resolve (assigned_admin_id, assigned_broker_id, broker_ancestry,
    signup_origin, referrer) for a self-signup.

    Precedence:
      1. A user-to-user referral places the new user in the REFERRER's pool —
         copying the referrer's attribution verbatim covers all cases.
      2. Else an explicitly-picked broker (searchable by city at signup) is the
         AUTHORITATIVE hierarchy.
      3. Else broker selection is OPTIONAL — fall back to host / referral
         branding attribution (custom domain → that admin; otherwise the
         super-admin PLATFORM pool). A user can register WITHOUT choosing a
         broker; the super-admin can reassign them later.

    Shared by real + demo signup so a demo account already sits under the right
    owner, ready for conversion.
    """
    from app.services import branding_service, broker_search_service

    referrer = await referral_service.resolve_referrer(payload.referral_code)
    if referrer is not None:
        return (
            referrer.assigned_admin_id,
            referrer.assigned_broker_id,
            list(referrer.broker_ancestry or []),
            "REFERRAL",
            referrer,
        )
    broker = await broker_search_service.resolve_active_visible_broker(payload.broker_id or "")
    if broker is not None:
        return (
            broker.assigned_admin_id,
            broker.id,
            (broker.broker_ancestry or []) + [broker.id],
            "BROKER_PICK",
            referrer,
        )
    # No referrer, no broker picked → don't block signup. Attribute via host /
    # referral branding (custom domain → admin, else super-admin PLATFORM pool).
    host = request.headers.get("host") if request is not None else None
    admin_id, broker_id, ancestry, origin = await branding_service.resolve_signup_attribution(
        request_host=host, referral_code=payload.referral_code
    )
    return (admin_id, broker_id, list(ancestry or []), origin, referrer)


async def _create_signup_user(payload: RegisterRequest, *, is_demo: bool, request: Request):
    """Create a self-signup client user (real or demo) under the resolved
    broker, inherit the admin's pool auto-settlement default, link the referral,
    and audit. Returns the persisted User. Funding + token minting are the
    caller's job (real signup funds nothing; demo seeds virtual balance)."""
    assigned_admin_id, assigned_broker_id, broker_ancestry, signup_origin, referrer = (
        await _resolve_signup_placement(payload, request)
    )

    user = await user_service.create_user(
        email=payload.email,
        mobile=payload.mobile,
        password=payload.password,
        full_name=payload.full_name,
        status=UserStatus.ACTIVE,  # for self-register; admin flow can set PENDING
        assigned_admin_id=assigned_admin_id,
        assigned_broker_id=assigned_broker_id,
        broker_ancestry=broker_ancestry,
        signup_origin=signup_origin,
        is_demo=is_demo,
    )
    # A personal demo account is flagged DEMO so it is hidden from admin views
    # and blocked from deposits/withdrawals until it's converted to real.
    if is_demo:
        from app.models.user import AccountType

        user.account_type = AccountType.DEMO
        await user.save()
    # Inherit the owning admin's pool auto-settlement default — if the admin has
    # turned auto-settlement OFF for their pool, this new user is created OFF too
    # (negative balance + manual settlement), matching everyone else under them.
    try:
        from app.models.user import User as _User

        if assigned_admin_id:
            owner = await _User.get(assigned_admin_id)
            if owner is not None and not bool(getattr(owner, "pool_auto_settlement", True)):
                user.auto_settlement = False
                await user.save()
    except Exception:  # noqa: BLE001
        pass

    # Link the referral (sets referred_by + creates the Referral doc). Never
    # let a referral bookkeeping error fail the signup.
    if referrer is not None:
        try:
            user.referred_by = referrer.id
            await user.save()
            await referral_service.create_referral_on_signup(referrer, user)
        except Exception:  # noqa: BLE001
            pass
    await log_event(
        action=AuditAction.CREATE,
        entity_type="User",
        entity_id=user.id,
        actor_id=user.id,
        ip_address=_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    return user


@router.post(
    "/register",
    response_model=APIResponse[AuthUserOut],
    status_code=status.HTTP_201_CREATED,
    dependencies=[rate_limit("auth")],
)
async def register(payload: RegisterRequest, request: Request):
    user = await _create_signup_user(payload, is_demo=False, request=request)
    return APIResponse(
        data=AuthUserOut(
            id=str(user.id),
            user_code=user.user_code,
            email=user.email,
            mobile=user.mobile,
            full_name=user.full_name,
            role=user.role.value,
            status=user.status.value,
            is_demo=user.is_demo,
            two_fa_enabled=user.two_fa_enabled,
            must_change_password=user.must_change_password,
        ),
        message="Registered successfully. Please log in.",
    )


@router.get("/brokers", response_model=APIResponse[list], dependencies=[rate_limit("auth")])
async def list_brokers_for_signup(q: str | None = None, limit: int = 30):
    """PUBLIC broker directory for the signup broker-picker. Active brokers +
    sub-brokers across all admins (minus admins the super-admin hid from
    search), matched by city / name / user_code. No auth (pre-login)."""
    from app.services import broker_search_service

    rows = await broker_search_service.search_brokers(q=q, limit=min(max(int(limit or 30), 1), 50))
    return APIResponse(data=rows)


@router.post(
    "/login",
    response_model=APIResponse[TokenPair],
    dependencies=[rate_limit("auth")],
)
async def login(payload: LoginRequest, request: Request):
    pair = await auth_service.authenticate(
        identifier=payload.identifier,
        password=payload.password,
        two_fa_code=payload.two_fa_code,
        audience="user",
        ip=_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    await log_event(
        action=AuditAction.LOGIN,
        entity_type="User",
        entity_id=pair.user.id,
        actor_id=pair.user.id,
        ip_address=_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    return APIResponse(data=pair)


@router.post("/refresh", response_model=APIResponse[TokenPair])
async def refresh(payload: RefreshRequest):
    pair = await auth_service.refresh_tokens(payload.refresh_token)
    return APIResponse(data=pair)


@router.post("/logout", response_model=APIResponse[OkResponse])
async def logout(payload: LogoutRequest, user: CurrentUser, request: Request):
    # NEVER allow the all-sessions purge fallback on the SHARED demo account:
    # every demo visitor shares one user id, so a single demo logout without a
    # valid refresh_token would otherwise wipe EVERY concurrent demo user's
    # session. Demo logout only ever drops the one session it presents a token
    # for; the client clears its own local tokens regardless.
    await auth_service.logout(
        refresh_token=payload.refresh_token,
        user_id=str(user.id),
        allow_global_purge=not user.is_demo,
    )
    await log_event(
        action=AuditAction.LOGOUT,
        entity_type="User",
        entity_id=user.id,
        actor_id=user.id,
        ip_address=_client_ip(request),
    )
    return APIResponse(data=OkResponse(message="Logged out"))


# ── OTP (used by register, forgot-password) ──────────────────────────
@router.post(
    "/otp/request",
    response_model=APIResponse[OkResponse],
    dependencies=[rate_limit("auth")],
)
async def request_otp(payload: OtpRequest):
    if payload.purpose not in {"register", "login", "reset_password", "withdrawal"}:
        raise ValidationFailedError("Invalid OTP purpose")
    code = await issue_otp(payload.purpose, payload.identifier.lower().strip())  # type: ignore[arg-type]
    # TODO: wire SMS/email delivery here (SMTP_HOST / SMS_PROVIDER in .env)
    # NEVER expose the code in the response outside local development.
    if settings.APP_ENV == "development":
        msg = f"OTP sent (dev only: {code})"
    else:
        msg = "If a matching account exists, a code has been sent"
    return APIResponse(data=OkResponse(message=msg))


@router.post(
    "/otp/verify",
    response_model=APIResponse[OkResponse],
    dependencies=[rate_limit("auth")],
)
async def verify_otp_endpoint(payload: OtpVerifyRequest):
    ok = await verify_otp(payload.purpose, payload.identifier.lower().strip(), payload.code)  # type: ignore[arg-type]
    if not ok:
        raise InvalidCredentialsError("Invalid or expired OTP")
    return APIResponse(data=OkResponse(message="OTP verified"))


# ── Forgot / reset ────────────────────────────────────────────────────
@router.post(
    "/forgot-password",
    response_model=APIResponse[OkResponse],
    dependencies=[rate_limit("auth")],
)
async def forgot_password(payload: ForgotPasswordRequest):
    user = await user_service.find_by_identifier(payload.identifier)
    # Don't reveal whether the account exists
    if user:
        await issue_otp("reset_password", user.email)
    return APIResponse(data=OkResponse(message="If an account exists, a reset code has been sent"))


@router.post(
    "/reset-password",
    response_model=APIResponse[OkResponse],
    dependencies=[rate_limit("auth")],
)
async def reset_password(payload: ResetPasswordRequest, request: Request):
    user = await user_service.find_by_identifier(payload.identifier)
    if user is None:
        raise NotFoundError("Account not found")
    # Admin-tier accounts must use the admin panel password-reset flow.
    # Never allow the public user API to touch admin/broker passwords.
    if user.role in {UserRole.SUPER_ADMIN, UserRole.ADMIN, UserRole.BROKER}:
        raise NotFoundError("Account not found")
    ok = await verify_otp("reset_password", user.email, payload.otp)
    if not ok:
        raise InvalidCredentialsError("Invalid or expired reset code")
    await auth_service.reset_password(user, new_password=payload.new_password)
    await log_event(
        action=AuditAction.PASSWORD_RESET,
        entity_type="User",
        entity_id=user.id,
        actor_id=user.id,
        ip_address=_client_ip(request),
    )
    return APIResponse(data=OkResponse(message="Password updated"))


@router.post("/change-password", response_model=APIResponse[OkResponse])
async def change_password(payload: ChangePasswordRequest, user: CurrentUser, request: Request):
    await auth_service.change_password(user, current=payload.current_password, new=payload.new_password)
    await log_event(
        action=AuditAction.PASSWORD_CHANGE,
        entity_type="User",
        entity_id=user.id,
        actor_id=user.id,
        ip_address=_client_ip(request),
    )
    return APIResponse(data=OkResponse(message="Password updated"))


# ── 2FA ───────────────────────────────────────────────────────────────
@router.post("/2fa/setup", response_model=APIResponse[TwoFASetupResponse])
async def two_fa_setup(user: CurrentUser):
    secret, uri = await auth_service.begin_2fa_setup(user)
    return APIResponse(data=TwoFASetupResponse(secret=secret, provisioning_uri=uri))


@router.post("/2fa/enable", response_model=APIResponse[OkResponse])
async def two_fa_enable(payload: TwoFAEnableRequest, user: CurrentUser):
    backup = await auth_service.confirm_2fa(user, payload.code)
    return APIResponse(
        data=OkResponse(message=f"2FA enabled. Backup codes: {', '.join(backup)}"),
    )


@router.post("/2fa/disable", response_model=APIResponse[OkResponse])
async def two_fa_disable(payload: TwoFADisableRequest, user: CurrentUser):
    await auth_service.disable_2fa(user, password=payload.password, code=payload.code)
    return APIResponse(data=OkResponse(message="2FA disabled"))


# ── Demo login ────────────────────────────────────────────────────────
@router.post(
    "/demo",
    response_model=APIResponse[TokenPair],
    dependencies=[rate_limit("auth")],
)
async def demo_login(request: Request):
    """Log into the shared demo account pre-funded with 🪙5 Lakh virtual money.

    No signup required — returns a full JWT pair immediately. The shared demo
    account is flattened + re-funded to 🪙5,00,000 every 24h (demo_reset_loop).
    """
    pair = await auth_service.create_demo_session(
        ip=_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    return APIResponse(data=pair, message="Demo account ready. 🪙5,00,000 virtual balance credited.")


@router.post(
    "/demo-register",
    response_model=APIResponse[TokenPair],
    status_code=status.HTTP_201_CREATED,
    dependencies=[rate_limit("auth")],
)
async def demo_register(payload: RegisterRequest, request: Request):
    """Create the user's OWN demo account (their name / mobile / email / password
    + a chosen broker), pre-fund it with 🪙5,00,000 virtual money, and log in
    immediately.

    Unlike the shared ``/demo`` account, this is personal: its trades and balance
    are private, and it can later be CONVERTED into a real account
    (``POST /users/me/convert-to-real``) keeping the same login + broker while
    wiping the demo trades and zeroing the balance.
    """
    from app.models.transaction import TransactionType
    from app.services import wallet_service

    user = await _create_signup_user(payload, is_demo=True, request=request)
    await wallet_service.adjust(
        user.id,
        500_000,
        transaction_type=TransactionType.BONUS,
        narration="Demo account virtual credit",
    )
    # Re-fetch so the token pair's embedded user carries the DEMO flag/balance.
    from app.models.user import User as _User

    fresh = await _User.get(user.id) or user
    pair = await auth_service.mint_login_pair(
        fresh,
        ip=_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    return APIResponse(
        data=pair, message="Demo account ready. 🪙5,00,000 virtual balance credited."
    )
