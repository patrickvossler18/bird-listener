"""birdlistener: set up and look after a bird-listener install from your computer."""
from __future__ import annotations

import argparse
import sys

from . import __version__, geocode, site


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="birdlistener",
        description="Flash the Pis, build the bird art, check on both nodes. "
                    "Every question has a flag, so it works for people and for agents.")
    ap.add_argument("--version", action="version", version=f"birdlistener {__version__}")
    sub = ap.add_subparsers(dest="command", required=True)

    f = sub.add_parser("flash", help="write an SD card that installs itself on first boot")
    f.add_argument("--node", choices=["window", "wall"])
    f.add_argument("--pi", choices=["zero-2-w", "zero-w"], default="zero-2-w",
                   help="wall node board (the original Zero W needs the 32-bit image)")
    f.add_argument("--wifi-ssid")
    f.add_argument("--wifi-password")
    f.add_argument("--location", help="town / postcode, or 'lat, lon'")
    f.add_argument("--lat", type=float)
    f.add_argument("--lon", type=float)
    f.add_argument("--country", help="2-letter code for WiFi regulations (from the location if omitted)")
    f.add_argument("--timezone", help="IANA zone (default: this computer's)")
    f.add_argument("--user", help="login user on the Pis (default: pi)")
    f.add_argument("--window-host", help="hostname for the window node (default: birdpi)")
    f.add_argument("--wall-host", help="hostname for the wall node (default: birdwall)")
    f.add_argument("--device", help="SD card device, e.g. /dev/disk4 or /dev/sdb")
    f.add_argument("--repo-url", help="git URL install.sh clones on first boot")
    f.add_argument("--repo-ref", help="branch or tag to install (default: main)")
    f.add_argument("--out-dir", help="where to write the cloud-init files")
    f.add_argument("--emit-only", action="store_true",
                   help="only write the cloud-init files (copy them to a card yourself)")
    f.add_argument("--dry-run", action="store_true", help="show the plan and the write command, write nothing")
    f.add_argument("-y", "--yes", action="store_true", help="no confirmations")

    g = sub.add_parser("geocode", help="look up coordinates for a place (Nominatim)")
    g.add_argument("place")
    g.add_argument("--country", help="2-letter code to scope a bare postcode")

    a = sub.add_parser("art", help="build the kachō-e cutouts for your birds and sync them to the wall")
    a.add_argument("--repo", help="path to the bird-listener checkout (default: current directory)")
    a.add_argument("--window-host")
    a.add_argument("--wall-host")
    a.add_argument("--gemini-key", help="or GEMINI_API_KEY in the environment / repo .env")
    a.add_argument("--from-json", help="use a saved range list instead of asking the window node")
    a.add_argument("--bundle", help="skip generation: fetch a prebuilt bundle by name (sf-bay-area) or URL")
    a.add_argument("--docker", action="store_true", help="run the pipeline in Docker instead of a local venv")
    a.add_argument("--skip-generate", action="store_true", help="seed only; no Gemini calls")
    a.add_argument("--limit", type=int, default=0, help="generate at most N species (testing)")
    a.add_argument("--no-sync", action="store_true", help="build only; don't push to the wall node")
    a.add_argument("--dry-run", action="store_true", help="show the plan and cost, change nothing")

    d = sub.add_parser("doctor", help="health report for both nodes")
    d.add_argument("--node", choices=["window", "wall"])
    d.add_argument("--window-host")
    d.add_argument("--wall-host")
    d.add_argument("--json", action="store_true")

    u = sub.add_parser("update", help="pull the latest code on each node and re-run setup")
    u.add_argument("--node", choices=["window", "wall"])
    u.add_argument("--window-host")
    u.add_argument("--wall-host")
    u.add_argument("--rsync", action="store_true", help="push this checkout instead of git pull")
    u.add_argument("--repo", help="checkout to push with --rsync")

    s = sub.add_parser("site", help="show what this computer remembers about the install")
    s.add_argument("--path", action="store_true", help="print the site file path only")
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "flash":
            from . import flash
            return flash.run(args)
        if args.command == "geocode":
            coords = geocode.parse_coords(args.place)
            if coords:
                print(f"{coords[0]}, {coords[1]}")
                return 0
            place = geocode.lookup(args.place, country_hint=args.country)
            if not place:
                print("nothing found", file=sys.stderr)
                return 1
            print(f"{place.lat}, {place.lon}  {place.country_code}  {place.name}")
            return 0
        if args.command == "art":
            from . import art
            return art.run(args)
        if args.command == "doctor":
            from . import doctor
            return doctor.run(args)
        if args.command == "update":
            from . import update
            return update.run(args)
        if args.command == "site":
            if args.path:
                print(site.SITE_FILE)
            else:
                import json
                print(json.dumps(site.redacted(site.load()), indent=2))
            return 0
    except KeyboardInterrupt:
        print("\ninterrupted", file=sys.stderr)
        return 130
    return 2


if __name__ == "__main__":
    sys.exit(main())
