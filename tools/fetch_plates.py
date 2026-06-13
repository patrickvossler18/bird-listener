#!/usr/bin/env python3
"""Fetch Audubon "Birds of America" plates from Wikimedia Commons by species.

Commons hosts all 435 public-domain Havell plates. Each plate file sits in both
`Category:The Birds of America` and a per-species `Category:{Genus species}
(illustrations)` category, so intersecting those two categories reliably finds
the one plate for a given scientific name — even though the file is *named* by
Audubon's historical common name.

For each requested species this:
  1. searches Commons (namespace 6) for the category intersection,
  2. pulls `imageinfo` with a resized thumbnail at the panel width,
  3. downloads the image into wall-node/images/,
  4. records scientificName -> filename in wall-node/species_map.json.

Results are cached: species already mapped to an existing file are skipped
unless --force is given.

Usage:
  python fetch_plates.py --from-map                 # fill in everything in species_map.json
  python fetch_plates.py "Cardinalis cardinalis" "Cyanocitta cristata"
  python fetch_plates.py --from-map --width 1200 --force
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEFAULT_IMAGES = HERE.parent / "wall-node" / "images"
DEFAULT_MAP = HERE.parent / "wall-node" / "species_map.json"

API = "https://commons.wikimedia.org/w/api.php"
BOA_CATEGORY = "The Birds of America"
# Wikimedia requires a descriptive User-Agent with contact info.
USER_AGENT = "BirdListener/1.0 (https://github.com/patrickvossler18/bird-listener; patrick.vossler18@gmail.com)"


def _api_get(params: dict) -> dict:
    url = f"{API}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def slugify(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
    return s or "bird"


def find_plate_file(scientific: str) -> str | None:
    """Return the File: title of the Audubon plate for a scientific name."""
    srsearch = (f'incategory:"{BOA_CATEGORY}" '
                f'incategory:"{scientific} (illustrations)"')
    data = _api_get({
        "action": "query", "format": "json", "list": "search",
        "srnamespace": 6, "srsearch": srsearch, "srlimit": 5,
    })
    hits = data.get("query", {}).get("search", [])
    return hits[0]["title"] if hits else None


def image_url(file_title: str, width: int) -> tuple[str, str] | None:
    """Return (download_url, original_url) for a File: title at ~width px."""
    data = _api_get({
        "action": "query", "format": "json", "titles": file_title,
        "prop": "imageinfo", "iiprop": "url", "iiurlwidth": width,
    })
    pages = data.get("query", {}).get("pages", {})
    for page in pages.values():
        info = page.get("imageinfo")
        if info:
            ii = info[0]
            return ii.get("thumburl") or ii["url"], ii["url"]
    return None


def download(url: str, dest: Path) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=60) as resp:
        dest.write_bytes(resp.read())


def main() -> int:
    ap = argparse.ArgumentParser(description="Fetch Audubon plates from Wikimedia Commons")
    ap.add_argument("species", nargs="*", help="scientific names to fetch")
    ap.add_argument("--from-map", action="store_true",
                    help="fetch every species key already in species_map.json")
    ap.add_argument("--images-dir", type=Path, default=DEFAULT_IMAGES)
    ap.add_argument("--map", type=Path, default=DEFAULT_MAP)
    ap.add_argument("--width", type=int, default=1200,
                    help="requested thumbnail width in px (default 1200)")
    ap.add_argument("--force", action="store_true",
                    help="re-download even if an image already exists")
    args = ap.parse_args()

    args.images_dir.mkdir(parents=True, exist_ok=True)
    species_map: dict[str, str] = {}
    if args.map.exists():
        species_map = json.loads(args.map.read_text())

    targets = list(args.species)
    if args.from_map:
        targets += [s for s in species_map if s not in targets]
    if not targets:
        ap.error("give one or more scientific names, or use --from-map")

    ok = misses = skipped = 0
    for scientific in targets:
        existing = species_map.get(scientific)
        if existing and (args.images_dir / existing).exists() and not args.force:
            print(f"[skip] {scientific} -> {existing} (cached)")
            skipped += 1
            continue

        file_title = find_plate_file(scientific)
        if not file_title:
            print(f"[miss] {scientific}: no plate found on Commons")
            misses += 1
            continue

        urls = image_url(file_title, args.width)
        if not urls:
            print(f"[miss] {scientific}: '{file_title}' has no imageinfo")
            misses += 1
            continue
        dl_url, orig = urls

        out_name = existing or f"{slugify(scientific)}.jpg"
        out_path = args.images_dir / out_name
        try:
            download(dl_url, out_path)
        except Exception as exc:
            print(f"[miss] {scientific}: download failed ({exc!s})")
            misses += 1
            continue

        species_map[scientific] = out_name
        ok += 1
        print(f"[ok]   {scientific} -> {out_name}  ({file_title})")
        time.sleep(0.5)  # be polite to the API

    args.map.write_text(json.dumps(species_map, indent=2, sort_keys=True) + "\n")
    print(f"\nFetched {ok}, skipped {skipped} cached, {misses} miss(es). "
          f"{len(species_map)} species in {args.map}")
    return 0 if misses == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
