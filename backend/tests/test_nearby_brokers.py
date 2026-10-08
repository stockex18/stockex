"""No broker in the city you searched? Show the nearest. PIN codes work the same way.

"Agar user koi city search kare aur us city ka broker nahi hai to jo sabse paas
ho wo dikha dena. PIN code me bhi same flow."

An empty list reads as "nobody serves you", which is the wrong thing to tell a
client about to sign up. Nearest needs coordinates, and coordinates cannot be
had from a city NAME without a gazetteer, so one is bundled (GeoNames, built by
scripts/build_in_cities.py) and the search never touches the network.

The two decisions the tests exist to protect:

  * exact matches are NEVER displaced. With real matches, only genuinely close
    extras are added; with none, the nearest few are shown however far.
  * a name that cannot be resolved ranks nothing. A wrong city would rank
    brokers by distance from a place the client never meant and look
    authoritative while doing it.
"""

from __future__ import annotations

import asyncio
import pathlib
from types import SimpleNamespace

import pytest

from app.services import broker_search_service as bs
from app.services import geo_service as geo


# ── reading a city name ──────────────────────────────────────────────
@pytest.mark.parametrize("typed,expected", [
    ("Mumbai", "Mumbai"), ("mumbai ", "Mumbai"), ("  MUMBAI", "Mumbai"),
    ("Bombay", "Mumbai"), ("Bangalore", "Bengaluru"), ("banglore", "Bengaluru"),
    ("Gurgaon", "Gurugram"), ("Calcutta", "Kolkata"), ("Madras", "Chennai"),
    ("Allahabad", "Prayagraj"), ("Poona", "Pune"), ("Trivandrum", "Thiruvananthapuram"),
])
def test_the_names_people_actually_type_find_the_right_city(typed, expected):
    c = geo.resolve(typed)
    assert c is not None and c.name == expected


def test_a_city_is_found_while_it_is_still_being_typed():
    """The picker searches as you type."""
    assert geo.resolve("mumb").name == "Mumbai"


def test_but_not_from_a_stub_too_short_to_mean_anything():
    assert geo.resolve("mu", allow_prefix=True) is None
    assert geo.resolve("m") is None


def test_gibberish_resolves_to_nothing_rather_than_the_closest_guess():
    assert geo.resolve("xyzzy") is None
    assert geo.resolve("") is None
    assert geo.resolve(None) is None


def test_prefix_guessing_can_be_turned_off():
    """Used in the All view, where a person's name must not become a city."""
    assert geo.resolve("ashok", allow_prefix=False) is None


def test_two_places_with_one_name_go_to_the_bigger():
    from app.services.geo_service import _index

    import json
    from collections import defaultdict

    by_key, _ = _index()
    raw = json.loads(pathlib.Path(geo._DATA).read_text(encoding="utf-8"))["cities"]
    pops = defaultdict(list)
    for c in raw:
        for nm in (c["n"], *c["a"]):
            pops[geo.norm(nm)].append(c["p"])
    shared = [k for k, v in pops.items() if len(v) > 1]
    assert shared, "expected at least one name shared by several places"
    for k in shared[:200]:
        assert by_key[k].population == max(pops[k]), k


def test_distances_agree_with_the_real_ones():
    m, p, d = geo.resolve("Mumbai"), geo.resolve("Pune"), geo.resolve("Delhi")
    assert 110 <= geo.distance_km(m, p) <= 130       # ~120 km
    assert 1100 <= geo.distance_km(m, d) <= 1200     # ~1,150 km
    assert geo.distance_km(m, m) == 0


def test_the_data_ships_with_its_attribution():
    """GeoNames is CC BY 4.0. The file carries the credit; stripping it is a licence breach."""
    import json

    raw = json.loads(pathlib.Path(geo._DATA).read_text(encoding="utf-8"))
    assert "GeoNames" in raw["attribution"] and "CC BY" in raw["attribution"]
    assert raw["count"] > 5000


def test_resolution_makes_no_network_call():
    import inspect

    src = inspect.getsource(geo)
    assert "urllib" not in src and "httpx" not in src and "requests" not in src


# ── ranking by city ──────────────────────────────────────────────────
def _b(name):
    return SimpleNamespace(name=name)


def _near(target, cities, *, any_exact):
    t = geo.resolve(target)
    got = bs.rank_nearby_by_city(t, [(_b(c), c) for c in cities], any_exact=any_exact)
    return [(b.name, round(km)) for b, km in got]


def test_with_no_broker_in_the_city_the_nearest_come_first():
    out = _near("Pune", ["Delhi", "Mumbai", "Nashik", "Chennai"], any_exact=False)
    assert [n for n, _ in out][:2] == ["Mumbai", "Nashik"]


def test_with_none_close_the_nearest_are_still_shown_however_far():
    """The alternative is an empty screen."""
    out = _near("Pune", ["Delhi", "Chennai"], any_exact=False)
    assert [n for n, _ in out] == ["Chennai", "Delhi"]


