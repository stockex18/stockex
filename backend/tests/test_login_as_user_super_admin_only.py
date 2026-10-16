"""Signing in AS a client ("Login As User") is super-admin only.

Admins and brokers could sign into any client in their own pool. Operator:
only the super-admin may log into a user's ID. The endpoint now depends on
SuperAdmin, and the menu item is hidden from everyone else.
"""

import pathlib
import types

import pytest
from fastapi.testclient import TestClient

from app.core.dependencies import get_current_admin
from app.main import app
from app.models.user import UserRole

ROOT = pathlib.Path(__file__).resolve().parents[2]
URL = "/api/v1/admin/users/6a48fc5613c116f8b4dda91b/impersonate"


@pytest.fixture
def as_role():
    def set_role(role):
        app.dependency_overrides[get_current_admin] = lambda: types.SimpleNamespace(
            id="a1", role=role
        )
        return TestClient(app)

    yield set_role
    app.dependency_overrides.pop(get_current_admin, None)


@pytest.mark.parametrize("role", [UserRole.ADMIN, UserRole.BROKER])
def test_an_admin_or_a_broker_is_refused(as_role, role):
    r = as_role(role).post(URL)
    assert r.status_code == 403


def test_the_super_admin_gets_past_the_role_check(as_role, monkeypatch):
    import app.api.v1.admin.users as users

    async def stop(admin, user_id):
        raise LookupError("reached the scope check")  # i.e. the role gate passed

    monkeypatch.setattr(users, "assert_user_in_scope", stop)
    with pytest.raises(LookupError):
        as_role(UserRole.SUPER_ADMIN).post(URL)


def test_the_menu_item_is_super_admin_only():
    menu = (ROOT / "frontend-admin/components/admin/UserActionMenu.tsx").read_text(encoding="utf-8")
    block = menu[menu.index('label="Login As User"') - 250 : menu.index('label="Login As User"')]
    assert "{isSuperAdmin && (" in block
