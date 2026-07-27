"""Super-admin operations on sub-admins and user assignment.

All mutations write an audit log entry. Pure data-layer; HTTP shaping lives
in [app.api.v1.admin.management](../api/v1/admin/management.py).
"""

from __future__ import annotations

import re
from decimal import Decimal
from typing import Any

from beanie import PydanticObjectId

from app.core.exceptions import ConflictError, NotFoundError, ValidationFailedError
from app.models.audit_log import AuditAction
from app.models.user import (
    AdminPermissions,
    User,
    UserRole,
    UserStatus,
)
from app.services import user_service
from app.services.audit_service import log_event
from app.utils.decimal_utils import to_decimal, to_decimal128


async def _get_sub_admin_or_404(sub_admin_id: str | PydanticObjectId) -> User:
    try:
        oid = PydanticObjectId(sub_admin_id)
    except Exception as e:
        raise ValidationFailedError("Invalid sub-admin id") from e
    sa = await User.get(oid)
    if sa is None or sa.role != UserRole.ADMIN:
        raise NotFoundError("Sub-admin not found")
    return sa


async def create_sub_admin(
    *,
    email: str,
    mobile: str,
    password: str,
    full_name: str,
    permissions: AdminPermissions,
    pnl_share_pct: Decimal,
    created_by: PydanticObjectId,
    brokerage_share_pct: Decimal | None = None,
    is_fixed_brokerage: bool = False,
    fixed_brokerage_unit: str | None = None,
    fixed_brokerage_rate: Decimal | None = None,
    no_self_brokerage: bool = False,
) -> User:
    if pnl_share_pct < 0 or pnl_share_pct > 100:
        raise ValidationFailedError("pnl_share_pct must be between 0 and 100")
    if brokerage_share_pct is not None and (brokerage_share_pct < 0 or brokerage_share_pct > 100):
        raise ValidationFailedError("brokerage_share_pct must be between 0 and 100")
    if is_fixed_brokerage:
        # The fixed rate + unit are set PER SEGMENT in the admin's Segment
        # settings → Brokerage (the create form no longer takes a flat
        # admin-level rate), so they're OPTIONAL here — only validate when
        # explicitly provided. account2_service defaults a missing unit to
        # per_crore.
        if fixed_brokerage_unit is not None and fixed_brokerage_unit not in ("per_lot", "per_crore"):
            raise ValidationFailedError("fixed_brokerage_unit must be per_lot|per_crore")
        if fixed_brokerage_rate is not None and fixed_brokerage_rate < 0:
            raise ValidationFailedError("fixed_brokerage_rate must be >= 0")

    sa = await user_service.create_user(
        email=email,
        mobile=mobile,
        password=password,
        full_name=full_name,
        role=UserRole.ADMIN,
        status=UserStatus.ACTIVE,
        created_by=created_by,
        # Sub-admin themselves are not assigned to anyone.
        assigned_admin_id=None,
    )
    sa.admin_permissions = permissions
    sa.pnl_share_pct = to_decimal128(pnl_share_pct)
    if brokerage_share_pct is not None:
        sa.admin_brokerage_share_pct = to_decimal128(brokerage_share_pct)
    if is_fixed_brokerage:
        sa.is_fixed_brokerage = True
        if fixed_brokerage_unit is not None:
            sa.fixed_brokerage_unit = fixed_brokerage_unit
        if fixed_brokerage_rate is not None:
            sa.fixed_brokerage_rate = to_decimal128(fixed_brokerage_rate)
    if no_self_brokerage:
        sa.no_self_brokerage = True

    # Copy the super-admin's AUTO-SETTLEMENT policy (pool on/off + the per-wallet
    # `kinds` map) onto the new admin so it starts identical to the SA — the
    # third global toggle alongside the segment + risk snapshot below. Segment &
    # risk are materialised into the new admin's own tables (snapshot_for_new_
    # admin); auto-settlement lives on the User doc, so copy it here. The SA can
    # still change the new admin's toggle afterwards; later SA edits don't
    # cascade (same snapshot policy). Default was `True`, so without this an
    # admin created while the SA had settlement OFF wrongly started ON.
    try:
        creator = await User.get(created_by)
        if creator is not None and creator.role == UserRole.SUPER_ADMIN:
            sa.pool_auto_settlement = bool(creator.pool_auto_settlement)
            sa.pool_auto_settlement_kinds = dict(creator.pool_auto_settlement_kinds or {})
    except Exception:  # noqa: BLE001 — never block admin creation on this copy
        import logging as _lg

        _lg.getLogger(__name__).exception(
            "auto_settlement_copy_failed_on_admin_create admin=%s", sa.id
        )
    await sa.save()

    # Snapshot the super-admin's current effective settings (segments
    # + risk) into the new admin's tier-tables so their settings page
    # opens populated instead of blank. The admin can edit freely from
    # there — their edits never bubble back to super-admin, and any
    # future super-admin edits do NOT cascade down. See
    # `settings_snapshot` module docstring for the policy.
    try:
        from app.services.settings_snapshot import snapshot_for_new_admin

        await snapshot_for_new_admin(sa.id, source_super_admin_id=created_by)
        # Account 2: freeze the per-segment fixed-brokerage table from the
        # just-baked effective brokerage, so a fixed admin earns from day one.
        if is_fixed_brokerage:
            from app.services.netting_service import seed_fixed_brokerage_rates

            await seed_fixed_brokerage_rates(sa)
    except Exception:
        # Snapshot is best-effort — a Mongo hiccup here must not roll
        # back the admin creation. The boot-time backfill will pick up
        # any miss on the next deploy.
        import logging as _lg

        _lg.getLogger(__name__).exception(
            "settings_snapshot_failed_on_admin_create admin=%s", sa.id
        )

    await log_event(
        action=AuditAction.SUB_ADMIN_CREATE,
        entity_type="User",
        entity_id=sa.id,
        actor_id=created_by,
        target_user_id=sa.id,
        new_values={
            "permissions": permissions.model_dump(),
            "pnl_share_pct": str(pnl_share_pct),
        },
    )
    return sa