def test_with_real_matches_only_close_extras_are_added():
    """A client in Mumbai is not offered Delhi beside the broker in Mumbai."""
    out = _near("Mumbai", ["Pune", "Delhi", "Chennai"], any_exact=True)
    assert [n for n, _ in out] == ["Pune"]


def test_the_radius_is_what_separates_close_from_far():
    assert bs.NEARBY_RADIUS_KM == 150
    assert _near("Mumbai", ["Pune"], any_exact=True)[0][1] < bs.NEARBY_RADIUS_KM


def test_once_the_same_city_has_a_broker_the_far_fallback_switches_off():
    """Otherwise a search for Mumbai would list its own broker (typed Bombay) and
    then Delhi, as if nobody were in Mumbai."""
    out = _near("Mumbai", ["Bombay", "Pune", "Delhi", "Chennai"], any_exact=False)
    assert [n for n, _ in out] == ["Bombay", "Pune"]


def test_the_old_name_for_the_same_city_is_zero_km_away():
    """A broker who typed Bombay is a Mumbai broker."""
    out = _near("Mumbai", ["Bombay"], any_exact=False)
    assert out == [("Bombay", 0)]


def test_a_broker_whose_city_cannot_be_read_is_left_out_not_guessed():
    out = _near("Pune", ["Mumbai", "Zzzzzz", ""], any_exact=False)
    assert [n for n, _ in out] == ["Mumbai"]


def test_a_broker_with_no_city_at_all_is_left_out():
    t = geo.resolve("Pune")
    got = bs.rank_nearby_by_city(t, [(_b("x"), None), (_b("y"), "Mumbai")], any_exact=False)
    assert [b.name for b, _ in got] == ["y"]


def test_there_is_a_cap_on_how_many_are_added():
    cities = ["Mumbai", "Nashik", "Thane", "Nagpur", "Indore", "Surat", "Delhi", "Jaipur"]
    assert len(_near("Pune", cities, any_exact=False)) == bs.NEARBY_MAX == 5


# ── ranking by PIN ───────────────────────────────────────────────────
def _pin(needle, pins, *, any_exact):
    got = bs.rank_nearby_by_pin(needle, [(_b(p), p) for p in pins], any_exact=any_exact)
    return [(b.name, cp) for b, cp in got]


def test_a_longer_shared_pin_prefix_is_a_smaller_area():
    out = _pin("400001", ["400706", "410210", "560001"], any_exact=False)
    # 560001 shares nothing with 400001, so it is not "nearby" at all.
    assert out == [("400706", 3), ("410210", 1)]


def test_with_real_matches_a_distant_pin_is_not_added():
    """Sharing one digit is not near. With real hits it needs two."""
    out = _pin("400001", ["410210", "402301"], any_exact=True)
    assert out == [("402301", 2)]            # two shared digits: kept
    assert "410210" not in [n for n, _ in out]  # one shared digit: dropped


def test_with_no_real_match_even_a_one_digit_neighbour_is_shown():
    assert ("410210", 1) in _pin("400001", ["410210"], any_exact=False)


def test_ties_are_broken_by_how_close_the_numbers_are():
    out = _pin("400001", ["400900", "400100"], any_exact=False)
    assert [n for n, _ in out] == ["400100", "400900"]


def test_a_pin_that_matches_the_typed_prefix_is_already_an_exact_hit_not_nearby():
    out = _pin("4000", ["400001", "400099", "410001"], any_exact=False)
    assert [n for n, _ in out] == ["410001"]


def test_malformed_pins_are_ignored():
    out = _pin("400001", ["", "40001", "abcdef", "4000011", "400100"], any_exact=False)
    assert [n for n, _ in out] == ["400100"]


def test_the_labels_tell_a_client_what_near_means():
    assert bs._PIN_AREA == {3: "Same area", 2: "Same region", 1: "Same part of India"}


# ── the search itself, end to end with a fake directory ──────────────
class _Q:
    """Beanie's `User.find(...).limit(n).to_list()`, over a fixed list."""

    def __init__(self, rows):
        self.rows = rows

    def limit(self, n):
        return self

    async def to_list(self):
        return list(self.rows)


def _user(i, city=None, pin=None, brand=None, name=None):
    return SimpleNamespace(
        id=f"id{i}", user_code=f"BRK{i}", full_name=name or f"Broker {i}",
        city=city, pincode=pin, broker_brand_name=brand, assigned_admin_id=None,
    )


