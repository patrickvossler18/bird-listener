#!/usr/bin/env python3
"""Build the kachō-e target species list from BirdNET-Go's range filter.

BirdNET-Go already weights/limits detections to species plausible at your
coordinates (its range model). The set of species the window node can *ever*
report is therefore exactly that range list — so we scope illustration
generation to it, instead of drawing 400+ birds that will never show up.

This pulls the range-filtered list from a running BirdNET-Go instance:

    GET http://<host>:8080/api/v2/range/species/list?lat=..&lon=..

and writes one `Scientific|Common` line per species to species.txt (the format
pregen.py and fetch_seed_illustrations.py both read). Coordinates default to
the live values on birdpi; override with --lat/--lon for a different site.

Usage:
    python3 build_species_list.py                      # live fetch from birdpi.local
    python3 build_species_list.py --url http://birdpi.local:8080
    python3 build_species_list.py --from-json range.json   # offline, from a saved dump
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent

# Live BirdNET-Go coordinates on birdpi (San Francisco). Override per site.
DEFAULT_LAT, DEFAULT_LON = 37.7726, -122.4476


def fetch_range(url: str, lat: float, lon: float, timeout: float) -> list[dict]:
    q = urllib.parse.urlencode({"lat": lat, "lon": lon})
    full = f"{url.rstrip('/')}/api/v2/range/species/list?{q}"
    req = urllib.request.Request(full, headers={"User-Agent": "kachoe-pipeline/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read()).get("species", [])


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", default="http://birdpi.local:8080",
                    help="BirdNET-Go base URL (default: http://birdpi.local:8080)")
    ap.add_argument("--lat", type=float, default=DEFAULT_LAT)
    ap.add_argument("--lon", type=float, default=DEFAULT_LON)
    ap.add_argument("--from-json", type=Path,
                    help="Read a saved range/species/list response instead of fetching")
    ap.add_argument("--out", type=Path, default=HERE / "species.txt")
    ap.add_argument("--timeout", type=float, default=20.0)
    args = ap.parse_args()

    if args.from_json:
        species = json.loads(args.from_json.read_text()).get("species", [])
        src = str(args.from_json)
    else:
        try:
            species = fetch_range(args.url, args.lat, args.lon, args.timeout)
        except Exception as e:
            print(f"error: range fetch failed ({e}).\n"
                  f"  Is BirdNET-Go reachable at {args.url}? You can also dump it on "
                  f"birdpi with\n    curl 'http://localhost:8080/api/v2/range/species/"
                  f"list?lat={args.lat}&lon={args.lon}' > range.json\n"
                  f"  and pass --from-json range.json.", file=sys.stderr)
            return 1
        src = f"{args.url} @ ({args.lat}, {args.lon})"

    rows = []
    for s in species:
        sci = (s.get("scientificName") or "").strip()
        com = (s.get("commonName") or "").strip()
        if sci and com:
            rows.append(f"{sci}|{com}")
    rows.sort()
    if not rows:
        print("error: no species resolved from the range list", file=sys.stderr)
        return 1

    args.out.write_text("\n".join(rows) + "\n")
    print(f"wrote {len(rows)} species to {args.out}  (source: {src})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
