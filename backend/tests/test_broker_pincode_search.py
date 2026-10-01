"""A client finds their broker by PIN code as well as by city.

A city name is a blunt instrument. "Thane" and "Mumbai" are the same market
to a client and different strings to a search, and a big city has more
brokers in it than a picker can usefully list. A PIN code is exact, and its
PREFIX is a locality — 560001 and 560034 are both central Bangalore.

Operator: "pin code wise and city wise broker search kar paye... aur all
users ka option bhi mile."

So the picker has three modes and the search has to honour all three:

    all      city, PIN, name and code  — the widest net, and the default
    city     city only
    pincode  PIN only, matched on the PREFIX

Two things are easy to get wrong and are pinned here. A PIN typed in "all"
mode must not be matched against `user_code`, or a code containing those
digits outranks the brokers actually near the client. And a PIN prefix must
anchor at the start: "5600" means Bangalore, and must not drag in 125600,
which is Haryana.
"""

from __future__ import annotations

import re

from app.services.broker_search_service import SEARCH_FIELDS


def _fields(by: str) -> list[str]:
    return SEARCH_FIELDS.get(by, SEARCH_FIELDS["all"])


# ── the three modes ───────────────────────────────────────────────────
def test_the_default_mode_searches_everything():
    assert set(_fields("all")) == {"city", "pincode", "full_name", "user_code"}


def test_city_mode_searches_only_the_city():
    assert _fields("city") == ["city"]


def test_pincode_mode_searches_only_the_pincode():
    assert _fields("pincode") == ["pincode"]


def test_an_unknown_mode_falls_back_to_the_widest_net():
    """A bad `by` from a stale client must still return brokers, not none."""
    assert _fields("nonsense") == _fields("all")


def test_pin_mode_cannot_be_matched_against_a_user_code():
    """The reason PIN is its own mode: a bare 6-digit number typed into a
    single combined box hits codes too, and the client gets strangers."""
    assert "user_code" not in _fields("pincode")
    assert "full_name" not in _fields("pincode")


# ── how the needle is turned into a query ─────────────────────────────
def _compile(field: str, needle: str) -> re.Pattern:
    """Mirrors the one expression in `search_brokers` that builds the regex."""
    esc = re.escape(needle)
    return re.compile(("^" + esc) if field == "pincode" else esc, re.IGNORECASE)


def test_a_pin_prefix_finds_the_locality():
    rx = _compile("pincode", "5600")
    assert rx.search("560001")
    assert rx.search("560034")


def test_a_pin_prefix_does_not_reach_into_the_middle_of_another_pin():
    """125600 is Haryana. Substring matching would hand it to a client in
    Bangalore, and the list would look random rather than local."""
    assert not _compile("pincode", "5600").search("125600")


def test_a_full_pin_still_matches_itself():
    assert _compile("pincode", "560001").search("560001")


def test_city_matching_stays_a_substring_and_ignores_case():
    """Unlike a PIN, a place name is typed partially and in any case —
    "mumb" has to find Mumbai, and "NAVI" has to find Navi Mumbai."""
    assert _compile("city", "mumb").search("Mumbai")
    assert _compile("city", "NAVI").search("Navi Mumbai")


def test_a_needle_with_regex_characters_is_taken_literally():
    """Otherwise a client typing "a+b" or "(" crashes the search."""
    assert _compile("city", "a+b").search("a+b nagar")
    assert _compile("city", "(").search("(old) town")


# ── browsing with no needle at all ────────────────────────────────────
def test_an_empty_needle_is_not_filtered_in_any_mode():
    """"All users" is a real state of the picker: a client who knows neither
    a city nor a PIN still has to be able to scroll the list."""
    import inspect

    from app.services import broker_search_service

    src = inspect.getsource(broker_search_service.search_brokers)
    # The $or is built only when there IS a needle.
    assert "if needle:" in src
    assert src.index("if needle:") < src.index('query["$or"]')


def test_the_pincode_is_returned_to_the_picker():
    """The mode is useless if the row cannot show which PIN it matched."""
    import inspect

    from app.services import broker_search_service

    src = inspect.getsource(broker_search_service.search_brokers)
    assert '"pincode": getattr(r, "pincode", None)' in src
