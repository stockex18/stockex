"""The signup picker's pink "Female" tab.

Only brokers who DECLARED themselves female (Settings → Platform, next to their
city and PIN) are listed there — gender is never guessed from a name. Search
inside the tab works like "All", and its nearby suggestions are female-only.
"""

import asyncio
import pathlib
import re
import types

import pytest
from bson import ObjectId
from fastapi import HTTPException

from app.api.v1.admin import me as admin_me
from app.services import broker_search_service as bs

ROOT = pathlib.Path(__file__).resolve().parents[2]


def _u(code, city, gender):
    return types.SimpleNamespace(
        id=ObjectId(), user_code=code, full_name=code, city=city, pincode=None,
        broker_brand_name=None, assigned_admin_id=None, broker_ancestry=[],
        role="BROKER", status="ACTIVE", is_demo=False, gender=gender,
    )


PEOPLE = [
    _u("BRKF1", "Pune", "FEMALE"),
    _u("BRKF2", "Mumbai", "FEMALE"),
    _u("BRKM1", "Pune", "MALE"),
    _u("BRKN1", "Nashik", None),  # never said — not guessed
]


def _matches(u, query):
    for key, want in query.items():
        if key == "$or":
            if not any(
                (v := getattr(u, f, None)) and pat.search(str(v))
                for clause in want
                for f, pat in clause.items()
            ):
                return False
        elif isinstance(want, dict) and "$ne" in want:
            if getattr(u, key, None) == want["$ne"]:
                return False
        elif isinstance(want, dict):
            continue
        elif getattr(u, key, None) != want:
            return False
    return True


class _Q:
    def __init__(self, rows):
        self.rows = rows

    def limit(self, n):
        return self

    async def to_list(self):
        return list(self.rows)


@pytest.fixture
def directory(monkeypatch):
    def find(query):
        return _Q([u for u in PEOPLE if _matches(u, query)])

    async def no_hidden():
        return set()

    monkeypatch.setattr(bs, "User", types.SimpleNamespace(find=find))
    monkeypatch.setattr(bs, "_hidden_set", no_hidden)

    def search(q, by):
        return asyncio.run(bs.search_brokers(q, by=by))

    return search


def codes(rows):
    return sorted(r["user_code"] for r in rows)


def test_the_female_tab_lists_only_brokers_who_said_so(directory):
    assert codes(directory("", "female")) == ["BRKF1", "BRKF2"]


def test_search_inside_the_tab_matches_like_all(directory):
    assert codes(directory("BRKF2", "female")) == ["BRKF2"]
    assert codes([r for r in directory("Pune", "female") if not r["nearby"]]) == ["BRKF1"]


def test_its_nearby_suggestions_are_female_only_too(directory):
    """Nobody female in Nashik: the rescue may suggest the nearest female
    brokers, never the male one in Pune or the undeclared one in Nashik."""
    out = directory("Nashik", "female")
    assert not ({"BRKM1", "BRKN1"} & set(codes(out)))


def test_all_still_lists_everyone_and_carries_gender_for_the_pink_chip(directory):
    out = directory("", "all")
    assert codes(out) == ["BRKF1", "BRKF2", "BRKM1", "BRKN1"]
    assert {r["user_code"]: r["gender"] for r in out}["BRKF1"] == "FEMALE"
    assert {r["user_code"]: r["gender"] for r in out}["BRKN1"] is None


# ── the broker declares it ───────────────────────────────────────────────


@pytest.fixture
def me(monkeypatch):
    user = types.SimpleNamespace(
        id=ObjectId(), full_name="B", city=None, pincode=None,
        broker_brand_name=None, gender=None,
    )

    async def save():
        return None

    user.save = save

    async def get(_id):
        return user

    monkeypatch.setattr(admin_me, "User", types.SimpleNamespace(get=get))
    return user


@pytest.mark.parametrize("raw", ["female", "FEMALE", " Female "])
def test_a_broker_can_say_female(me, raw):
    out = asyncio.run(admin_me.update_my_profile({"gender": raw}, types.SimpleNamespace(id=me.id)))
    assert me.gender == "FEMALE"
    assert out.data["gender"] == "FEMALE"


def test_empty_clears_it(me):
    me.gender = "FEMALE"
    asyncio.run(admin_me.update_my_profile({"gender": ""}, types.SimpleNamespace(id=me.id)))
    assert me.gender is None


@pytest.mark.parametrize("raw", ["F", "woman", "1"])
def test_anything_else_is_refused_and_nothing_changes(me, raw):
    with pytest.raises(HTTPException) as e:
        asyncio.run(admin_me.update_my_profile({"gender": raw}, types.SimpleNamespace(id=me.id)))
    assert e.value.status_code == 400
    assert me.gender is None


def test_the_matcher_is_not_vacuous():
    assert not _matches(PEOPLE[2], {"gender": "FEMALE"})
    assert _matches(PEOPLE[0], {"$or": [{"city": re.compile("pun", re.I)}]})


# ── the apps ─────────────────────────────────────────────────────────────


def test_the_picker_has_a_pink_female_tab():
    src = (ROOT / "frontend-user/components/common/BrokerPicker.tsx").read_text(encoding="utf-8")
    assert '{ key: "female", label: "Female"' in src
    assert "bg-pink-500 text-white" in src
    assert 'b.gender === "FEMALE"' in src


def test_the_broker_can_choose_it_in_settings():
    src = (ROOT / "frontend-admin/app/(admin)/settings/platform/page.tsx").read_text(encoding="utf-8")
    assert '<option value="FEMALE">Female</option>' in src
    assert "setProfile({ brand_name: brand, city, pincode, gender })" in src
