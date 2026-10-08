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

import difflib
import json
import math
import pathlib
import re
from dataclasses import dataclass
from functools import lru_cache

_DATA = pathlib.Path(__file__).resolve().parents[1] / "data" / "in_cities.json"

#: A typed fragment shorter than this is never taken as the start of a city.
MIN_PREFIX = 4
#: How close a misspelling has to be (difflib ratio) to count as that city.
TYPO_CUTOFF = 0.86

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


def distance_km(a: City, b: City) -> float:
    """Great-circle distance. Straight-line, not by road — it is a ranking, and
    the label on screen says "away", not "drive"."""
    r = 6371.0
    p1, p2 = math.radians(a.lat), math.radians(b.lat)
    dp = p2 - p1
    dl = math.radians(b.lon - a.lon)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))