async def update_sub_admin(
    sub_admin_id: str | PydanticObjectId,
    *,
    full_name: str | None,
    actor_id: PydanticObjectId,
) -> User:
    sa = await _get_sub_admin_or_404(sub_admin_id)
    changes: dict[str, Any] = {}
    if full_name is not None and full_name.strip() and full_name != sa.full_name:
        changes["full_name"] = full_name.strip()
        sa.full_name = full_name.strip()
    if changes:
        await sa.save()
        await log_event(
            action=AuditAction.SUB_ADMIN_UPDATE,
            entity_type="User",
            entity_id=sa.id,
            actor_id=actor_id,
            target_user_id=sa.id,
            new_values=changes,
        )
    return sa


async def update_permissions(
    sub_admin_id: str | PydanticObjectId,
    permissions: AdminPermissions,
    actor_id: PydanticObjectId,
) -> User:
    sa = await _get_sub_admin_or_404(sub_admin_id)
    old = sa.admin_permissions.model_dump() if sa.admin_permissions else None
    sa.admin_permissions = permissions
    await sa.save()
    await log_event(
        action=AuditAction.SUB_ADMIN_PERMS_UPDATE,
        entity_type="User",
        entity_id=sa.id,
        actor_id=actor_id,
        target_user_id=sa.id,
        old_values={"permissions": old},
        new_values={"permissions": permissions.model_dump()},
    )
    return sa


