"""A new user starts on their owner's main-wallet auto-settlement.

Operator, 26 Nov: every admin is OFF (a loss shows as a minus balance) and
new ones must stay that way. A new admin already copies the super admin, and
signup copied the owning admin, but a user made from the admin panel started
ON whatever the pool said. user_service.create_user now does it for every
path, and a user with no admin follows the super admin."""

import asyncio
import inspect
import types

from bson import ObjectId

from app.services import user_service

ADMIN = ObjectId()


def _wire(monkeypatch, admin_pool=None, sa_pool=None, boom=False):
    async def get(_id):
        if boom:
            raise RuntimeError("db down")
        return types.SimpleNamespace(pool_auto_settlement=admin_pool) if admin_pool is not None else types.SimpleNamespace()

    async def find_one(*_a):
        return types.SimpleNamespace(pool_auto_settlement=sa_pool) if sa_pool is not None else None

    monkeypatch.setattr(user_service, "User", types.SimpleNamespace(role=None, get=get, find_one=find_one))


def test_a_user_under_an_off_admin_starts_off(monkeypatch):
    _wire(monkeypatch, admin_pool=False)
    assert asyncio.run(user_service._pool_auto_settlement(ADMIN)) is False


def test_a_user_with_no_admin_follows_the_super_admin(monkeypatch):
    _wire(monkeypatch, sa_pool=False)
    assert asyncio.run(user_service._pool_auto_settlement(None)) is False


def test_an_admin_who_never_set_it_keeps_the_default_on(monkeypatch):
    _wire(monkeypatch)
    assert asyncio.run(user_service._pool_auto_settlement(ADMIN)) is True


def test_a_failed_lookup_never_blocks_the_signup(monkeypatch):
    _wire(monkeypatch, boom=True)
    assert asyncio.run(user_service._pool_auto_settlement(ADMIN)) is True


def test_create_user_sets_it_for_every_path():
    assert "auto_settlement=await _pool_auto_settlement(assigned_admin_id)" in inspect.getsource(
        user_service.create_user
    )
