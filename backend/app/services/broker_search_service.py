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
from app.services import geo_service
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


#: What a broker search is matching on. "all" is the default and the widest
#: net; the other two exist because the picker offers them as separate modes.
SEARCH_FIELDS: dict[str, list[str]] = {
    # A client usually knows a broker by the brand they trade under, not by
    # the name on their account, so the brand is searched alongside it.
    "all": ["city", "pincode", "broker_brand_name", "full_name", "user_code"],
    "city": ["city"],
    "pincode": ["pincode"],
}


# ── Nearest brokers ─────────────────────────────────────────────────────
#
# "Agar us city ka broker nahi hai to jo sabse paas ho wo dikha dena, PIN code
# me bhi same flow." A client who searches a place with no broker in it should
# be shown who is NEAREST, not an empty list that reads as "nobody serves you".
#
# The rules, so they are not rediscovered:
#   * exact matches always come first and are never displaced;
#   * with NO exact match, the nearest few are shown however far they are — the
#     alternative is an empty screen;
#   * WITH exact matches, only genuinely close extras are added, so a client in
#     Mumbai is not offered a broker in Delhi beside the one in Mumbai.
NEARBY_MAX = 5
NEARBY_RADIUS_KM = 150
#: A PIN shares its first digit with a broad region of India, its first two
#: with a state-sized area, its first three with a sorting district. That is the
#: only notion of "near" a PIN carries without a PIN-to-coordinates table.
_PIN_AREA = {3: "Same area", 2: "Same region", 1: "Same part of India"}


def rank_nearby_by_city(
    target: "geo_service.City",
    candidates: list[tuple[Any, str | None]],
    *,
    any_exact: bool,
) -> list[tuple[Any, float]]:
    """(broker, km) nearest first. `candidates` are (broker, the city text they
    typed). A broker whose city cannot be resolved is left out: ranking them by
    a guess would be worse than not ranking them."""
    scored: list[tuple[Any, float]] = []
    for broker, city_text in candidates:
        city = geo_service.resolve(city_text, allow_prefix=False)
        if city is None:
            continue
        scored.append((broker, geo_service.distance_km(target, city)))
    scored.sort(key=lambda t: t[1])
    if any_exact:
        scored = [t for t in scored if t[1] <= NEARBY_RADIUS_KM]
    return scored[:NEARBY_MAX]


def common_prefix_len(a: str, b: str) -> int:
    n = 0
    for x, y in zip(a, b):
        if x != y:
            break
        n += 1
    return n


def rank_nearby_by_pin(
    needle_digits: str,
    candidates: list[tuple[Any, str | None]],
    *,
    any_exact: bool,
) -> list[tuple[Any, int]]:
    """(broker, shared-prefix length) closest first. A longer shared PIN prefix
    is a smaller area; ties are broken by how close the numbers are, because
    neighbouring sorting districts have neighbouring numbers."""
    padded = (needle_digits + "000000")[:6]
    scored: list[tuple[Any, int, int]] = []
    for broker, pin in candidates:
        pin = (pin or "").strip()
        if len(pin) != 6 or not pin.isdigit():
            continue
        scored.append((broker, common_prefix_len(needle_digits, pin), abs(int(pin) - int(padded))))
    # Anything sharing the WHOLE typed prefix is already an exact match.
    scored = [t for t in scored if t[1] < len(needle_digits)]
    floor = 2 if any_exact else 1
    scored = [t for t in scored if t[1] >= floor]
    scored.sort(key=lambda t: (-t[1], t[2]))
    return [(b, cp) for b, cp, _ in scored[:NEARBY_MAX]]