async def set_admin_fixed_brokerage(
    sub_admin_id: str | PydanticObjectId,
    is_fixed: bool,
    unit: str | None,
    rate: Decimal | None,
    actor_id: PydanticObjectId,
) -> User:
    """Toggle an admin's fixed-brokerage flag (editable anytime, incl. from the
    3-dot Edit). The actual rate is now PER-SEGMENT (frozen from the admin's
    Segment settings → Brokerage), so `unit`/`rate` are legacy/optional here.
    is_fixed=False clears it back to the normal % flow."""
    sa = await _get_sub_admin_or_404(sub_admin_id)
    old = {
        "is_fixed_brokerage": sa.is_fixed_brokerage,
        "fixed_brokerage_unit": sa.fixed_brokerage_unit,
        "fixed_brokerage_rate": str(sa.fixed_brokerage_rate) if sa.fixed_brokerage_rate is not None else None,
    }
    if is_fixed:
        sa.is_fixed_brokerage = True
        # Legacy single rate only if explicitly supplied (per-segment is primary).
        if unit in ("per_lot", "per_crore"):
            sa.fixed_brokerage_unit = unit
        if rate is not None and to_decimal(rate) >= 0:
            sa.fixed_brokerage_rate = to_decimal128(to_decimal(rate))
        await sa.save()
        # Seed the per-segment frozen table from the admin's current effective
        # brokerage if it isn't set yet, so Account 2 has data the moment they
        # switch this admin to fixed. (No-op if already seeded.)
        from app.services.netting_service import seed_fixed_brokerage_rates

        await seed_fixed_brokerage_rates(sa)
    else:
        sa.is_fixed_brokerage = False
        sa.fixed_brokerage_unit = None
        sa.fixed_brokerage_rate = None
        await sa.save()
    await log_event(
        action=AuditAction.SUB_ADMIN_PNL_SHARE_UPDATE,
        entity_type="User",
        entity_id=sa.id,
        actor_id=actor_id,
        target_user_id=sa.id,
        old_values=old,
        new_values={
            "is_fixed_brokerage": sa.is_fixed_brokerage,
            "fixed_brokerage_unit": sa.fixed_brokerage_unit,
            "fixed_brokerage_rate": str(sa.fixed_brokerage_rate) if sa.fixed_brokerage_rate is not None else None,
        },
    )
    return sa


async def set_admin_expiry_edit_allowed(
    sub_admin_id: str | PydanticObjectId,
    allowed: bool,
    actor_id: PydanticObjectId,
) -> User:
    """Super-admin toggles whether this admin may edit its OWN expiry / option-
    chain settings. Default OFF — the admin inherits what the super-admin set and
    can't override until unlocked here."""
    sa = await _get_sub_admin_or_404(sub_admin_id)
    old = bool(getattr(sa, "can_edit_expiry_settings", False))
    sa.can_edit_expiry_settings = bool(allowed)
    await sa.save()
    await log_event(
        action=AuditAction.SUB_ADMIN_PNL_SHARE_UPDATE,
        entity_type="User",
        entity_id=sa.id,
        actor_id=actor_id,
        target_user_id=sa.id,
        old_values={"can_edit_expiry_settings": old},
        new_values={"can_edit_expiry_settings": sa.can_edit_expiry_settings},
    )
    return sa


async def set_admin_trading_referral_enabled(
    sub_admin_id: str | PydanticObjectId,
    enabled: bool,
    actor_id: PydanticObjectId,
) -> User:
    """Super-admin switches TRADING-REFERRAL income ON/OFF for this admin's WHOLE
    client base at once. Default ON — flip OFF and no client whose owning admin is
    this row accrues or earns a trading-referral reward until it's switched back
    on. Does not touch the games (◉ coin) referral, only the trading reward."""
    sa = await _get_sub_admin_or_404(sub_admin_id)
    old = bool(getattr(sa, "trading_referral_enabled", True))
    sa.trading_referral_enabled = bool(enabled)
    await sa.save()
    await log_event(
        action=AuditAction.SUB_ADMIN_PNL_SHARE_UPDATE,
        entity_type="User",
        entity_id=sa.id,
        actor_id=actor_id,
        target_user_id=sa.id,
        old_values={"trading_referral_enabled": old},
        new_values={"trading_referral_enabled": sa.trading_referral_enabled},
    )
    return sa


