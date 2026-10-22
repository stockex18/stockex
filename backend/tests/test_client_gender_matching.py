"""Signup asks the client's gender (required). It picks the app colour and
which broker list opens first; it does NOT limit who joins whom. Operator
(22 Oct): female clients may choose male brokers too — with no female broker
live yet, the old "female → female only" rule left them unable to sign up.
"""

import asyncio
import pathlib
import types

import pytest
from bson import ObjectId
from pydantic import ValidationError

from app.api.v1.user import auth as user_auth
from app.api.v1.user import profile
from app.schemas.auth import RegisterRequest
from app.services import broker_search_service as bs

from tests.test_female_brokers import directory, codes  # noqa: F401 — fixture

ROOT = pathlib.Path(__file__).resolve().parents[2]


def test_the_female_list_is_female_brokers_only(directory):  # noqa: F811
    assert codes(asyncio.run(bs.search_brokers("", gender="FEMALE"))) == ["BRKF1", "BRKF2"]


def test_the_male_list_is_everyone_else(directory):  # noqa: F811
    assert codes(asyncio.run(bs.search_brokers("", gender="MALE"))) == ["BRKM1", "BRKN1"]
    out = asyncio.run(bs.search_brokers("Mumbai", gender="MALE"))
    assert "BRKF2" not in codes(out)


def test_signup_must_say():
    base = dict(email="a@b.co", mobile="9876543210", password="Abcdefg1", full_name="Ab")
    with pytest.raises(ValidationError):
        RegisterRequest(**base)
    with pytest.raises(ValidationError):
        RegisterRequest(**base, gender="OTHER")
    assert RegisterRequest(**base, gender="FEMALE").gender == "FEMALE"


def test_the_old_rule_is_gone():
    assert not hasattr(bs, "gender_fits")


# ── placement: anyone joins any broker ──────────────────────────────────

FEMALE_BRK = types.SimpleNamespace(id=ObjectId(), gender="FEMALE", assigned_admin_id=None, broker_ancestry=[])
MALE_BRK = types.SimpleNamespace(id=ObjectId(), gender="MALE", assigned_admin_id=None, broker_ancestry=[])
BROKERS = {str(FEMALE_BRK.id): FEMALE_BRK, str(MALE_BRK.id): MALE_BRK}


@pytest.fixture
def place(monkeypatch):
    def run(gender, broker=None, referrer_broker=None):
        referrer = (
            types.SimpleNamespace(
                assigned_admin_id=None, assigned_broker_id=referrer_broker.id, broker_ancestry=[referrer_broker.id]
            )
            if referrer_broker
            else None
        )

        async def resolve_referrer(code):
            return referrer

        async def resolve_broker(bid):
            return BROKERS.get(bid)

        monkeypatch.setattr(user_auth.referral_service, "resolve_referrer", resolve_referrer)
        monkeypatch.setattr(bs, "resolve_active_visible_broker", resolve_broker)
        payload = types.SimpleNamespace(
            gender=gender,
            referral_code="123456" if referrer else None,
            broker_id=str(broker.id) if broker else "",
        )
        return asyncio.run(user_auth._resolve_signup_placement(payload))

    return run


@pytest.mark.parametrize("gender", ["FEMALE", "MALE"])
@pytest.mark.parametrize("broker", [MALE_BRK, FEMALE_BRK])
def test_any_client_may_join_any_broker(place, gender, broker):
    _, broker_id, _, origin, _ = place(gender, broker)
    assert (broker_id, origin) == (broker.id, "BROKER_PICK")


def test_a_referral_places_under_the_friends_broker_whatever_the_gender(place):
    _, broker_id, _, origin, _ = place("FEMALE", referrer_broker=MALE_BRK)
    assert (broker_id, origin) == (MALE_BRK.id, "REFERRAL")


def test_a_female_client_may_switch_to_a_male_broker(monkeypatch):
    async def resolve_broker(bid):
        return MALE_BRK

    async def save():
        return None

    async def me_out(user):
        return user

    monkeypatch.setattr(bs, "resolve_active_visible_broker", resolve_broker)
    monkeypatch.setattr(profile, "_me_out", me_out)
    monkeypatch.setattr(profile, "log_event", lambda **kw: asyncio.sleep(0))
    me = types.SimpleNamespace(id=ObjectId(), gender="FEMALE", assigned_broker_id=None, save=save)
    asyncio.run(profile.change_my_broker({"broker_id": str(MALE_BRK.id)}, me))
    assert me.assigned_broker_id == MALE_BRK.id


# ── the app ──────────────────────────────────────────────────────────────


def test_register_asks_and_sends_it():
    src = (ROOT / "frontend-user/app/(auth)/register/page.tsx").read_text(encoding="utf-8")
    assert 'gender: z.enum(["MALE", "FEMALE"]' in src
    assert "gender: values.gender," in src
    assert "Select Male or Female above to see your brokers." in src


def test_every_client_gets_both_lists_their_own_first():
    src = (ROOT / "frontend-user/components/common/BrokerPicker.tsx").read_text(encoding="utf-8")
    assert 'useState<ClientGender>(gender === "FEMALE" ? "FEMALE" : "MALE")' in src
    assert "{gender && (" in src
    assert "BrokerSearchAPI.search(debounced, 30, mode, list)" in src