async def _nearby(
    needle: str, by: str, exact: list[Any], base: dict[str, Any], hidden: set
) -> list[dict[str, Any]]:
    """Extra rows (as dicts of extra fields keyed by user id) for a search that
    deserves them, else []."""
    digits = "".join(c for c in needle if c.isdigit())
    is_pin_query = needle.replace(" ", "").isdigit() and len(digits) >= 3
    if by == "pincode":
        if len(digits) < 3:
            return []
        mode = "pin"
    elif by == "city":
        mode = "city"
    else:  # "all": a rescue only, so it never competes with real name/code hits
        if exact:
            return []
        mode = "pin" if is_pin_query else "city"

    exact_ids = {r.id for r in exact}
    pool = await User.find(base).limit(500).to_list()
    pool = [
        r for r in pool
        if r.id not in exact_ids and not (r.assigned_admin_id and r.assigned_admin_id in hidden)
    ]
    if not pool:
        return []

    if mode == "pin":
        ranked = rank_nearby_by_pin(
            digits, [(r, getattr(r, "pincode", None)) for r in pool], any_exact=bool(exact)
        )
        return [
            {"user": r, "nearby": True, "distance_km": None, "area": _PIN_AREA.get(cp, "Nearby"), "near": digits}
            for r, cp in ranked
        ]

    target = geo_service.resolve(needle, allow_prefix=(by == "city"))
    if target is None:
        return []
    ranked = rank_nearby_by_city(
        target, [(r, r.city) for r in pool], any_exact=bool(exact)
    )
    return [
        {
            "user": r, "nearby": True,
            # Under 5 km is the same city under another name (Bombay for Mumbai).
            "distance_km": 0 if km < 5 else int(round(km)),
            "area": None, "near": target.name,
        }
        for r, km in ranked
    ]


async def search_brokers(
    q: str | None = None, limit: int = 30, by: str = "all"
) -> list[dict[str, Any]]:
    """Active brokers + sub-brokers across all admins (minus hidden admins).
    Platform-pool brokers (no owning admin) are always shown.

    `by` picks which fields the needle is matched against — see
    `SEARCH_FIELDS`. The signup picker offers All / City / PIN code as three
    modes rather than one box, because a bare number means different things
    in each: typed into "All" it would also hit a user_code, and a client who
    knows their PIN wants the brokers near them, not a code that happens to
    contain those digits.

    An EMPTY needle is not an error in any mode — it lists everyone, which is
    the picker's "all brokers" state. A client who does not know a city or a
    PIN still has to be able to browse.

    PIN matching is a PREFIX match, not a substring one: "5600" should find
    560001 and 560034, which share a locality, and must not find 125600,
    which is a different state entirely.
    """
    hidden = await _hidden_set()
    base: dict[str, Any] = {
        "role": UserRole.BROKER.value,
        "status": UserStatus.ACTIVE.value,
    }
    query: dict[str, Any] = dict(base)
    needle = (q or "").strip()
    if needle:
        fields = SEARCH_FIELDS.get(by, SEARCH_FIELDS["all"])
        esc = re.escape(needle)
        query["$or"] = [
            {f: re.compile(("^" + esc) if f == "pincode" else esc, re.IGNORECASE)}
            for f in fields
        ]

    rows = await User.find(query).limit(200).to_list()
    rows = [r for r in rows if not (r.assigned_admin_id and r.assigned_admin_id in hidden)]
    rows.sort(key=lambda r: ((r.city or "￿").lower(), (r.full_name or "").lower()))
    rows = rows[:limit]

    extras: list[dict[str, Any]] = []
    if needle:
        try:
            extras = await _nearby(needle, by, rows, base, hidden)
        except Exception:  # noqa: BLE001 — never lose the real answer to the extra one
            logger.warning("broker_nearby_failed q=%r by=%s", needle, by, exc_info=True)

    admin_ids = {r.assigned_admin_id for r in rows if r.assigned_admin_id}
    admin_ids |= {e["user"].assigned_admin_id for e in extras if e["user"].assigned_admin_id}
    admins: dict[str, str] = {}
    if admin_ids:
        for a in await User.find({"_id": {"$in": list(admin_ids)}}).to_list():
            admins[str(a.id)] = a.full_name or a.user_code

    def _row(r: Any, **extra: Any) -> dict[str, Any]:
        return {
            "id": str(r.id),
            "user_code": r.user_code,
            "full_name": r.full_name,
            "city": r.city,
            "pincode": getattr(r, "pincode", None),
            # What the client is shown FIRST. `full_name` stays in the payload
            # so the picker can still say whose brand it is.
            "brand_name": getattr(r, "broker_brand_name", None),
            "admin_name": admins.get(str(r.assigned_admin_id)) if r.assigned_admin_id else "Platform",
            # Not a match for what was typed, but the closest there is.
            "nearby": False,
            "distance_km": None,
            "area": None,
            "near": None,
            **extra,
        }

    out = [_row(r) for r in rows]
    out += [
        _row(e["user"], nearby=True, distance_km=e["distance_km"], area=e["area"], near=e["near"])
        for e in extras
    ]
    return out


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
