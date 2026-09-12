"""A broker can sign up the way a user does — pick an admin, then wait.

Operator: "jaise user register hai waise broker register bana de, usme select
your admin show ho". Two rules make it safe on a public endpoint:

  * the admin pick is REQUIRED and must be one the picker actually offers
    (active, and not hidden by the super admin);
  * the account is created PENDING, so it cannot sign in until the admin
    approves it — the existing Brokers → unblock path.
"""

from __future__ import annotations

import asyncio
import inspect
from types import SimpleNamespace

import pytest

from app.api.v1.admin import auth as admin_auth
from app.models.user import UserRole, UserStatus
from app.services import broker_search_service as bss

ADMIN_A = SimpleNamespace(id="a1", full_name="Ankit", user_code="ADM1", city="Indore",
                          role=UserRole.ADMIN, status=UserStatus.ACTIVE)
ADMIN_HIDDEN = SimpleNamespace(id="a2", full_name="Hidden Co", user_code="ADM2", city="Surat",
                               role=UserRole.ADMIN, status=UserStatus.ACTIVE)
ADMIN_BLOCKED = SimpleNamespace(id="a3", full_name="Blocked Co", user_code="ADM3", city="Pune",
                                role=UserRole.ADMIN, status=UserStatus.BLOCKED)


@pytest.fixture
def directory(monkeypatch):
    rows = [ADMIN_A, ADMIN_HIDDEN, ADMIN_BLOCKED]

    class _Find:
        def __init__(self, q):
            self.q = q

        async def to_list(self):
            return [
                r for r in rows
                if r.role.value == self.q["role"] and r.status.value == self.q["status"]
            ]

    async def hidden():
        return {"a2"}

    monkeypatch.setattr(bss.User, "find", staticmethod(lambda q: _Find(q)))
    monkeypatch.setattr(bss, "_hidden_set", hidden)
    return rows


def test_the_picker_lists_active_admins_only(directory):
    out = asyncio.run(bss.search_admins())
    assert [r["user_code"] for r in out] == ["ADM1"]  # hidden and blocked are out
    assert out[0]["city"] == "Indore"


def test_the_picker_searches_by_name_code_or_city(directory):
    for term in ("ank", "ADM1", "indo"):
        assert len(asyncio.run(bss.search_admins(q=term))) == 1, term
    assert asyncio.run(bss.search_admins(q="nobody")) == []


def test_only_an_admin_the_picker_offers_can_be_signed_up_under(monkeypatch, directory):
    async def get(oid):
        return {"a1": ADMIN_A, "a2": ADMIN_HIDDEN, "a3": ADMIN_BLOCKED}.get(str(oid))

    monkeypatch.setattr(bss.User, "get", staticmethod(get))
    monkeypatch.setattr(bss, "PydanticObjectId", lambda v: str(v))
    assert asyncio.run(bss.resolve_signup_admin("a1")) is ADMIN_A
    assert asyncio.run(bss.resolve_signup_admin("a2")) is None  # hidden
    assert asyncio.run(bss.resolve_signup_admin("a3")) is None  # blocked
    assert asyncio.run(bss.resolve_signup_admin("nope")) is None


def test_the_admin_pick_is_required():
    assert admin_auth.BrokerRegisterRequest.model_fields["admin_id"].is_required()


def test_signup_refuses_an_admin_that_is_not_on_the_list():
    src = inspect.getsource(admin_auth.broker_register)
    assert "resolve_signup_admin(payload.admin_id)" in src
    assert "Please choose a valid admin" in src


def test_the_new_broker_is_pending_and_holds_no_permissions():
    src = inspect.getsource(admin_auth.broker_register)
    assert "broker.status = UserStatus.PENDING" in src
    assert "permissions=BrokerPermissions()" in src
    # It must not hand back tokens — a pending account cannot sign in.
    assert "mint_login_pair" not in src
