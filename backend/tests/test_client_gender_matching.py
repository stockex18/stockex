"""Female clients are matched with female brokers only; male clients may pick
male or female brokers. Signup asks the client's gender (required), the picker
shows a female client the female list only and a male client both lists, and
the server refuses a mismatch on every path that places a client: the picked
broker, a referral, a profile switch.
"""

import asyncio
import pathlib
import types

import pytest
from bson import ObjectId
from fastapi import HTTPException
from pydantic import ValidationError

import app.models.user as user_model
from app.api.v1.user import auth as user_auth
from app.api.v1.user import profile
from app.core.exceptions import ValidationFailedError
from app.schemas.auth import RegisterRequest
from app.services import broker_search_service as bs

from tests.test_female_brokers import directory, codes  # noqa: F401 — fixture

ROOT = pathlib.Path(__file__).resolve().parents[2]


@pytest.mark.parametrize(
    "client, broker, ok",
    [
        ("FEMALE", "FEMALE", True),
        ("FEMALE", "MALE", False),
        ("FEMALE", None, False),  # undeclared is not female
        ("MALE", "FEMALE", True),  # operator: male clients may choose female brokers
        ("MALE", "MALE", True),
        ("MALE", None, True),
        (None, "FEMALE", True),  # clients from before signup asked: as before
        (None, "MALE", True),
    ],
)
def test_the_rule(client, broker, ok):
    assert bs.gender_fits(client, broker) is ok


def test_the_female_list_is_female_brokers_only(directory):  # noqa: F811
    assert codes(asyncio.run(bs.search_brokers("", gender="FEMALE"))) == ["BRKF1", "BRKF2"]


def test_the_male_list_is_everyone_else(directory):  # noqa: F811
    assert codes(asyncio.run(bs.search_brokers("", gender="MALE"))) == ["BRKM1", "BRKN1"]
    # …and its nearby suggestions stay in that list.
    out = asyncio.run(bs.search_brokers("Mumbai", gender="MALE"))
    assert "BRKF2" not in codes(out)


def test_signup_must_say():
    base = dict(email="a@b.co", mobile="9876543210", password="Abcdefg1", full_name="Ab")
    with pytest.raises(ValidationError):
        RegisterRequest(**base)
    with pytest.raises(ValidationError):
        RegisterRequest(**base, gender="OTHER")
    assert RegisterRequest(**base, gender="FEMALE").gender == "FEMALE"


# ── placement ────────────────────────────────────────────────────────────

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

        async def get(oid):
            return BROKERS.get(str(oid))

        monkeypatch.setattr(user_auth.referral_service, "resolve_referrer", resolve_referrer)
        monkeypatch.setattr(bs, "resolve_active_visible_broker", resolve_broker)
        monkeypatch.setattr(user_model, "User", types.SimpleNamespace(get=get))
        payload = types.SimpleNamespace(
            gender=gender,
            referral_code="123456" if referrer else None,
            broker_id=str(broker.id) if broker else "",
        )
        return asyncio.run(user_auth._resolve_signup_placement(payload)), referrer

    return run


def test_a_woman_joins_a_female_broker(place):
    (_, broker_id, _, origin, _), _ = place("FEMALE", FEMALE_BRK)
    assert (broker_id, origin) == (FEMALE_BRK.id, "BROKER_PICK")


def test_a_woman_cannot_join_a_male_broker(place):
    with pytest.raises(ValidationFailedError):
        place("FEMALE", MALE_BRK)


@pytest.mark.parametrize("broker", [MALE_BRK, FEMALE_BRK])
def test_a_man_may_join_either(place, broker):
    (_, broker_id, _, _, _), _ = place("MALE", broker)
    assert broker_id == broker.id


def test_a_referral_to_a_male_broker_still_needs_a_female_pick(place):
    with pytest.raises(ValidationFailedError) as e:
        place("FEMALE", referrer_broker=MALE_BRK)
    assert "broker" in str(e.value).lower()  # the app opens the picker on that word
    (_, broker_id, _, origin, referrer), _ = place("FEMALE", FEMALE_BRK, referrer_broker=MALE_BRK)
    assert (broker_id, origin) == (FEMALE_BRK.id, "BROKER_PICK")
    assert referrer is not None  # the friend is still credited


def test_a_fitting_referral_places_as_before(place):
    (_, broker_id, _, origin, _), _ = place("FEMALE", referrer_broker=FEMALE_BRK)
    assert (broker_id, origin) == (FEMALE_BRK.id, "REFERRAL")


# ── switching broker later ───────────────────────────────────────────────


def test_a_female_client_cannot_switch_to_a_male_broker(monkeypatch):
    async def resolve_broker(bid):
        return MALE_BRK

    monkeypatch.setattr(bs, "resolve_active_visible_broker", resolve_broker)
    me = types.SimpleNamespace(gender="FEMALE", assigned_broker_id=None)
    with pytest.raises(HTTPException) as e:
        asyncio.run(profile.change_my_broker({"broker_id": str(MALE_BRK.id)}, me))
    assert e.value.status_code == 400
    assert me.assigned_broker_id is None


# ── the app ──────────────────────────────────────────────────────────────


def test_register_asks_and_sends_it():
    src = (ROOT / "frontend-user/app/(auth)/register/page.tsx").read_text(encoding="utf-8")
    assert 'gender: z.enum(["MALE", "FEMALE"]' in src
    assert "gender: values.gender," in src
    assert "<BrokerPicker\n              gender={gender}" in src
    assert "Select Male or Female above to see your brokers." in src


def test_a_male_client_gets_both_lists_a_female_client_one():
    src = (ROOT / "frontend-user/components/common/BrokerPicker.tsx").read_text(encoding="utf-8")
    assert 'gender === "FEMALE" ? "FEMALE" : gender === "MALE" ? maleView : null' in src
    assert '{gender === "MALE" && (' in src
    assert "BrokerSearchAPI.search(debounced, 30, mode, list)" in src