async def set_pnl_share(
    sub_admin_id: str | PydanticObjectId,
    pct: Decimal,
    actor_id: PydanticObjectId,
    brokerage_share_pct: Decimal | None = None,
) -> User:
    """Update the admin's PnL share % (and optionally its separate brokerage
    share %) — editable anytime by the super-admin."""
    pct_dec = to_decimal(pct)
    if pct_dec < 0 or pct_dec > 100:
        raise ValidationFailedError("pct must be between 0 and 100")
    sa = await _get_sub_admin_or_404(sub_admin_id)
    old = str(sa.pnl_share_pct) if sa.pnl_share_pct is not None else None
    old_bkg = str(sa.admin_brokerage_share_pct) if sa.admin_brokerage_share_pct is not None else None
    sa.pnl_share_pct = to_decimal128(pct_dec)
    new_vals = {"pnl_share_pct": str(pct_dec)}
    if brokerage_share_pct is not None:
        bkg = to_decimal(brokerage_share_pct)
        if bkg < 0 or bkg > 100:
            raise ValidationFailedError("brokerage_share_pct must be between 0 and 100")
        sa.admin_brokerage_share_pct = to_decimal128(bkg)
        new_vals["admin_brokerage_share_pct"] = str(bkg)
    await sa.save()
    await log_event(
        action=AuditAction.SUB_ADMIN_PNL_SHARE_UPDATE,
        entity_type="User",
        entity_id=sa.id,
        actor_id=actor_id,
        target_user_id=sa.id,
        old_values={"pnl_share_pct": old, "admin_brokerage_share_pct": old_bkg},
        new_values=new_vals,
    )
    return sa


async def block_sub_admin(
    sub_admin_id: str | PydanticObjectId, actor_id: PydanticObjectId
) -> User:
    sa = await _get_sub_admin_or_404(sub_admin_id)
    sa.status = UserStatus.BLOCKED
    await sa.save()
    # Force-logout every active session of the blocked sub-admin (same
    # rationale as the client block path in admin/users.py).
    from app.services import auth_service as _auth

    await _auth.revoke_user_sessions(sa)
    await log_event(
        action=AuditAction.BLOCK,
        entity_type="User",
        entity_id=sa.id,
        actor_id=actor_id,
        target_user_id=sa.id,
        metadata={"kind": "SUB_ADMIN"},
    )
    return sa


async def unblock_sub_admin(
    sub_admin_id: str | PydanticObjectId, actor_id: PydanticObjectId
) -> User:
    sa = await _get_sub_admin_or_404(sub_admin_id)
    sa.status = UserStatus.ACTIVE
    sa.failed_login_count = 0
    sa.locked_until = None
    await sa.save()
    await log_event(
        action=AuditAction.UNBLOCK,
        entity_type="User",
        entity_id=sa.id,
        actor_id=actor_id,
        target_user_id=sa.id,
        metadata={"kind": "SUB_ADMIN"},
    )
    return sa


async def list_sub_admins(
    *, status: str | None = None, q: str | None = None, page: int = 1, page_size: int = 20
) -> tuple[list[User], int]:
    query: dict[str, Any] = {"role": UserRole.ADMIN.value}
    if status:
        query["status"] = status
    if q:
        regex = re.compile(re.escape(q.strip()), re.IGNORECASE)
        query["$or"] = [
            {"email": regex},
            {"mobile": regex},
            {"user_code": regex},
            {"full_name": regex},
        ]
    total = await User.find(query).count()
    rows = (
        await User.find(query)
        .sort("-created_at")
        .skip((page - 1) * page_size)
        .limit(page_size)
        .to_list()
    )
    return rows, total


