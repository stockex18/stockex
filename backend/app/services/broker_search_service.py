"""Public broker directory for the signup broker-picker + the super-admin
visibility control (which admins' brokers are searchable).

Shared by the PUBLIC user endpoint (`GET /user/auth/brokers`) and the
super-admin settings endpoints, and by the signup / profile-change flows that
must validate a picked broker.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from beanie import PydanticObjectId

from app.models.platform_setting import PlatformSetting, SettingType
from app.models.user import User, UserRole, UserStatus

logger = logging.getLogger(__name__)

# JSON PlatformSetting: list of ADMIN user-ids whose brokers are HIDDEN from
# the signup broker-search. Default [] = every admin's brokers are searchable.
HIDDEN_ADMINS_KEY = "broker_search.hidden_admin_ids"

#: The BROKER signup's own "Choose your admin" picker. A separate list from
#: the one above on purpose: an admin can be right for a client to find a
#: broker under and wrong to hand a brand-new broker to, and the operator
#: wants those two decided separately.
HIDDEN_SIGNUP_ADMINS_KEY = "broker_search.hidden_signup_admin_ids"

_DESCRIPTIONS = {
    HIDDEN_ADMINS_KEY: "Admin ids whose brokers are HIDDEN from the signup broker-search.",
    HIDDEN_SIGNUP_ADMINS_KEY: "Admin ids HIDDEN from the broker signup's Choose-your-admin picker.",
}


async def get_hidden_admin_ids(key: str = HIDDEN_ADMINS_KEY) -> list[str]:
    row = await PlatformSetting.find_one(PlatformSetting.setting_key == key)
    if row is None or not isinstance(row.setting_value, list):
        return []
    return [str(x) for x in row.setting_value]


async def get_hidden_signup_admin_ids() -> list[str]:
    """Admins kept out of the BROKER signup's admin picker."""
    return await get_hidden_admin_ids(HIDDEN_SIGNUP_ADMINS_KEY)


async def set_hidden_signup_admin_ids(ids: list[str]) -> list[str]:
    return await set_hidden_admin_ids(ids, key=HIDDEN_SIGNUP_ADMINS_KEY)


async def set_hidden_admin_ids(ids: list[str], key: str = HIDDEN_ADMINS_KEY) -> list[str]:
    """Upsert one of the hidden-admin lists (validated, deduped)."""
    clean: list[str] = []
    seen: set[str] = set()
    for x in ids or []:
        s = str(x).strip()
        if not s or s in seen:
            continue
        try:
            PydanticObjectId(s)  # reject junk ids
        except Exception:
            continue
        seen.add(s)
        clean.append(s)

    row = await PlatformSetting.find_one(PlatformSetting.setting_key == key)
    if row is None:
        row = PlatformSetting(
            setting_key=key,
            setting_value=clean,
            setting_type=SettingType.JSON,
            category="general",
            is_public=False,
            description=_DESCRIPTIONS.get(key, "Hidden admin ids."),
        )
        await row.insert()
    else:
        row.setting_value = clean
        await row.save()
    return clean


async def _hidden_set(key: str = HIDDEN_ADMINS_KEY) -> set[PydanticObjectId]:
    out: set[PydanticObjectId] = set()
    for x in await get_hidden_admin_ids(key):
        try:
            out.add(PydanticObjectId(x))
        except Exception:
            continue
    return out


async def search_brokers(q: str | None = None, limit: int = 30) -> list[dict[str, Any]]:
    """Active brokers + sub-brokers across all admins (minus hidden admins),
    matched by city / full_name / user_code. Platform-pool brokers (no owning
    admin) are always shown."""
    hidden = await _hidden_set()
    query: dict[str, Any] = {
        "role": UserRole.BROKER.value,
        "status": UserStatus.ACTIVE.value,
    }
    needle = (q or "").strip()
    if needle:
        rx = re.compile(re.escape(needle), re.IGNORECASE)
        query["$or"] = [{"city": rx}, {"full_name": rx}, {"user_code": rx}]

    rows = await User.find(query).limit(200).to_list()
    rows = [r for r in rows if not (r.assigned_admin_id and r.assigned_admin_id in hidden)]
    rows.sort(key=lambda r: ((r.city or "￿").lower(), (r.full_name or "").lower()))
    rows = rows[:limit]

    admin_ids = {r.assigned_admin_id for r in rows if r.assigned_admin_id}
    admins: dict[str, str] = {}
    if admin_ids:
        for a in await User.find({"_id": {"$in": list(admin_ids)}}).to_list():
            admins[str(a.id)] = a.full_name or a.user_code

    return [
        {
            "id": str(r.id),
            "user_code": r.user_code,
            "full_name": r.full_name,
            "city": r.city,
            "admin_name": admins.get(str(r.assigned_admin_id)) if r.assigned_admin_id else "Platform",
        }
        for r in rows
    ]


async def resolve_active_visible_broker(broker_id: str) -> User | None:
    """Return the active, non-hidden BROKER for `broker_id`, else None.
    Used by signup + profile-change to validate the picked broker."""
    try:
        b = await User.get(PydanticObjectId(str(broker_id)))
    except Exception:
        return None
    if b is None or b.role != UserRole.BROKER or b.status != UserStatus.ACTIVE:
        return None
    hidden = await _hidden_set()
    if b.assigned_admin_id and b.assigned_admin_id in hidden:
        return None
    return b

# ── Admin directory for the BROKER signup picker ─────────────────────
async def search_admins(q: str | None = None, limit: int = 30) -> list[dict[str, Any]]:
    """ADMINs a broker may sign up under — active, minus the hidden ones.

    Its OWN list, not the client-side broker directory's: the super admin
    decides separately which admins a brand-new broker may land under.
    """
    hidden = await _hidden_set(HIDDEN_SIGNUP_ADMINS_KEY)
    rows = await User.find(
        {"role": UserRole.ADMIN.value, "status": UserStatus.ACTIVE.value}
    ).to_list()
    rows = [r for r in rows if r.id not in hidden]
    term = (q or "").strip()
    if term:
        rx = re.compile(re.escape(term), re.IGNORECASE)
        rows = [
            r
            for r in rows
            if rx.search(r.full_name or "")
            or rx.search(r.user_code or "")
            or rx.search(getattr(r, "city", "") or "")
        ]
    rows.sort(key=lambda r: (r.full_name or r.user_code or "").lower())
    return [
        {
            "id": str(r.id),
            "full_name": r.full_name,
            "user_code": r.user_code,
            "city": getattr(r, "city", None),
        }
        for r in rows[: max(1, int(limit or 30))]
    ]


async def resolve_signup_admin(admin_id: str) -> User | None:
    """The active, non-hidden ADMIN for `admin_id`, else None. Mirrors
    `resolve_active_visible_broker` — the picker's list and what a signup is
    allowed to name must be the same set."""
    try:
        oid = PydanticObjectId(str(admin_id))
    except Exception:  # noqa: BLE001 — junk id resolves to nothing
        return None
    u = await User.get(oid)
    if u is None or u.role != UserRole.ADMIN or u.status != UserStatus.ACTIVE:
        return None
    if oid in await _hidden_set(HIDDEN_SIGNUP_ADMINS_KEY):
        return None
    return u
