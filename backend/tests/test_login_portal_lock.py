"""Broker and admin sign in at separate doors onto the same panel.

Asked for: a broker login of its own — not the admin login link — installable
as its own app next to the admin app on one phone, with the login "locked" to
its role.

The lock is server-side. A client-side role check would be decorative: by the
time the page could read the role, the tokens are already issued. It sits in
`authenticate` at one exact spot:

    after the password and 2FA  — before them it would tell anyone typing an
                                  ID which role that account holds
    before any token is minted  — after minting, a refused login would
                                  already have written a live refresh session

`portal` omitted keeps the old any-admin-role behaviour, so every client that
predates the split — scripts, older app installs — keeps working.
"""

from __future__ import annotations

import asyncio
import inspect
from types import SimpleNamespace

import pytest

from app.api.v1.admin import auth as auth_api
from app.core.exceptions import InvalidCredentialsError, WrongPortalError
from app.models.user import UserRole, UserStatus
from app.services import auth_service


def _user(role):
    return SimpleNamespace(
        id="u1",
        role=role,
        status=UserStatus.ACTIVE,
        password_hash="h",
        two_fa_enabled=False,
        two_fa_secret=None,
        token_version=0,
    )


@pytest.fixture
def wire(monkeypatch):
    """Fake the user lookup and password check; record whether a token was
    minted, which is the thing the lock must prevent."""
    state = {"user": None, "password_ok": True, "minted": False}

    async def find(_identifier):
        return state["user"]

    def mint(*_a, **_kw):
        state["minted"] = True
        raise RuntimeError("stop after mint — the test only cares that it got here")

    monkeypatch.setattr(auth_service.user_service, "find_by_identifier", find)
    monkeypatch.setattr(auth_service, "verify_password", lambda *_a: state["password_ok"])
    monkeypatch.setattr(auth_service, "needs_rehash", lambda *_a: False)
    monkeypatch.setattr(auth_service, "_is_locked", lambda *_a: False)
    monkeypatch.setattr(auth_service, "create_access_token", mint)

    async def failed(*_a, **_kw):
        return None

    monkeypatch.setattr(auth_service, "_register_failed_attempt", failed)
    return state


def _login(roles):
    return asyncio.run(
        auth_service.authenticate(
            identifier="x",
            password="p" * 8,
            two_fa_code=None,
            audience="admin",
            ip="1.1.1.1",
            user_agent=None,
            allowed_roles=roles,
        )
    )


BROKER_DOOR = auth_api._PORTAL_ROLES["broker"]
ADMIN_DOOR = auth_api._PORTAL_ROLES["admin"]


def test_an_admin_cannot_use_the_broker_login(wire):
    wire["user"] = _user(UserRole.ADMIN)
    with pytest.raises(WrongPortalError) as e:
        _login(BROKER_DOOR)
    assert "broker login" in str(e.value)
    assert wire["minted"] is False


def test_a_broker_cannot_use_the_admin_login(wire):
    wire["user"] = _user(UserRole.BROKER)
    with pytest.raises(WrongPortalError) as e:
        _login(ADMIN_DOOR)
    assert "Brokers sign in at the broker login" in str(e.value)
    assert wire["minted"] is False


def test_the_right_door_goes_through_to_minting(wire):
    wire["user"] = _user(UserRole.BROKER)
    with pytest.raises(RuntimeError, match="stop after mint"):
        _login(BROKER_DOOR)
    assert wire["minted"] is True


def test_the_super_admin_uses_the_admin_door(wire):
    wire["user"] = _user(UserRole.SUPER_ADMIN)
    with pytest.raises(RuntimeError, match="stop after mint"):
        _login(ADMIN_DOOR)


def test_a_wrong_password_never_reveals_the_role(wire):
    # An admin ID typed on the broker page with a WRONG password must get the
    # generic error, not "this is the broker login" — that would confirm the
    # account exists and what it is.
    wire["user"] = _user(UserRole.ADMIN)
    wire["password_ok"] = False
    with pytest.raises(InvalidCredentialsError):
        _login(BROKER_DOOR)


def test_no_portal_keeps_the_old_behaviour(wire):
    # Clients that predate the split send no portal and must keep working.
    wire["user"] = _user(UserRole.BROKER)
    with pytest.raises(RuntimeError, match="stop after mint"):
        _login(None)


def test_the_lock_sits_between_2fa_and_minting():
    src = inspect.getsource(auth_service.authenticate)
    assert src.index("verify_password(") < src.index("allowed_roles is not None")
    assert src.index("TwoFARequiredError") < src.index("allowed_roles is not None")
    assert src.index("allowed_roles is not None") < src.index("create_access_token(")


def test_the_endpoint_passes_the_portal_through():
    src = inspect.getsource(auth_api.admin_login)
    assert "allowed_roles=_PORTAL_ROLES.get(payload.portal)" in src
