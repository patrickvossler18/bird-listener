#!/usr/bin/env python3
"""Build the kachō-e target species list from BirdNET-Go's range filter.

BirdNET-Go already weights/limits detections to species plausible at your
coordinates (its range model). The set of species the window node can *ever*
report is therefore exactly that range list — so we scope illustration
generation to it, instead of drawing 400+ birds that will never show up.

This pulls the range-filtered list from a running BirdNET-Go instance:

    GET http://<host>:8080/api/v2/range/species/list?lat=..&lon=..

and writes one `Scientific|Common` line per species to species.txt (the format
pregen.py and fetch_seed_illustrations.py both read).

The BirdNET-Go UI is bound to loopback on the window node, so from another
machine the fetch goes over SSH (--ssh HOST runs curl on the Pi). Coordinates
default to whatever that BirdNET-Go is configured with (read from its
config.yaml over the same SSH connection); --lat/--lon override.

Usage:
    python3 build_species_list.py --ssh birdpi              # from your computer
    python3 build_species_list.py --url http://localhost:8080 --lat 37.77 --lon -122.44
    python3 build_species_list.py --from-json range.json    # offline, from a saved dump
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
REMOTE_CONFIG = "~/bird-listener/window-node/birdnet-go/config/config.yaml"


def fetch_range(url: str, lat: float, lon: float, timeout: float) -> list[dict]:
    q = urllib.parse.urlencode({"lat": lat, "lon": lon})
    full = f"{url.rstrip('/')}/api/v2/range/species/list?{q}"
    req = urllib.request.Request(full, headers={"User-Agent": "kachoe-pipeline/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read()).get("species", [])


def ssh_coords(host: str, timeout: float) -> tuple[float, float]:
    """Read birdnet.latitude/longitude from the window node's config.yaml."""
    out = subprocess.run(
        ["ssh", "-o", "BatchMode=yes", host, f"grep -E '^    (latitude|longitude):' {REMOTE_CONFIG}"],
        capture_output=True, text=True, timeout=timeout).stdout
    found = dict(re.findall(r"(latitude|longitude):\s*([-0-9.]+)", out))
    if "latitude" not in found or "longitude" not in found:
        raise RuntimeError(f"could not read coordinates from {host}:{REMOTE_CONFIG}")
    return float(found["latitude"]), float(found["longitude"])


def ssh_fetch_range(host: str, lat: float, lon: float, timeout: float) -> list[dict]:
    q = urllib.parse.urlencode({"lat": lat, "lon": lon})
    cmd = f"curl -sf 'http://localhost:8080/api/v2/range/species/list?{q}'"
    p = subprocess.run(["ssh", "-o", "BatchMode=yes", host, cmd],
                       capture_output=True, text=True, timeout=timeout)
    if p.returncode != 0:
        raise RuntimeError(p.stderr.strip() or f"ssh {host} exited {p.returncode}")
    return json.loads(p.stdout).get("species", [])


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ssh", metavar="HOST",
                    help="Fetch via `ssh HOST curl localhost:8080` (the UI is loopback-only)")
    ap.add_argument("--url", default="http://localhost:8080",
                    help="BirdNET-Go base URL when reachable directly (default: %(default)s)")
    ap.add_argument("--lat", type=float, help="Override latitude (default: the node's own)")
    ap.add_argument("--lon", type=float, help="Override longitude")
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
            lat, lon = args.lat, args.lon
            if args.ssh and (lat is None or lon is None):
                lat, lon = ssh_coords(args.ssh, args.timeout)
            if lat is None or lon is None:
                print("error: --lat and --lon are required without --ssh", file=sys.stderr)
                return 2
            if args.ssh:
                species = ssh_fetch_range(args.ssh, lat, lon, args.timeout)
                src = f"ssh {args.ssh} @ ({lat}, {lon})"
            else:
                species = fetch_range(args.url, lat, lon, args.timeout)
                src = f"{args.url} @ ({lat}, {lon})"
        except Exception as e:
            print(f"error: range fetch failed ({e}).\n"
                  f"  Is the window node up? You can also dump the list on it with\n"
                  f"    curl 'http://localhost:8080/api/v2/range/species/list?lat=..&lon=..' > range.json\n"
                  f"  and pass --from-json range.json.", file=sys.stderr)
            return 1

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
