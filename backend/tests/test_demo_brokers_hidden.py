"""A "Try a Broker Demo" account must not be offered to a client signing up.

Reported: the register broker picker listed demo brokers. They are sandboxes —
a real client landing under one would be attached to an account that is wiped
after seven days. The search hides them (list, search and nearby alike), and
the pick is validated with the same rule, so an id posted by hand fails too.
"""

import asyncio
import re
import types

from bson import ObjectId

from app.services import broker_search_service as bs

REAL = ObjectId()
DEMO = ObjectId()
CONVERTED = ObjectId()


def _u(oid, code, city, *, demo):
    return types.SimpleNamespace(
        id=oid, user_code=code, full_name=code, city=city, pincode=None,
        broker_brand_name=None, assigned_admin_id=None, broker_ancestry=[],
        role="BROKER", status="ACTIVE", is_demo=demo,
    )


PEOPLE = {
    REAL: _u(REAL, "BRKREAL", "Pune", demo=False),
    DEMO: _u(DEMO, "BRKDEMO", "Pune", demo=True),
    # A demo that was converted to a real broker is a real broker.
    CONVERTED: _u(CONVERTED, "BRKCONV", "Mumbai", demo=False),
}


def _matches(u, query):
    """Just enough of Mongo for these queries: equality, $ne, $or of regexes."""
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
            continue  # {"_id": {"$in": ...}} for the admin-name lookup
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


def _install(monkeypatch):
    async def get(oid):
        return PEOPLE.get(ObjectId(str(oid)))

    def find(query):
        return _Q([u for u in PEOPLE.values() if _matches(u, query)])

    async def no_hidden():
        return set()

    monkeypatch.setattr(bs, "User", types.SimpleNamespace(find=find, get=get))
    monkeypatch.setattr(bs, "_hidden_set", no_hidden)


def codes(rows):
    return sorted(r["user_code"] for r in rows)


def test_the_full_list_has_no_demo_broker(monkeypatch):
    _install(monkeypatch)
    assert codes(asyncio.run(bs.search_brokers(""))) == ["BRKCONV", "BRKREAL"]


def test_searching_the_demo_brokers_city_does_not_find_it(monkeypatch):
    _install(monkeypatch)
    out = asyncio.run(bs.search_brokers("Pune", by="city"))
    assert codes([r for r in out if not r["nearby"]]) == ["BRKREAL"]
    assert "BRKDEMO" not in codes(out)  # nor among the "also nearby" ones


def test_searching_its_code_does_not_find_it_either(monkeypatch):
    _install(monkeypatch)
    assert asyncio.run(bs.search_brokers("BRKDEMO")) == []


def test_it_is_not_offered_as_a_nearby_broker(monkeypatch):
    """Nashik has nobody, so the nearest are offered — Pune's real broker, and
    Mumbai's, never the demo one in Pune."""
    _install(monkeypatch)
    out = asyncio.run(bs.search_brokers("Nashik", by="city"))
    assert "BRKDEMO" not in codes(out)
    assert "BRKREAL" in codes(out)


def test_a_demo_broker_id_posted_by_hand_is_refused(monkeypatch):
    _install(monkeypatch)
    assert asyncio.run(bs.resolve_active_visible_broker(str(DEMO))) is None
    assert asyncio.run(bs.resolve_active_visible_broker(str(REAL))) is PEOPLE[REAL]
    assert asyncio.run(bs.resolve_active_visible_broker(str(CONVERTED))) is PEOPLE[CONVERTED]


def test_the_matcher_is_not_vacuous():
    """The rule really is in the query the search sends."""
    assert _matches(PEOPLE[DEMO], {"role": "BROKER", "status": "ACTIVE"})
    assert not _matches(PEOPLE[DEMO], {"is_demo": {"$ne": True}})
    assert _matches(PEOPLE[REAL], {"$or": [{"city": re.compile("pun", re.I)}]})
