"""Super admin caps how many REAL client IDs an admin's pool may hold
(sub-admins 3-dot -> "Set ID count"). Enforced where a real ID is born."""

import asyncio
import inspect
import types

import pytest
from bson import ObjectId
from fastapi import HTTPException

from app.api.v1.admin import users as admin_users
from app.api.v1.user import profile
from app.models.user import UserRole
from app.services import admin_management_service as mgmt

ADMIN = ObjectId()


@pytest.fixture
def pool(monkeypatch):
    def set_up(limit, used, role=UserRole.ADMIN):
        owner = types.SimpleNamespace(id=ADMIN, role=role, real_id_limit=limit)

        async def get(_id):
            return owner if _id == ADMIN else None

        async def count(_id):
            return used

        monkeypatch.setattr(mgmt.User, "get", get)
        monkeypatch.setattr(mgmt, "count_real_users", count)
        return lambda **kw: asyncio.run(mgmt.assert_real_id_room(ADMIN, **kw))

    return set_up


def test_unlimited_never_blocks(pool):
    pool(None, 500)()


def test_under_the_limit_is_fine(pool):
    pool(10, 9)()


def test_at_the_limit_a_new_real_id_is_refused(pool):
    with pytest.raises(HTTPException) as e:
        pool(10, 10)()
    assert e.value.status_code == 403 and "10/10" in e.value.detail
    with pytest.raises(HTTPException) as e:
        pool(10, 10)(for_client=True)
    assert "contact your broker" in e.value.detail


def test_the_platform_pool_and_a_super_admin_owner_are_never_capped(pool):
    asyncio.run(mgmt.assert_real_id_room(None))
    pool(1, 99, role=UserRole.SUPER_ADMIN)()


def test_every_place_a_real_id_is_born_asks():
    create = inspect.getsource(admin_users.create_user)
    assert "await assert_real_id_room(assigned_admin_id)" in create
    assert "if not make_demo and admin.role != UserRole.SUPER_ADMIN:" in create
    update = inspect.getsource(admin_users.update_user)
    assert "await assert_real_id_room(u.assigned_admin_id)" in update
    convert = inspect.getsource(profile.convert_to_real)
    assert "await assert_real_id_room(user.assigned_admin_id, for_client=True)" in convert
    assert convert.index("assert_real_id_room") < convert.index("convert_demo_to_real")