@pytest.fixture
def directory(monkeypatch):
    """A search over a fake set of brokers. `exact` is what Mongo's regex would
    have returned for the needle; the full list is the pool for nearby."""
    everyone = {
        "pune": _user(1, "Pune", "411001"),
        "mumbai": _user(2, "Mumbai", "400001"),
        "bombay": _user(3, "Bombay", "400050"),
        "delhi": _user(4, "Delhi", "110001"),
        "nocity": _user(5),
    }

    def find(query):
        clauses = query.get("$or")
        if not clauses:  # the nearby POOL: role + status only, no needle
            return _Q(list(everyone.values()))
        hit = []
        for u in everyone.values():
            for clause in clauses:
                ((field, pat),) = clause.items()
                val = getattr(u, field, None)
                if val and pat.search(str(val)):
                    hit.append(u)
                    break
        return _Q(hit)

    fake_user = SimpleNamespace(find=find)

    async def no_hidden():
        return set()

    monkeypatch.setattr(bs, "User", fake_user)
    monkeypatch.setattr(bs, "_hidden_set", no_hidden)

    def run(q, by):
        return asyncio.run(bs.search_brokers(q, by=by))

    return run


def test_a_city_with_a_broker_lists_it_first_and_marks_nothing_nearby_that_is_far(directory):
    out = directory("Mumbai", "city")
    assert out[0]["user_code"] == "BRK2" and out[0]["nearby"] is False
    # Pune is within the radius, Delhi is not.
    near = [r["user_code"] for r in out if r["nearby"]]
    assert "BRK1" in near and "BRK4" not in near


def test_a_city_with_no_broker_shows_the_nearest_instead_of_nothing(directory):
    out = directory("Nashik", "city")
    assert out, "an empty list is the answer this feature exists to avoid"
    assert all(r["nearby"] for r in out)
    assert out[0]["user_code"] in {"BRK1", "BRK2", "BRK3"}  # Maharashtra before Delhi
    assert out[0]["distance_km"] is not None and out[0]["near"] == "Nashik"


def test_the_synonym_comes_back_as_the_same_city(directory):
    """Searching Mumbai finds the broker who typed Bombay — as in the same city."""
    out = directory("Mumbai", "city")
    bombay = [r for r in out if r["user_code"] == "BRK3"][0]
    # A real match, not a neighbour: no "nearby" heading over a broker who is
    # in the city, just under an older name.
    assert bombay["nearby"] is False and bombay["distance_km"] == 0


def test_a_pin_with_no_match_shows_the_nearest_pins(directory):
    out = directory("4100", "pincode")      # no 4100xx PIN exists in the fake set
    near = {r["user_code"]: r for r in out}
    assert all(r["nearby"] for r in out)
    assert near["BRK2"]["area"] in {"Same region", "Same part of India", "Same area"}
    assert near["BRK2"]["distance_km"] is None


def test_a_two_digit_pin_is_too_short_to_say_anything_about_nearby(directory):
    out = directory("41", "pincode")
    assert [r["user_code"] for r in out] == ["BRK1"]      # the exact 41xxxx hit...
    assert all(r["nearby"] is False for r in out)          # ...and no nearby noise


def test_in_the_all_view_a_normal_hit_gets_no_nearby_noise(directory):
    """A rescue only: with a real match for the name, nothing else is added."""
    out = directory("Broker 2", "all")
    assert all(r["nearby"] is False for r in out)


def test_in_the_all_view_a_dead_end_is_rescued_when_it_is_a_city(directory):
    out = directory("Nashik", "all")
    assert out and all(r["nearby"] for r in out)


def test_the_all_view_does_not_turn_a_persons_name_into_a_city(directory):
    """"Ashok" is a person; "Ashoknagar" is a town. In All, prefix guessing is off."""
    assert directory("ashok", "all") == []


def test_every_row_carries_the_new_fields_even_when_nothing_is_nearby(directory):
    for r in directory("Mumbai", "city"):
        assert {"nearby", "distance_km", "area", "near"} <= set(r)


def test_a_failure_in_the_nearby_lookup_never_costs_the_real_answer(directory, monkeypatch):
    async def boom(*a, **k):
        raise RuntimeError("gazetteer missing")

    monkeypatch.setattr(bs, "_nearby", boom)
    out = directory("Mumbai", "city")
    assert out and out[0]["user_code"] == "BRK2"


# ── the picker ───────────────────────────────────────────────────────
_FE = pathlib.Path(__file__).resolve().parents[2] / "frontend-user"


def _picker():
    return (_FE / "components" / "common" / "BrokerPicker.tsx").read_text(encoding="utf-8", errors="ignore")


def test_the_picker_keeps_real_matches_apart_from_nearby_ones():
    s = _picker()
    assert "const exactRows = brokers.filter((b) => !b.nearby)" in s
    assert "const nearRows = brokers.filter((b) => b.nearby)" in s
    assert s.index("exactRows.map(renderRow)") < s.index("nearRows.map(renderRow)")


def test_it_says_plainly_there_is_no_broker_in_that_place():
    s = _picker()
    assert "No brokers in ${where} yet. The nearest ones:" in s
    assert '"Also nearby"' in s


def test_it_shows_how_far_not_just_that_it_is_near():
    s = _picker()
    assert "≈ ${b.distance_km} km away" in s
    # A same-city synonym says which city it is the same as, and shows even
    # though it is listed with the real matches rather than under "nearby".
    assert "Same city as ${b.near" in s
    assert "b.distance_km === 0" in s
    assert "b.area" in s
