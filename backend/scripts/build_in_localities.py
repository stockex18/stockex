"""Build app/data/in_localities.json — area / locality name -> PIN codes, behind
"search a broker by area".

    python -m scripts.build_in_localities             # downloads from GeoNames
    python -m scripts.build_in_localities IN.zip      # or from a local copy

Source: the same GeoNames postal file as `build_in_pincodes` (CC BY 4.0 —
https://www.geonames.org/), so the output carries the attribution too.

Why. A client knows their area — "Andheri", "Koramangala", "Salt Lake" — far
more often than their PIN, and brokers only record a city and a PIN. GeoNames
lists every post office with its PIN, and a post office is named after the
area it serves. So an area name can be turned into a PIN, and from there the
existing "nearest broker by PIN" ranking does the rest.

Post-office names are not what people type, so they are cleaned first:
"Andheri H.O" -> "Andheri", "Shivaji Nagar (Pune)" -> "Shivaji Nagar",
"Bandra(East)" -> "Bandra East", which is ALSO filed under "Bandra". Keys are
lower-case with no spaces, so "Shivajinagar" and "Shivaji Nagar" meet.

One name, many places (there are Andheris in Mumbai, Gujarat and Himachal).
Each PIN carries a weight — the population of the city its district or
sub-district is named after, 0 for none — and the biggest is listed first,
the same rule as the forty Rampurs in the city gazetteer. A client can still
say which one they mean: "Shivaji Nagar, Pune".
"""

from __future__ import annotations

import io
import json
import pathlib
import re
import sys
import urllib.request
import zipfile
from collections import defaultdict

from app.services import geo_service

URL = "https://download.geonames.org/export/zip/IN.zip"
OUT = pathlib.Path(__file__).resolve().parents[1] / "app" / "data" / "in_localities.json"

#: Most places a single name keeps. The biggest come first; past a handful
#: they are villages nobody will pick without naming the city anyway.
PER_NAME = 6

_PAREN = re.compile(r"\(([^)]*)\)")
#: Post-office jargon that is not part of the area's name.
_OFFICE = re.compile(
    r"\b(?:g\.?\s?p\.?\s?o|h\.?\s?o|s\.?\s?o|b\.?\s?o|p\.?\s?o|head office|sub office|branch office)\.?\s*$",
    re.IGNORECASE,
)
_SIDES = ("east", "west", "north", "south")


def _read(source: str | None) -> str:
    if source:
        raw = pathlib.Path(source).read_bytes()
    else:
        print("downloading", URL)
        raw = urllib.request.urlopen(URL, timeout=120).read()
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        return z.read("IN.txt").decode("utf-8")


def clean(name: str) -> str:
    """What a person would call the post office's area."""
    # "Bandra(East)" is a side of Bandra, not a city qualifier.
    name = _PAREN.sub(lambda m: f" {m.group(1)}" if m.group(1).strip().lower() in _SIDES else " ", name)
    name = _OFFICE.sub("", name.strip())
    return re.sub(r"\s+", " ", name).strip(" .,-")


def keys_for(name: str) -> list[str]:
    words = geo_service.norm(name).split()
    if not words:
        return []
    out = ["".join(words)]
    if len(words) > 1 and words[-1] in _SIDES:
        out.append("".join(words[:-1]))
    return out


def main() -> None:
    text = _read(sys.argv[1] if len(sys.argv) > 1 else None)
    by_key, _ = geo_service._index()
    known_pins = geo_service._pins()

    def weight(*places: str) -> int:
        return max((by_key[k].population for p in places if (k := geo_service.norm(p)) in by_key), default=0)

    # Districts are stored once and referred to by number: most of the file
    # would otherwise be the same few hundred district names over and over.
    districts: dict[str, int] = {}
    district_rows: list[list] = []

    def district_no(name: str, w: int) -> int:
        if name not in districts:
            districts[name] = len(district_rows)
            district_rows.append([name, w])
        return districts[name]

    # key -> pin -> (area, district no)
    index: dict[str, dict[str, tuple[str, int]]] = defaultdict(dict)
    for line in text.splitlines():
        f = line.split("\t")
        if len(f) < 8 or f[0] != "IN":
            continue
        pin = f[1].strip()
        if pin not in known_pins:  # no position, nothing to measure from
            continue
        area = clean(f[2])
        district = f[5].strip()
        w = weight(district, f[7].strip())
        # The weight belongs to the district as a whole, so it is the bigger of
        # what any of its rows was named after.
        dn = district_no(district, 0)
        district_rows[dn][1] = max(district_rows[dn][1], w)
        for k in keys_for(area):
            if len(k) < 3:
                continue
            index[k].setdefault(pin, (area, dn))

    localities = {
        # One string per name, not nested lists: loaded, 125k small lists cost
        # several times the memory of 125k strings, and one search reads one.
        # "pin.district no[.area]" joined by "|"; the area is left out when it
        # is just the key spelt nicely.
        k: "|".join(
            f"{pin}.{dn}" if area.lower().replace(" ", "") == k else f"{pin}.{dn}.{area}"
            for pin, (area, dn) in sorted(pins.items(), key=lambda t: (-district_rows[t[1][1]][1], t[0]))[
                :PER_NAME
            ]
        )
        for k, pins in sorted(index.items())
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        json.dumps(
            {
                "attribution": "Postal code data from GeoNames (https://www.geonames.org/), CC BY 4.0.",
                "source": URL,
                "count": len(localities),
                # [name, weight], referred to by position from `localities`.
                "districts": district_rows,
                "localities": localities,
            },
            ensure_ascii=True,
            separators=(",", ":"),
        ),
        encoding="utf-8",
    )
    print(f"wrote {len(localities)} Indian area names -> {OUT} ({OUT.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
