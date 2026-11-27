"""Admin weekly settlements count only real users — never demo accounts.

Demo users trade practice money. Their P&L and brokerage were being added to
the admin's weekly settlement (users, loss, profit, net house P&L and the
admin's share), so a demo account's wins and losses moved real money owed.
"""

from __future__ import annotations

import asyncio

from bson import ObjectId

from app.models.user import User
from app.services import admin_settlement_service as svc


class _Cursor:
    def __init__(self, docs):
        self.docs = docs

    def __aiter__(self):
        async def gen():
            for d in self.docs:
                yield d
        return gen()


class _Coll:
    """A tiny in-memory users collection that honours the two filters used."""

    def __init__(self, users):
        self.users = users
        self.last_filter = None

    def find(self, flt, proj=None):
        self.last_filter = flt
        out = [u for u in self.users if u["assigned_admin_id"] == flt["assigned_admin_id"]]
        demo = flt.get("is_demo")
        if demo == {"$ne": True}:
            out = [u for u in out if u.get("is_demo") is not True]
        return _Cursor([{"_id": u["_id"]} for u in out])


def test_demo_users_are_left_out(monkeypatch):
    admin = ObjectId()
    real1, real2, demo, other = ObjectId(), ObjectId(), ObjectId(), ObjectId()
    coll = _Coll([
        {"_id": real1, "assigned_admin_id": admin},
        {"_id": real2, "assigned_admin_id": admin, "is_demo": False},
        {"_id": demo, "assigned_admin_id": admin, "is_demo": True},
        {"_id": other, "assigned_admin_id": ObjectId()},
    ])
    monkeypatch.setattr(User, "get_motor_collection", lambda: coll)

    ids = asyncio.run(svc._sub_admin_user_ids(admin))

    assert ids == [real1, real2]
    assert coll.last_filter["is_demo"] == {"$ne": True}
