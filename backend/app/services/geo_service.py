"""Where is this city, and how far is it from that one?

Backs "no broker in your city? here is who is nearest". It answers from a
bundled GeoNames gazetteer (`app/data/in_cities.json`, built by
`scripts/build_in_cities.py`), never from the network: the broker picker is a
public, pre-login endpoint, and a lookup that can time out or rate-limit has no
business sitting in it.

The hard part is not the distance, it is the NAME. Brokers type their city by
hand — "Mumbai", "mumbai ", "Bombay", "Banglore" — and a client types whatever
they type. So resolution is layered, strictest first, and returns nothing
rather than guess when it is not sure:

  1. the whole string is a known name or a known alternate spelling
  2. a typo of one (a close match, high bar)
  3. what has been typed SO FAR is the start of one, but only past three
     letters — the picker searches as you type, and "pun" should not be
     answered with the nearest "Punch…" in Punjab

A wrong city is worse than none: it would rank brokers by distance from
somewhere the client never meant, and look authoritative while doing it.
Ties between places that share a name (the forty Rampurs) go to the biggest.

Data: GeoNames, CC BY 4.0 — https://www.geonames.org/
"""

from __future__ import annotations

import bisect
import difflib
import json
import math
import pathlib
import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

_DATA = pathlib.Path(__file__).resolve().parents[1] / "data" / "in_cities.json"
#: PIN code -> [lat, lon], built by `scripts/build_in_pincodes.py` from GeoNames.
_PIN_DATA = pathlib.Path(__file__).resolve().parents[1] / "data" / "in_pincodes.json"
#: Area / locality name -> PIN codes, built by `scripts/build_in_localities.py`.
_LOC_DATA = pathlib.Path(__file__).resolve().parents[1] / "data" / "in_localities.json"

#: A typed fragment shorter than this is never taken as the start of a city.
MIN_PREFIX = 4
#: How close a misspelling has to be (difflib ratio) to count as that city.
TYPO_CUTOFF = 0.86
#: An area is only taken from the start of its name past this many letters —
#: there are far more areas than cities, so a stub matches far more of them.
AREA_MIN_PREFIX = 5
#: "Shivaji Nagar, Pune": the Shivaji Nagar this close to Pune is the one meant.
AREA_IN_CITY_KM = 50

_NON_ALNUM = re.compile(r"[^a-z0-9]+")


@dataclass(frozen=True)
class City:
    name: str
    lat: float
    lon: float
    population: int
    state: str


def norm(text: str | None) -> str:
    """Lower-case, letters and digits only, single spaces."""
    return _NON_ALNUM.sub(" ", (text or "").lower()).strip()


@lru_cache(maxsize=1)
def _index() -> tuple[dict[str, City], list[str]]:
    """normalised name or spelling -> City (the biggest wins a shared name), and
    every key sorted so prefix search is a scan of a short, ordered list."""
    raw = json.loads(_DATA.read_text(encoding="utf-8"))
    by_key: dict[str, City] = {}
    for c in raw["cities"]:  # already sorted by population, biggest first
        city = City(c["n"], c["lat"], c["lon"], c["p"], c["s"])
        for nm in (c["n"], *c["a"]):
            k = norm(nm)
            if k and k not in by_key:
                by_key[k] = city
    return by_key, sorted(by_key)


def resolve(text: str | None, *, allow_prefix: bool = True) -> City | None:
    """The city `text` means, or None when it is not clearly any one of them."""
    q = norm(text)
    if len(q) < 2:
        return None
    by_key, keys = _index()

    hit = by_key.get(q)
    if hit:
        return hit

    # A close misspelling: "banglore", "mumbay", "ahmedabd".
    if len(q) >= 5:
        close = difflib.get_close_matches(q, keys, n=1, cutoff=TYPO_CUTOFF)
        if close:
            return by_key[close[0]]

    # Partway through typing a name. Biggest city that starts with it.
    if allow_prefix and len(q) >= MIN_PREFIX:
        best: City | None = None
        for k in keys:
            if k.startswith(q):
                c = by_key[k]
                if best is None or c.population > best.population:
                    best = c
        return best
    return None


@dataclass(frozen=True)
class Locality:
    """An area a client typed, pinned to the PIN code of its post office."""

    name: str  # "Andheri, Mumbai" — what the client is shown
    pin: str
    #: Every PIN filed under this area name in the same district: Andheri is
    #: 400053 and 400069, and a broker at either is IN Andheri.
    pins: frozenset[str]
    point: City
    #: Population of the city the district is named after, 0 for none.
    weight: int
    #: That city, when the district is named after one.
    city: City | None = None


def is_city_name(text: str | None) -> bool:
    """True when `text` is exactly a known city name or spelling — no typo or
    prefix guessing. A real city beats an area of the same name."""
    return norm(text) in _index()[0]


@lru_cache(maxsize=1)
def _localities() -> tuple[dict[str, str], list[list[Any]], list[str]]:
    raw = json.loads(_LOC_DATA.read_text(encoding="utf-8"))
    loc = raw["localities"]
    return loc, raw["districts"], sorted(loc)


