"""Build app/data/in_pincodes.json — PIN code -> coordinates, behind "nearest
broker by PIN".

    python -m scripts.build_in_pincodes             # downloads from GeoNames
    python -m scripts.build_in_pincodes IN.zip      # or from a local copy

Source: GeoNames postal codes for India (`export/zip/IN.zip`). GeoNames data is
CC BY 4.0 — https://www.geonames.org/ — which is why the output carries an
attribution field and the file is not to be stripped of it.

Why coordinates. Before this, "nearest PIN" was guessed from the digits: the
longest shared prefix, ties broken by how close the numbers are. The first
three digits do mean a sorting district, but the last three are just a
post-office number — 110025 is numerically nearer 110019 than 110048 is, and
further away on the map. Only coordinates can say which is closer.

GeoNames lists every post office, so one PIN has several rows. Kept per PIN:
the median of its rows' positions, using only the rows with the best accuracy
GeoNames gives that PIN — a median, so one misplaced post office cannot drag
the whole PIN across town.
"""

from __future__ import annotations

import io
import json
import pathlib
import statistics
import sys
import urllib.request
import zipfile
from collections import defaultdict

URL = "https://download.geonames.org/export/zip/IN.zip"
OUT = pathlib.Path(__file__).resolve().parents[1] / "app" / "data" / "in_pincodes.json"


def _read(source: str | None) -> str:
    if source:
        raw = pathlib.Path(source).read_bytes()
    else:
        print("downloading", URL)
        raw = urllib.request.urlopen(URL, timeout=120).read()
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        return z.read("IN.txt").decode("utf-8")


def main() -> None:
    text = _read(sys.argv[1] if len(sys.argv) > 1 else None)

    # pin -> accuracy -> [(lat, lon)]
    rows: dict[str, dict[int, list[tuple[float, float]]]] = defaultdict(lambda: defaultdict(list))
    for line in text.splitlines():
        f = line.split("\t")
        if len(f) < 11 or f[0] != "IN":
            continue
        pin = f[1].strip()
        if len(pin) != 6 or not pin.isdigit() or not f[9] or not f[10]:
            continue
        acc = int(f[11]) if len(f) > 11 and f[11].strip().isdigit() else 0
        rows[pin][acc].append((float(f[9]), float(f[10])))

    pins: dict[str, list[float]] = {}
    for pin, by_acc in rows.items():
        best = by_acc[max(by_acc)]
        pins[pin] = [
            round(statistics.median(p[0] for p in best), 4),
            round(statistics.median(p[1] for p in best), 4),
        ]

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        json.dumps(
            {
                "attribution": "Postal code data from GeoNames (https://www.geonames.org/), CC BY 4.0.",
                "source": URL,
                "count": len(pins),
                "pins": dict(sorted(pins.items())),
            },
            ensure_ascii=True,
            separators=(",", ":"),
        ),
        encoding="utf-8",
    )
    print(f"wrote {len(pins)} Indian PIN codes -> {OUT} ({OUT.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
