"""User-domain operations — lookups, code generation, hierarchy walks."""

from __future__ import annotations

import secrets
from typing import Iterable

from beanie import PydanticObjectId
from beanie.operators import Or

from app.core.exceptions import ConflictError, NotFoundError, ValidationFailedError
from app.core.security import hash_password
from app.models._base import ALL_SEGMENTS
from app.models.user import (
    KycInfo,
    User,
    UserPermissions,
    UserRole,
    UserSegment,
    UserStatus,
)
from app.models.wallet import Wallet
from app.utils.validators import is_valid_mobile_in, normalize_mobile_in


def _role_prefix(role: UserRole) -> str:
    return {
        UserRole.SUPER_ADMIN: "SADM",
        UserRole.ADMIN: "ADM",
        UserRole.BROKER: "BRK",
        UserRole.MASTER: "MAS",
        UserRole.DEALER: "DLR",
        UserRole.CLIENT: "CL",
    }.get(role, "USR")


async def generate_user_code(role: UserRole) -> str:
    """Returns a unique user_code like 'CL12345678'. Retries on conflict."""
    prefix = _role_prefix(role)
    for _ in range(10):
        code = f"{prefix}{secrets.randbelow(10**8):08d}"
        existing = await User.find_one(User.user_code == code)
        if existing is None:
            return code
    raise ConflictError("Could not generate a unique user code; please retry")


async def generate_referral_number() -> str:
    """Unique 6-digit referral code (e.g. '048213'). Retries on conflict."""
    for _ in range(20):
        code = f"{secrets.randbelow(10**6):06d}"
        if await User.find_one(User.referral_number == code) is None:
            return code
    raise ConflictError("Could not generate a unique referral code; please retry")


async def find_by_identifier(
    identifier: str, roles: set[UserRole] | None = None
) -> User | None:
    """Lookup by email OR mobile (10-digit Indian), optionally preferring a tier.

    One number or gmail can belong to BOTH a staff account and a client
    account — the same person running a desk and trading their own book. So a
    lookup has to say which door it came in through, or it gets whichever row
    Mongo happened to reach first and the login becomes a coin toss.

    `roles` is a PREFERENCE, not a filter. When nothing matches inside it we
    fall back to the plain lookup, so an identifier that exists exactly once
    behaves precisely as it always did — including the staff member who signs
    into the user app to enrol 2FA.
    """
    ident = identifier.strip().lower()
    if "@" in ident:
        field, value = "email", ident
    else:
        mobile = normalize_mobile_in(ident)
        if is_valid_mobile_in(mobile):
            field, value = "mobile", mobile
        else:
            # last resort: user_code, which is unique platform-wide and so
            # never ambiguous.
            return await User.find_one(User.user_code == ident.upper())

    if roles:
        hit = await User.find_one(
            {field: value, "role": {"$in": [r.value for r in roles]}}
        )
        if hit is not None:
            return hit
    return await User.find_one({field: value})


async def email_or_mobile_taken(
    email: str, mobile: str, role: UserRole | None = None
) -> str | None:
    """Returns the field name that conflicts, or None.

    Scoped to ONE role. A broker who signed up with their own number should
    still be able to open a client account and trade their own book on it, so
    "taken" means taken *at this tier* — one client per number, one broker per
    number, and the same person may be both. Passing no role keeps the old
    platform-wide meaning for any caller that has not been taught the
    difference.

    CLOSED rows (soft-deleted by admin → /admin/users/{id} DELETE) are
    NOT counted as conflicts: re-registering with a previously deleted
    user's email should succeed.  The delete path renames their
    email/mobile to a sentinel so the unique index doesn't fight a new
    insert either — this is defence-in-depth on the API side.
    """
    clauses: list[dict] = [
        {"$or": [{"email": email.lower()}, {"mobile": mobile}]},
        {"status": {"$ne": UserStatus.CLOSED.value}},
    ]
    if role is not None:
        clauses.append({"role": role.value})
    existing = await User.find_one({"$and": clauses})
    if existing is None:
        return None
    if existing.email == email.lower():
        return "email"
    return "mobile"


async def create_user(
    *,
    email: str,
    mobile: str,
    password: str,
    full_name: str,
    role: UserRole = UserRole.CLIENT,
    status: UserStatus = UserStatus.ACTIVE,
    parent_id: PydanticObjectId | None = None,
    kyc: KycInfo | None = None,
    permissions: UserPermissions | None = None,
    is_demo: bool = False,
    created_by: PydanticObjectId | None = None,
    assigned_admin_id: PydanticObjectId | None = None,
    assigned_broker_id: PydanticObjectId | None = None,
    broker_ancestry: list[PydanticObjectId] | None = None,
    signup_origin: str | None = None,
) -> User:
    email_l = email.lower().strip()
    mobile_n = normalize_mobile_in(mobile)
    conflict = await email_or_mobile_taken(email_l, mobile_n, role)
    if conflict:
        raise ConflictError(
            f"A user with this {conflict} already exists",
            details={"field": conflict},
        )

    user = User(
        user_code=await generate_user_code(role),
        referral_number=await generate_referral_number(),
        email=email_l,
        mobile=mobile_n,
        password_hash=hash_password(password),
        full_name=full_name.strip(),
        role=role,
        status=status,
        parent_id=parent_id,
        kyc=kyc or KycInfo(),
        permissions=permissions or UserPermissions(),
        is_demo=is_demo,
        created_by=created_by,
        assigned_admin_id=assigned_admin_id,
        assigned_broker_id=assigned_broker_id,
        broker_ancestry=broker_ancestry or [],
        signup_origin=signup_origin,
    )
    await user.insert()

    # Create wallet (one per user) — sequential. An earlier asyncio.gather
    # version raced on Beanie's shared session on cold Mongo connections
    # and surfaced as a 500 from /auth/register, so the micro-optimisation
    # was reverted in favour of reliability.
    wallet = Wallet(user_id=user.id)  # type: ignore[arg-type]
    await wallet.insert()

    # Default segment access — all enabled (admin can prune later).
    await UserSegment.insert_many(
        [
            UserSegment(user_id=user.id, segment=s.value, enabled=True)  # type: ignore[arg-type]
            for s in ALL_SEGMENTS
        ]
    )

    return user


async def get_user_or_404(user_id: str | PydanticObjectId) -> User:
    try:
        oid = PydanticObjectId(user_id)
    except Exception as e:
        raise ValidationFailedError("Invalid user id") from e
    user = await User.get(oid)
    if user is None:
        raise NotFoundError("User not found")
    return user


async def descendants_of(user_id: PydanticObjectId, *, max_depth: int = 6) -> list[User]:
    """BFS through hierarchy. max_depth caps cost; trees deeper than 6 are
    almost certainly a misconfiguration."""
    out: list[User] = []
    frontier: Iterable[PydanticObjectId] = [user_id]
    for _ in range(max_depth):
        next_frontier: list[PydanticObjectId] = []
        if not frontier:
            break
        children = await User.find(User.parent_id.in_(list(frontier))).to_list()  # type: ignore[attr-defined]
        if not children:
            break
        out.extend(children)
        next_frontier = [c.id for c in children]  # type: ignore[misc]
        frontier = next_frontier
    return out
