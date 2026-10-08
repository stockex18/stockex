"""Build app/data/in_cities.json — the Indian-city gazetteer behind "nearest broker".

    python -m scripts.build_in_cities

Source: GeoNames `cities5000` (every place with a population of 5,000 or more),
filtered to India. GeoNames data is CC BY 4.0 — https://www.geonames.org/ —
which is why the output carries an attribution field and the file is not to be
stripped of it.

Why a gazetteer at all. A client who searches "Pune" when no broker is in Pune
should be shown whoever is NEAREST, and "nearest" needs coordinates. There is
no honest way to get that from a city NAME. Shipping the data means the search
never makes a network call, never rate-limits, and gives the same answer
tomorrow.

What is kept per city: its name, the alternate spellings people actually type
(Bangalore for Bengaluru, Bombay for Mumbai, Gurgaon for Gurugram), latitude,
longitude, population and state code. Population is what breaks ties between
the forty places called Rampur: the biggest wins.

Alternate names are limited to plain ASCII. GeoNames lists the name in every
script it has seen; a broker types "Mumbai", not the Devanagari, and carrying
the rest only makes the file larger.
"""

from __future__ import annotations

import io
import json
import pathlib
import re
import urllib.request
import zipfile

URL = "https://download.geonames.org/export/dump/cities5000.zip"
OUT = pathlib.Path(__file__).resolve().parents[1] / "app" / "data" / "in_cities.json"

_ASCII_NAME = re.compile(r"^[A-Za-z][A-Za-z .'-]{1,38}$")
# Generous, because the cap is what lost "Calcutta": shortest-first with a cap of
# eight let airport codes ("BOM") and typos crowd out the old names people still
# type. Codes are now dropped outright and the cap is wide enough for the
# historical spellings.
_MAX_ALTS = 24


def main() -> None:
    print("downloading", URL)
    raw = urllib.request.urlopen(URL, timeout=120).read()
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        text = z.read("cities5000.txt").decode("utf-8")

    cities = []
    for line in text.splitlines():
        f = line.split("\t")
        if len(f) < 15 or f[8] != "IN":
            continue
        name, ascii_name = f[1], f[2]
        alts_all = [a.strip() for a in f[3].split(",") if a.strip()]
        # Keep spellings someone could type on a keyboard, not duplicates of the
        # primary name, shortest first (the common ones are the short ones).
        seen = {name.lower(), ascii_name.lower()}
        alts: list[str] = []
        for a in sorted(alts_all, key=len):
            # An all-caps short token is an airport/station code, not a place name.
            if a.isupper() and len(a) <= 4:
                continue
            if _ASCII_NAME.match(a) and a.lower() not in seen:
                seen.add(a.lower())
                alts.append(a)
            if len(alts) >= _MAX_ALTS:
                break
        cities.append(
            {
                "n": ascii_name or name,
                "a": alts,
                "lat": round(float(f[4]), 4),
                "lon": round(float(f[5]), 4),
                "p": int(f[14] or 0),
                "s": f[10],
            }
        )

    cities.sort(key=lambda c: -c["p"])
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        json.dumps(
            {
                "attribution": "City data from GeoNames (https://www.geonames.org/), CC BY 4.0.",
                "source": URL,
                "count": len(cities),
                "cities": cities,
            },
            ensure_ascii=True,
            separators=(",", ":"),
        ),
        encoding="utf-8",
    )
    print(f"wrote {len(cities)} Indian cities -> {OUT} ({OUT.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