async def count_assigned_users(sub_admin_id: PydanticObjectId) -> int:
    """Trading-client count for a sub-admin's pool — matches exactly what
    that admin sees on their own dashboard / accounts (the comprehensive
    scoped set: directly-assigned clients PLUS the whole broker subtree,
    with admin / broker / sub-broker LOGIN rows excluded).

    Was a flat ``{assigned_admin_id}`` count that also counted the admin's
    broker / sub-broker login accounts, so the super-admin's sub-admin
    list showed a larger number (e.g. 141) than the admin's own dashboard
    (122). Now delegates to the shared scope helper so all views agree.
    """
    from app.core.dependencies import count_admin_pool_clients

    return await count_admin_pool_clients(sub_admin_id)


async def count_assigned_brokers(sub_admin_id: PydanticObjectId) -> int:
    """Broker + sub-broker LOGIN accounts under a sub-admin — shown as a
    separate column from the trading-client count on the sub-admins list."""
    from app.core.dependencies import count_admin_pool_brokers

    return await count_admin_pool_brokers(sub_admin_id)


async def list_assigned_users(
    sub_admin_id: str | PydanticObjectId,
    *,
    page: int = 1,
    page_size: int = 50,
) -> tuple[list[User], int]:
    try:
        oid = PydanticObjectId(sub_admin_id)
    except Exception as e:
        raise ValidationFailedError("Invalid sub-admin id") from e
    # Comprehensive client scope (directly-assigned + whole broker
    # subtree, admin/broker login rows excluded, CLOSED soft-deleted rows
    # excluded) so this drill-in list and its row count match the sub-
    # admin's own dashboard / accounts and the "USERS" number on the sub-
    # admins list (see count_assigned_users).
    from app.core.dependencies import _NON_CLIENT_ROLES, _admin_pool_clause
    from app.models.user import UserStatus

    clause = await _admin_pool_clause(oid)
    query = {
        **clause,
        "role": {"$nin": _NON_CLIENT_ROLES},
        "status": {"$ne": UserStatus.CLOSED.value},
    }
    total = await User.find(query).count()
    rows = (
        await User.find(query)
        .sort("-created_at")
        .skip((page - 1) * page_size)
        .limit(page_size)
        .to_list()
    )
    return rows, total


async def reassign_user(
    user_id: str | PydanticObjectId,
    new_sub_admin_id: str | PydanticObjectId | None,
    actor_id: PydanticObjectId,
) -> User:
    """Move a user into a sub-admin's pool, or back to super-admin (None)."""
    target = await user_service.get_user_or_404(user_id)
    if target.role in {UserRole.SUPER_ADMIN, UserRole.ADMIN}:
        raise ConflictError("Cannot reassign an admin-role user")

    new_oid: PydanticObjectId | None = None
    if new_sub_admin_id is not None:
        sa = await _get_sub_admin_or_404(new_sub_admin_id)
        new_oid = sa.id

    old = str(target.assigned_admin_id) if target.assigned_admin_id else None
    target.assigned_admin_id = new_oid
    # Stamp transfer telemetry so the destination dashboard can render
    # a "Transferred" badge and the audit trail of last-owner-change is
    # readable without joining audit_logs.
    from app.utils.time_utils import now_utc as _now_utc

    target.last_transferred_at = _now_utc()
    target.last_transferred_by = actor_id
    await target.save()

    # If the target is a BROKER, propagate the new assigned_admin_id
    # to its entire subtree (sub-brokers + client-tier users below).
    # Without this the destination admin's dashboard kept showing the
    # broker but none of its downline — operator-reported "super-admin
    # se transfer kiye gaye users admin ke cards me count nahi ho rahe".
    if target.role == UserRole.BROKER:
        try:
            coll = User.get_motor_collection()
            await coll.update_many(
                {"broker_ancestry": target.id},
                {"$set": {"assigned_admin_id": new_oid}},
            )
        except Exception:
            pass

    # Cache-bust the per-user netting + risk caches — the resolver reads
    # `assigned_admin_id` LIVE to pick the right sub-admin / super-admin
    # segment override, but the resolved settings are memoised in Redis
    # for 5 min. Without an explicit purge the user would keep trading
    # under the OLD owner's lot caps / margins / commissions for up to
    # CACHE_TTL after the transfer commits. User-flagged: "transfer
    # ke baad us user ki segment setting jis admin ne kiya hai uski
    # work karegi ki nahi?".
    try:
        from app.core.redis_client import cache_delete_pattern

        await cache_delete_pattern(f"netting_eff:{target.id}:*")
        await cache_delete_pattern(f"risk:{target.id}")
    except Exception:
        # Cache miss is harmless — settings will re-resolve on the
        # next order. Don't fail the transfer over Redis hiccups.
        pass
    await log_event(
        action=AuditAction.USER_REASSIGN,
        entity_type="User",
        entity_id=target.id,
        actor_id=actor_id,
        target_user_id=target.id,
        old_values={"assigned_admin_id": old},
        new_values={"assigned_admin_id": str(new_oid) if new_oid else None},
    )
    return target


