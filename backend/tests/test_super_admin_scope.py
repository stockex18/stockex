"""The super-admin's scope is everybody.

It used to mean "clients who sit under no admin", which on a live book is
nobody — all 32 belong to one of the four admins. So the super-admin was 403'd
off a client's ledger, off their detail page, and off Approve on their own
Orders monitor: eight approve calls in one afternoon, every one refused, while
the operator watched a pending order sit there. "Approve karne par turant
execute nahi ho raha hai."

Admins and brokers are still rejected here — they are managed on their own
screens, and that is what keeps this from becoming a way to edit an admin
through a client endpoint.
"""

from __future__ import annotations

import asyncio
import inspect
from types import SimpleNamespace

import pytest

from app.core.dependencies import assert_user_in_scope
from app.core.exceptions import InsufficientPermissionsError
from app.models.user import UserRole


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture
def target(monkeypatch):
    """One client, assigned to an admin — the shape that used to 403."""
    from app.models.user import User

    row = SimpleNamespace(
        id="c1", role=UserRole.CLIENT, assigned_admin_id="a1", broker_ancestry=["b1"]
    )

    async def get(_oid):
        return row

    monkeypatch.setattr(User, "get", staticmethod(get))
    from beanie import PydanticObjectId

    monkeypatch.setattr(
        "app.core.dependencies.PydanticObjectId", lambda v: v
    )
    return row


def test_a_client_under_an_admin_is_in_the_super_admins_scope(target):
    sa = SimpleNamespace(role=UserRole.SUPER_ADMIN, id="sa")
    assert _run(assert_user_in_scope(sa, "c1")) is target


def test_their_own_admin_still_reaches_them(target):
    a = SimpleNamespace(role=UserRole.ADMIN, id="a1")
    assert _run(assert_user_in_scope(a, "c1")) is target


def test_a_different_admin_still_cannot(target):
    other = SimpleNamespace(role=UserRole.ADMIN, id="a2")
    with pytest.raises(InsufficientPermissionsError):
        _run(assert_user_in_scope(other, "c1"))


def test_a_broker_outside_the_ancestry_still_cannot(target):
    b = SimpleNamespace(role=UserRole.BROKER, id="b2")
    with pytest.raises(InsufficientPermissionsError):
        _run(assert_user_in_scope(b, "c1"))


def test_admin_tier_targets_are_still_refused(monkeypatch):
    from app.models.user import User

    admin_row = SimpleNamespace(id="a9", role=UserRole.ADMIN, assigned_admin_id=None)

    async def get(_oid):
        return admin_row

    monkeypatch.setattr(User, "get", staticmethod(get))
    monkeypatch.setattr("app.core.dependencies.PydanticObjectId", lambda v: v)
    sa = SimpleNamespace(role=UserRole.SUPER_ADMIN, id="sa")
    with pytest.raises(InsufficientPermissionsError):
        _run(assert_user_in_scope(sa, "a9"))


def test_the_reason_is_written_down():
    src = inspect.getsource(assert_user_in_scope)
    assert "reassign to your pool first" in src.lower()
    assert "every client-tier user" in src
