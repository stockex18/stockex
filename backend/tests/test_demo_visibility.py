"""Who may see the Demo section.

Authorization boundary, so it gets a test: the ADMIN tier that owns a broker
must NOT see that broker's demo signups, and one broker must never see
another's. Hiding the nav item is not enough — the endpoint takes any
admin-tier token.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from beanie import PydanticObjectId

from app.api.v1.admin.management import demo_visibility_scope
from app.core.exceptions import InsufficientPermissionsError
from app.models.user import UserRole

BROKER_ID = PydanticObjectId()


def _actor(role: UserRole, _id=None):
    return SimpleNamespace(role=role, id=_id or PydanticObjectId())


def test_super_admin_sees_everything():
    assert demo_visibility_scope(_actor(UserRole.SUPER_ADMIN)) == {}


def test_broker_is_scoped_to_its_own_signups():
    scope = demo_visibility_scope(_actor(UserRole.BROKER, BROKER_ID))
    assert scope == {"assigned_broker_id": BROKER_ID}


def test_broker_scope_is_exact_not_ancestry():
    """`broker_ancestry` would let a PARENT broker see a sub-broker's signups."""
    scope = demo_visibility_scope(_actor(UserRole.BROKER, BROKER_ID))
    assert "broker_ancestry" not in scope


@pytest.mark.parametrize(
    "role", [UserRole.ADMIN, UserRole.MASTER, UserRole.DEALER, UserRole.CLIENT]
)
def test_everyone_else_is_refused(role):
    """ADMIN included — the broker's owning admin is deliberately excluded."""
    with pytest.raises(InsufficientPermissionsError):
        demo_visibility_scope(_actor(role))
