"""Search a broker by AREA — "Andheri", "Koramangala", "Shivaji Nagar, Pune".

Brokers record only a city and a PIN, and a client knows their area far more
often than their PIN. So the area is turned into its post office's PIN
(GeoNames, built by scripts/build_in_localities.py) and the brokers are ranked
by distance from there, the same way a PIN search is.

What the tests protect:

  * a real city is never read as an area, and an area never as a city that
    merely looks like it;
  * a broker AT the area's PIN is a real match, not a "nearby" one;
  * a name the data does not know still ranks nothing.
"""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest

from app.services import broker_search_service as bs
from app.services import geo_service as geo


# ── reading an area name ─────────────────────────────────────────────
@pytest.mark.parametrize(
    "typed,pin,city",
    [
        ("Andheri", "400053", "Mumbai"),
        ("andheri east", "400069", "Mumbai"),
        ("Koramangala", "560034", "Bengaluru"),
        ("Connaught Place", "110001", "Delhi"),
    ],
)
def test_an_area_becomes_its_post_offices_pin(typed, pin, city):
    loc = geo.resolve_place(typed)
    assert isinstance(loc, geo.Locality)
    assert loc.pin == pin and city in loc.name


def test_an_area_with_several_pins_owns_them_all():
    """Andheri is 400053 and 400069: a broker at either is IN Andheri."""
    assert {"400053", "400069"} <= geo.resolve_locality("Andheri").pins


def test_a_shared_name_goes_to_the_biggest_place():
    """There are Andheris in Gujarat and Himachal too."""
    assert geo.resolve_locality("Andheri").pin.startswith("400")


@pytest.mark.parametrize(
    "typed,pin",
    [
        ("Shivajinagar Pune", "411005"),
        ("Shivaji Nagar, Bhopal", "462016"),
        ("Malviya Nagar, Jaipur", "302017"),
    ],
)
def test_naming_the_city_picks_that_citys_area(typed, pin):
    assert geo.resolve_locality(typed).pin == pin


def test_spacing_does_not_matter():
    assert geo.resolve_locality("Shivaji Nagar, Pune").pin == geo.resolve_locality("shivajinagar pune").pin


def test_a_real_city_is_never_read_as_an_area():
    for typed in ("Mumbai", "Bombay", "Pune"):
        assert isinstance(geo.resolve_place(typed), geo.City)


def test_an_area_is_found_while_it_is_still_being_typed_but_only_in_city_mode():
    assert geo.resolve_place("koram", allow_prefix=True).pin == "560034"
    assert geo.resolve_place("koram", allow_prefix=False) is None


def test_unknown_names_resolve_to_nothing():
    assert geo.resolve_place("xyzzy") is None
    assert geo.resolve_locality("") is None
    assert geo.resolve_locality(None) is None


def test_the_area_data_ships_with_its_attribution():
    raw = json.loads(geo._LOC_DATA.read_text(encoding="utf-8"))
    assert "GeoNames" in raw["attribution"] and raw["count"] > 50_000


# ── ranking ──────────────────────────────────────────────────────────
def _b(name):
    return SimpleNamespace(name=name)


def _rank(typed, rows, *, any_exact=False):
    loc = geo.resolve_locality(typed)
    got = bs.rank_nearby_by_locality(loc, [(_b(n), p, c) for n, p, c in rows], any_exact=any_exact)
    return [(b.name, how) for b, _, how in got]


def test_a_broker_at_the_areas_pin_is_a_real_match_and_comes_first():
    got = _rank("Andheri", [("pune", "411001", "Pune"), ("andheri", "400069", "Mumbai")])
    assert got[0] == ("andheri", "pin")


def test_a_broker_with_no_pin_is_placed_by_their_city():
    got = _rank("Andheri", [("mum", None, "Mumbai"), ("delhi", None, "Delhi")])
    assert got[0] == ("mum", "city")
    assert ("delhi", "km") in got  # no real match: the far one still shows


def test_with_a_real_match_far_brokers_are_not_added():
    got = _rank("Andheri", [("andheri", "400053", "Mumbai"), ("delhi", "110001", "Delhi")])
    assert [n for n, _ in got] == ["andheri"]


def test_a_broker_that_cannot_be_placed_is_left_out():
    assert _rank("Andheri", [("ghost", None, "Qwertyville"), ("blank", None, None)]) == []


# ── end to end with a fake directory ─────────────────────────────────
class _Q:
    def __init__(self, rows):
        self.rows = rows

    def limit(self, n):
        return self

    async def to_list(self):
        return list(self.rows)


def _user(i, city=None, pin=None):
    return SimpleNamespace(
        id=f"id{i}",
        user_code=f"BRK{i}",
        full_name=f"Broker {i}",
        city=city,
        pincode=pin,
        broker_brand_name=None,
        assigned_admin_id=None,
    )


@pytest.fixture
def directory(monkeypatch):
    everyone = [
        _user(1, "Pune", "411001"),
        _user(2, "Mumbai", "400069"),  # Andheri East
        _user(3, "Mumbai", "400001"),
        _user(4, "Delhi", "110001"),
    ]

    def find(query):
        clauses = query.get("$or")
        if not clauses:
            return _Q(everyone)
        hit = [
            u
            for u in everyone
            if any((v := getattr(u, f, None)) and pat.search(str(v)) for c in clauses for f, pat in c.items())
        ]
        return _Q(hit)

    async def no_hidden():
        return set()

    monkeypatch.setattr(bs, "User", SimpleNamespace(find=find))
    monkeypatch.setattr(bs, "_hidden_set", no_hidden)
    return lambda q, by: asyncio.run(bs.search_brokers(q, by=by))


@pytest.mark.parametrize("by", ["city", "all"])
def test_searching_an_area_finds_the_broker_there(directory, by):
    out = directory("Andheri", by)
    assert out[0]["user_code"] == "BRK2" and out[0]["nearby"] is False
    assert out[0]["area"] == "In Andheri, Mumbai"
    # The rest of Mumbai is close; Delhi, with a real match in hand, is not.
    codes = [r["user_code"] for r in out]
    assert "BRK3" in codes and "BRK4" not in codes


def test_an_area_with_no_broker_says_where_it_looked(directory):
    out = directory("Koramangala", "city")
    assert out and all(r["nearby"] for r in out)
    assert out[0]["near"] == "Koramangala, Bengaluru"


def test_a_city_search_is_unchanged(directory):
    out = directory("Mumbai", "city")
    assert {r["user_code"] for r in out if not r["nearby"]} == {"BRK2", "BRK3"}
    assert all(r["area"] is None for r in out)
