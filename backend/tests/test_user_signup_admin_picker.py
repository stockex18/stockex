"""User signup: "Choose your admin" field, switched on/off by the super admin.

Client request 25 Nov 2026: a user registering should be able to pick an
ADMIN, the way a new broker does, with the field controlled from Platform
settings — when the super admin turns it OFF the field is not shown at all.

The rules pinned here:
  * OFF (the default): signup is exactly what it was — `admin_id` is ignored;
  * ON: the admin is required, must be active and not hidden, and the broker
    must be one of THAT admin's brokers;
  * a referral still wins over any pick;
  * the broker list can be narrowed to one admin.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from app.api.v1.admin import settings as admin_settings
from app.api.v1.user import auth as user_auth
from app.core.exceptions import ValidationFailedError
from app.models.user import UserRole, UserStatus
from app.services import broker_search_service as bss

ADMIN_A = SimpleNamespace(id="a1", full_name="Ankit", user_code="ADM1", city="Indore",
                          role=UserRole.ADMIN, status=UserStatus.ACTIVE)
ADMIN_B = SimpleNamespace(id="b1", full_name="Bharat", user_code="ADM2", city="Surat",
                          role=UserRole.ADMIN, status=UserStatus.ACTIVE)
ADMIN_BLOCKED = SimpleNamespace(id="c1", full_name="Blocked Co", user_code="ADM3", city="Pune",
                                role=UserRole.ADMIN, status=UserStatus.BLOCKED)
BROKER_OF_A = SimpleNamespace(id="br1", assigned_admin_id="a1", broker_ancestry=[])
BROKER_OF_B = SimpleNamespace(id="br2", assigned_admin_id="b1", broker_ancestry=[])


def _payload(**kw):
    base = {"referral_code": None, "broker_id": "br1", "admin_id": None}
    base.update(kw)
    return SimpleNamespace(**base)


@pytest.fixture
def signup(monkeypatch):
    """Placement with no referrer, two admins, one broker each."""
    state = {"on": False, "referrer": None}

    async def enabled():
        return state["on"]

    async def resolve_admin(admin_id):
        return {"a1": ADMIN_A, "b1": ADMIN_B}.get(admin_id)

    async def resolve_broker(broker_id):
        return {"br1": BROKER_OF_A, "br2": BROKER_OF_B}.get(broker_id)

    async def referrer(code):
        return state["referrer"]

    monkeypatch.setattr(bss, "user_signup_admin_picker_enabled", enabled)
    monkeypatch.setattr(bss, "resolve_user_signup_admin", resolve_admin)
    monkeypatch.setattr(bss, "resolve_active_visible_broker", resolve_broker)
    monkeypatch.setattr(user_auth.referral_service, "resolve_referrer", referrer)
    return state


def _place(payload):
    return asyncio.run(user_auth._resolve_signup_placement(payload))


# ── Placement ────────────────────────────────────────────────────────
def test_off_signup_is_unchanged_and_admin_id_is_ignored(signup):
    # Even a wrong admin is ignored while the field is off.
    admin_id, broker_id, ancestry, origin, _ = _place(_payload(admin_id="b1"))
    assert (admin_id, broker_id, ancestry, origin) == ("a1", "br1", ["br1"], "BROKER_PICK")


def test_on_admin_is_required(signup):
    signup["on"] = True
    with pytest.raises(ValidationFailedError, match="valid admin"):
        _place(_payload(admin_id=None))
    with pytest.raises(ValidationFailedError, match="valid admin"):
        _place(_payload(admin_id="hidden-or-blocked"))


def test_on_broker_must_belong_to_the_chosen_admin(signup):
    signup["on"] = True
    with pytest.raises(ValidationFailedError, match="not under the admin"):
        _place(_payload(admin_id="b1", broker_id="br1"))
    admin_id, broker_id, *_ = _place(_payload(admin_id="b1", broker_id="br2"))
    assert (admin_id, broker_id) == ("b1", "br2")


def test_on_broker_is_still_required(signup):
    signup["on"] = True
    with pytest.raises(ValidationFailedError, match="valid broker"):
        _place(_payload(admin_id="a1", broker_id=""))


def test_referral_still_wins_over_the_pick(signup):
    signup["on"] = True
    signup["referrer"] = SimpleNamespace(
        assigned_admin_id="z9", assigned_broker_id="zb", broker_ancestry=["zb"]
    )
    admin_id, broker_id, _, origin, _ = _place(_payload(admin_id=None, broker_id=None))
    assert (admin_id, broker_id, origin) == ("z9", "zb", "REFERRAL")


# ── The switch ───────────────────────────────────────────────────────
@pytest.mark.parametrize(
    ("stored", "expected"),
    [(None, False), (True, True), (False, False), ("false", False), ("true", True), ("0", False)],
)
def test_switch_reads_off_by_default_and_never_reads_false_text_as_on(monkeypatch, stored, expected):
    async def find_one(*_a, **_k):
        return None if stored is None else SimpleNamespace(setting_value=stored)

    monkeypatch.setattr(bss, "PlatformSetting", SimpleNamespace(setting_key="k", find_one=find_one))
    assert asyncio.run(bss.user_signup_admin_picker_enabled()) is expected


def test_switch_reads_off_when_the_row_cannot_be_read(monkeypatch):
    async def boom(*_a, **_k):
        raise RuntimeError("db down")

    monkeypatch.setattr(bss, "PlatformSetting", SimpleNamespace(setting_key="k", find_one=boom))
    assert asyncio.run(bss.user_signup_admin_picker_enabled()) is False


# ── The admin list the form shows ────────────────────────────────────
@pytest.fixture
def directory(monkeypatch):
    rows = [ADMIN_A, ADMIN_B, ADMIN_BLOCKED]
    asked: dict = {}

    class _Find:
        def __init__(self, q):
            self.q = q

        async def to_list(self):
            return [
                r for r in rows
                if r.role.value == self.q["role"] and r.status.value == self.q["status"]
            ]

    async def hidden(key=bss.HIDDEN_ADMINS_KEY):
        asked["key"] = key
        return {"b1"} if key == bss.USER_SIGNUP_HIDDEN_ADMINS_KEY else set()

    monkeypatch.setattr(bss.User, "find", staticmethod(lambda q: _Find(q)))
    monkeypatch.setattr(bss, "_hidden_set", hidden)
    return asked


def test_admin_list_is_empty_while_the_field_is_off(monkeypatch, directory):
    async def off():
        return False

    monkeypatch.setattr(bss, "user_signup_admin_picker_enabled", off)
    assert asyncio.run(bss.search_user_signup_admins()) == []


def test_admin_list_uses_its_own_hidden_list(monkeypatch, directory):
    async def on():
        return True

    monkeypatch.setattr(bss, "user_signup_admin_picker_enabled", on)
    out = asyncio.run(bss.search_user_signup_admins())
    assert [r["user_code"] for r in out] == ["ADM1"]  # b1 hidden here, c1 blocked
    assert directory["key"] == bss.USER_SIGNUP_HIDDEN_ADMINS_KEY


def test_broker_signup_picker_is_not_affected_by_the_user_list(directory):
    # The broker signup's list hides nobody in this fixture, so b1 is there.
    out = asyncio.run(bss.search_admins())
    assert [r["user_code"] for r in out] == ["ADM1", "ADM2"]
    assert directory["key"] == bss.HIDDEN_SIGNUP_ADMINS_KEY


def test_resolver_refuses_hidden_and_blocked_admins(monkeypatch):
    async def get(oid):
        return {"a1": ADMIN_A, "b1": ADMIN_B, "c1": ADMIN_BLOCKED}.get(str(oid))

    async def hidden(key=None):
        return {"b1"} if key == bss.USER_SIGNUP_HIDDEN_ADMINS_KEY else set()

    monkeypatch.setattr(bss.User, "get", staticmethod(get))
    monkeypatch.setattr(bss, "PydanticObjectId", lambda v: str(v))
    monkeypatch.setattr(bss, "_hidden_set", hidden)
    assert asyncio.run(bss.resolve_user_signup_admin("a1")) is ADMIN_A
    assert asyncio.run(bss.resolve_user_signup_admin("b1")) is None  # hidden
    assert asyncio.run(bss.resolve_user_signup_admin("c1")) is None  # blocked
    assert asyncio.run(bss.resolve_user_signup_admin("nope")) is None


# ── Broker list narrowed to one admin ────────────────────────────────
def test_broker_search_narrows_to_the_chosen_admin(monkeypatch):
    seen: list[dict] = []

    class _Find:
        def __init__(self, q):
            seen.append(q)

        def limit(self, _n):
            return self

        async def to_list(self):
            return []

    async def hidden(key=None):
        return set()

    monkeypatch.setattr(bss.User, "find", staticmethod(lambda q: _Find(q)))
    monkeypatch.setattr(bss, "_hidden_set", hidden)
    oid = "6650f0f0f0f0f0f0f0f0f0f0"
    asyncio.run(bss.search_brokers(admin_id=oid))
    assert str(seen[-1]["assigned_admin_id"]) == oid
    # A junk id lists nobody, not everyone.
    before = len(seen)
    assert asyncio.run(bss.search_brokers(admin_id="junk")) == []
    assert len(seen) == before
    # No admin → the old, unfiltered list.
    asyncio.run(bss.search_brokers())
    assert "assigned_admin_id" not in seen[-1]


# ── Super-admin settings endpoint ────────────────────────────────────
@pytest.fixture
def settings_store(monkeypatch):
    store = {"on": False, "lists": {}}

    async def get_list(key=bss.HIDDEN_ADMINS_KEY):
        return store["lists"].get(key, [])

    def setter(key):
        async def _set(ids):
            store["lists"][key] = ids
            return ids
        return _set

    async def enabled():
        return store["on"]

    async def set_enabled(on):
        store["on"] = on
        return on

    async def no_log(**_k):
        return None

    monkeypatch.setattr(bss, "get_hidden_admin_ids", get_list)
    monkeypatch.setattr(bss, "set_hidden_admin_ids", setter(bss.HIDDEN_ADMINS_KEY))
    monkeypatch.setattr(bss, "set_hidden_signup_admin_ids", setter(bss.HIDDEN_SIGNUP_ADMINS_KEY))
    monkeypatch.setattr(
        bss, "set_hidden_user_signup_admin_ids", setter(bss.USER_SIGNUP_HIDDEN_ADMINS_KEY)
    )
    monkeypatch.setattr(bss, "user_signup_admin_picker_enabled", enabled)
    monkeypatch.setattr(bss, "set_user_signup_admin_picker_enabled", set_enabled)
    monkeypatch.setattr(admin_settings, "log_event", no_log)
    return store


SA = SimpleNamespace(id="sa", role=UserRole.SUPER_ADMIN)


def test_switch_alone_does_not_blank_the_lists(settings_store):
    settings_store["lists"][bss.HIDDEN_ADMINS_KEY] = ["x"]
    res = asyncio.run(
        admin_settings.set_broker_search_hidden({"user_signup_admin_picker": True}, SA)
    )
    assert res.data["user_signup_admin_picker"] is True
    assert res.data["hidden_admin_ids"] == ["x"]
    assert settings_store["on"] is True


def test_user_signup_list_is_saved_on_its_own(settings_store):
    res = asyncio.run(
        admin_settings.set_broker_search_hidden({"hidden_user_signup_admin_ids": ["a1"]}, SA)
    )
    assert res.data["hidden_user_signup_admin_ids"] == ["a1"]
    assert settings_store["lists"] == {bss.USER_SIGNUP_HIDDEN_ADMINS_KEY: ["a1"]}
    assert res.data["user_signup_admin_picker"] is False


def test_switch_must_be_a_real_boolean(settings_store):
    from fastapi import HTTPException

    with pytest.raises(HTTPException):
        asyncio.run(
            admin_settings.set_broker_search_hidden({"user_signup_admin_picker": "false"}, SA)
        )
    assert settings_store["on"] is False


def test_only_the_super_admin_can_change_it(settings_store):
    from fastapi import HTTPException

    with pytest.raises(HTTPException):
        asyncio.run(
            admin_settings.set_broker_search_hidden(
                {"user_signup_admin_picker": True}, SimpleNamespace(id="a", role=UserRole.ADMIN)
            )
        )
    assert settings_store["on"] is False
