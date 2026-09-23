"""One number, one account per tier — not one account platform-wide.

Operator: "broker ya admin ban gaya apne number se, to user me bhi wahi number
use kar paye." The person running a desk and trading their own book is one
person. Two CLIENTS still may not share a number; a broker and a client may.

The part that is easy to miss: once a number can appear twice, every lookup
that takes an identifier has to say which door it came through, or it gets
whichever row Mongo reached first and the login becomes a coin toss.
"""

from __future__ import annotations

import inspect

from app.models.user import User, UserRole
from app.services import auth_service, user_service


def _index_keys():
    return [tuple(i.document["key"].items()) for i in User.Settings.indexes
            if hasattr(i, "document")]


def test_uniqueness_is_per_role_not_platform_wide():
    uniq = [i.document for i in User.Settings.indexes
            if getattr(i, "document", {}).get("unique")]
    keysets = [tuple(d["key"].keys()) for d in uniq]
    assert ("email", "role") in keysets
    assert ("mobile", "role") in keysets
    # The old platform-wide uniques must be gone, or nothing changes.
    assert ("email",) not in keysets
    assert ("mobile",) not in keysets


def test_the_field_no_longer_declares_its_own_unique_index():
    """Beanie's `Indexed(str, unique=True)` builds a single-field unique index
    of its own, which would keep enforcing the old rule whatever the index
    block says."""
    s = inspect.getsource(User)
    assert "email: str" in s and "mobile: str" in s
    assert "email: Indexed(" not in s
    assert "mobile: Indexed(" not in s
    # user_code IS still unique platform-wide, and should stay that way.
    assert "user_code: Indexed(str, unique=True)" in s


def test_a_plain_lookup_is_still_available_for_speed():
    keysets = [tuple(d["key"].keys()) for d in
               (i.document for i in User.Settings.indexes if hasattr(i, "document"))]
    assert ("email",) in keysets and ("mobile",) in keysets


def test_the_conflict_check_is_scoped_to_one_tier():
    s = inspect.getsource(user_service.email_or_mobile_taken)
    assert 'clauses.append({"role": role.value})' in s
    assert "if role is not None:" in s
    # A closed account still frees its number, as before.
    assert "UserStatus.CLOSED" in s


def test_creating_a_user_passes_its_own_tier_in():
    s = inspect.getsource(user_service.create_user)
    assert "email_or_mobile_taken(email_l, mobile_n, role)" in s


def test_the_lookup_prefers_a_tier_but_never_hides_a_lone_account():
    """A preference, not a filter — an identifier that exists once must keep
    working exactly as before, including staff signing into the user app."""
    s = inspect.getsource(user_service.find_by_identifier)
    assert "if roles:" in s
    assert "if hit is not None:" in s
    assert s.rstrip().endswith("return await User.find_one({field: value})")


def test_user_code_is_still_unambiguous():
    s = inspect.getsource(user_service.find_by_identifier)
    assert "User.user_code == ident.upper()" in s
    assert "unique platform-wide" in s


def test_login_tells_the_lookup_which_door_it_came_through():
    s = inspect.getsource(auth_service.authenticate)
    assert "lookup_roles = allowed_roles or (" in s
    assert 'ADMIN_ROLES if audience == "admin" else {UserRole.CLIENT}' in s
    assert "find_by_identifier(identifier, roles=lookup_roles)" in s


def test_the_broker_and_admin_portal_lock_still_wins_over_the_audience():
    """`allowed_roles` is the narrower door; it must be preferred."""
    s = inspect.getsource(auth_service.authenticate)
    assert s.index("allowed_roles or (") < s.index('audience == "admin"')


def test_password_reset_uses_the_client_door():
    from app.api.v1.user import auth as user_auth

    s = inspect.getsource(user_auth)
    assert s.count("roles={UserRole.CLIENT}") >= 2, "forgot AND reset"