def _area_key(text: str | None) -> str:
    """Area names are matched with no spaces: "Shivajinagar" = "Shivaji Nagar"."""
    return norm(text).replace(" ", "")


#: (pin, district, weight, area name if stored).
_Entry = tuple[str, str, int, str | None]


def _entries(key: str) -> list[_Entry]:
    """The places filed under `key`, biggest district first."""
    loc, districts, _ = _localities()
    out: list[_Entry] = []
    for part in (loc.get(key) or "").split("|"):
        if not part:
            continue
        pin, dn, *area = part.split(".", 2)
        name, weight = districts[int(dn)]
        out.append((pin, name, weight, area[0] if area else None))
    return out


def _locality(key: str, typed: str, entries: list[_Entry], pick: int) -> Locality | None:
    pin, district, weight, area = entries[pick]
    point = pin_point(pin)
    if point is None:
        return None
    # The area as the client typed it when the data has no nicer spelling.
    shown = area or (typed.title() if _area_key(typed) == key else key.title())
    name = shown if not district or norm(district) == norm(shown) else f"{shown}, {district}"
    pins = frozenset(e[0] for e in entries if e[1] == district)
    return Locality(name, pin, pins, point, weight, resolve(district, allow_prefix=False))


def resolve_locality(text: str | None, *, allow_prefix: bool = False) -> Locality | None:
    """The area `text` names — "Andheri", "Koramangala", "Shivaji Nagar, Pune" —
    or None. One name in many districts goes to the biggest unless a city is
    named after it. Prefix matching only past `AREA_MIN_PREFIX` letters."""
    q = norm(text)
    key = q.replace(" ", "")
    if len(key) < 3:
        return None

    entries = _entries(key)
    if entries:
        return _locality(key, q, entries, 0)

    # "<area> <city>" / "<area>, <city>": the area closest to that city.
    words = q.split()
    for cut in range(len(words) - 1, 0, -1):
        area_words, city_words = words[:cut], words[cut:]
        city = resolve(" ".join(city_words), allow_prefix=False)
        if city is None:
            continue
        akey = "".join(area_words)
        entries = _entries(akey)
        best, best_km = None, None
        for i, e in enumerate(entries):
            pt = pin_point(e[0])
            km = distance_km(city, pt) if pt else None
            if km is not None and km <= AREA_IN_CITY_KM and (best_km is None or km < best_km):
                best, best_km = i, km
        if best is not None:
            return _locality(akey, " ".join(area_words), entries, best)

    if allow_prefix and len(key) >= AREA_MIN_PREFIX:
        _, _, keys = _localities()
        best_key, best_w = None, -1
        i = bisect.bisect_left(keys, key)
        while i < len(keys) and keys[i].startswith(key):
            w = _entries(keys[i])[0][2]
            # Biggest place first; between equals, the shortest name — the one
            # nearest to what has been typed.
            if w > best_w or (w == best_w and best_key and len(keys[i]) < len(best_key)):
                best_key, best_w = keys[i], w
            i += 1
        if best_key:
            return _locality(best_key, q, _entries(best_key), 0)
    return None


def resolve_place(text: str | None, *, allow_prefix: bool = True) -> City | Locality | None:
    """A city or, failing that, an area — strictest reading first:

      1. exactly a city name ("Mumbai", "Bombay")
      2. exactly an area name, or "<area>, <city>" ("Andheri", "Bandra, Mumbai")
      3. a city typo, or a city still being typed
      4. an area still being typed

    So an area is never displaced by a city that merely looks like it, and a
    real city is never displaced by a village that shares its name."""
    if is_city_name(text):
        return resolve(text, allow_prefix=False)
    return (
        resolve_locality(text)
        or resolve(text, allow_prefix=allow_prefix)
        or (resolve_locality(text, allow_prefix=True) if allow_prefix else None)
    )


@lru_cache(maxsize=1)
def _pins() -> dict[str, list[float]]:
    return json.loads(_PIN_DATA.read_text(encoding="utf-8"))["pins"]


def pin_point(pin: str | None) -> City | None:
    """Where a 6-digit PIN code is, or None when it is not one we know.

    Coarse in places: GeoNames gives some PINs only their sub-district's
    centre, so several PINs of one city can share a point (Bengaluru's 109 PINs
    sit on 12). Callers treat equal distances as "can't tell" and break the
    tie some other way rather than reading meaning into it."""
    p = (pin or "").strip()
    if len(p) != 6 or not p.isdigit():
        return None
    hit = _pins().get(p)
    if hit is None:
        return None
    return City(p, hit[0], hit[1], 0, "")


def distance_km(a: City, b: City) -> float:
    """Great-circle distance. Straight-line, not by road — it is a ranking, and
    the label on screen says "away", not "drive"."""
    r = 6371.0
    p1, p2 = math.radians(a.lat), math.radians(b.lat)
    dp = p2 - p1
    dl = math.radians(b.lon - a.lon)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))