async def bulk_reassign(
    user_ids: list[str],
    new_sub_admin_id: str | PydanticObjectId | None,
    actor_id: PydanticObjectId,
) -> dict[str, Any]:
    moved = 0
    failed: list[dict[str, str]] = []
    for uid in user_ids:
        try:
            await reassign_user(uid, new_sub_admin_id, actor_id)
            moved += 1
        except Exception as e:
            failed.append({"user_id": uid, "error": str(e)})
    return {"moved": moved, "failed": failed}


async def delete_sub_admin(
    sub_admin_id: PydanticObjectId,
    *,
    actor_id: PydanticObjectId,
) -> None:
    """Permanently delete a sub-admin. Reassigns their users back to the
    platform pool (assigned_admin_id = None) so they don't become orphans.
    Any ACTIVE / PAUSED P&L sharing agreements for this admin are ENDed to
    preserve history. Caller must be SUPER_ADMIN (gated at the router level).
    """
    sa = await _get_sub_admin_or_404(sub_admin_id)

    # Reassign assigned users back to platform pool
    coll = User.get_motor_collection()
    await coll.update_many(
        {"assigned_admin_id": sa.id},
        {"$set": {"assigned_admin_id": None}},
    )

    # End any active P&L sharing agreements for this admin (preserve history)
    from app.models.pnl_sharing import AgreementStatus, PnlSharingAgreement
    from app.utils.time_utils import now_utc

    await PnlSharingAgreement.find(
        PnlSharingAgreement.admin_id == sa.id,
        PnlSharingAgreement.status != AgreementStatus.ENDED,
    ).update_many({
        "$set": {
            "status": AgreementStatus.ENDED.value,
            "effective_until": now_utc(),
            "last_modified_by": actor_id,
        }
    })

    await sa.delete()

    await log_event(
        action=AuditAction.DELETE,
        entity_type="User",
        entity_id=sa.id,
        actor_id=actor_id,
        target_user_id=sa.id,
        new_values={
            "user_code": sa.user_code,
            "email": sa.email,
            "role": "ADMIN",
        },
    )


async def reset_password(
    sub_admin_id: PydanticObjectId,
    new_password: str,
    *,
    actor_id: PydanticObjectId,
) -> User:
    """Reset a sub-admin's password to a new value chosen by super-admin.
    Sub-admin should change it on next login (no flag enforced in Phase 1)."""
    from app.core.security import hash_password

    sa = await _get_sub_admin_or_404(sub_admin_id)
    sa.password_hash = hash_password(new_password)
    await sa.save()
    # Force-logout so the old password's sessions die immediately.
    from app.services import auth_service as _auth

    await _auth.revoke_user_sessions(sa)

    await log_event(
        action=AuditAction.PASSWORD_RESET,
        entity_type="User",
        entity_id=sa.id,
        actor_id=actor_id,
        target_user_id=sa.id,
    )
    return sa
