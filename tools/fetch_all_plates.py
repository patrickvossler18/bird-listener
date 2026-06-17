#!/usr/bin/env python3
"""Download ALL Audubon "Birds of America" plates from Wikimedia Commons.

Enumerates `Category:The Birds of America`, resolves each file's
`<Genus species> (illustrations)` category to a scientific name, and downloads a
panel-sized copy into wall-node/images/, keyed by scientific name in
species_map.json. Dedupes to one plate per species (prefers the canonical plate
over cropped/restored variants). Public domain; no API key.

Usage:
  python fetch_all_plates.py                 # download everything
  python fetch_all_plates.py --list-only     # just show what would be fetched
  python fetch_all_plates.py --limit 10      # cap (for a quick test)
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEFAULT_IMAGES = HERE.parent / "wall-node" / "images"
DEFAULT_MAP = HERE.parent / "wall-node" / "species_map.json"
API = "https://commons.wikimedia.org/w/api.php"
BOA = "The Birds of America"
USER_AGENT = "BirdListener/1.0 (https://github.com/patrickvossler18/bird-listener; patrick.vossler18@gmail.com)"
ILLUS = re.compile(r"^Category:(.+) \(illustrations\)$")
VARIANT_HINTS = ("crop", "restor", "detail", "sketch", "sheet music")


def api(params: dict) -> dict:
    url = f"{API}?{urllib.parse.urlencode({**params, 'format': 'json'})}"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode("utf-8"))


def slugify(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_") or "bird"


def all_category_files(category: str) -> list[str]:
    titles, cont = [], {}
    while True:
        d = api({"action": "query", "list": "categorymembers",
                 "cmtitle": f"Category:{category}", "cmtype": "file",
                 "cmlimit": "500", **cont})
        titles += [m["title"] for m in d["query"]["categorymembers"]]
        if "continue" in d:
            cont = d["continue"]
        else:
            return titles


def resolve_meta(titles: list[str], width: int) -> dict:
    """title -> (scientific_name|None, image_url|None) via batched API calls."""
    out = {}
    for i in range(0, len(titles), 50):
        chunk = titles[i:i + 50]
        d = api({"action": "query", "titles": "|".join(chunk),
                 "prop": "categories|imageinfo", "cllimit": "500",
                 "iiprop": "url", "iiurlwidth": str(width)})
        for page in d.get("query", {}).get("pages", {}).values():
            sci = None
            for c in page.get("categories", []):
                m = ILLUS.match(c["title"])
                if m:
                    sci = m.group(1)
                    break
            ii = page.get("imageinfo")
            url = (ii[0].get("thumburl") or ii[0].get("url")) if ii else None
            out[page["title"]] = (sci, url)
        time.sleep(0.3)
    return out


def download(url: str, dest: Path, retries: int = 6) -> None:
    """Download with exponential backoff on HTTP 429 (Wikimedia rate limit)."""
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=120) as r:
                dest.write_bytes(r.read())
            return
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < retries - 1:
                wait = 15 * (2 ** attempt)  # 15, 30, 60, 120, 240s
                print(f"    429 rate-limited; backing off {wait}s…", flush=True)
                time.sleep(wait)
                continue
            raise
        except Exception:
            if attempt < retries - 1:
                time.sleep(8)
                continue
            raise


def main() -> int:
    ap = argparse.ArgumentParser(description="Download all Audubon plates from Commons")
    ap.add_argument("--images-dir", type=Path, default=DEFAULT_IMAGES)
    ap.add_argument("--map", type=Path, default=DEFAULT_MAP)
    ap.add_argument("--width", type=int, default=1200)
    ap.add_argument("--limit", type=int, default=0, help="cap plates (0 = all)")
    ap.add_argument("--list-only", action="store_true")
    ap.add_argument("--force", action="store_true", help="re-download existing files")
    ap.add_argument("--delay", type=float, default=1.5, help="seconds between downloads")
    args = ap.parse_args()

    args.images_dir.mkdir(parents=True, exist_ok=True)
    smap = json.loads(args.map.read_text()) if args.map.exists() else {}

    print(f"Enumerating Category:{BOA} …", flush=True)
    titles = all_category_files(BOA)
    print(f"  {len(titles)} files in category", flush=True)
    if args.limit:
        titles = titles[:args.limit]

    print("Resolving species + image URLs …", flush=True)
    meta = resolve_meta(titles, args.width)

    # Dedupe to one plate per species, preferring canonical over variant files.
    chosen: dict[str, tuple[str, str, bool]] = {}
    for title, (sci, url) in meta.items():
        if not sci or not url:
            continue
        is_variant = any(h in title.lower() for h in VARIANT_HINTS)
        if sci not in chosen or (chosen[sci][2] and not is_variant):
            chosen[sci] = (title, url, is_variant)
    print(f"  {len(chosen)} unique species resolved "
          f"({len(meta) - len(chosen)} files skipped: no species / dupes)", flush=True)

    if args.list_only:
        for sci in sorted(chosen):
            print(f"  {sci}  <-  {chosen[sci][0]}")
        return 0

    def save_map():
        args.map.write_text(json.dumps(smap, indent=2, sort_keys=True) + "\n")

    ok = fail = skip = 0
    items = sorted(chosen.items())
    for n, (sci, (title, url, _)) in enumerate(items, 1):
        fn = smap.get(sci) or f"{slugify(sci)}.jpg"
        dest = args.images_dir / fn
        if dest.exists() and dest.stat().st_size > 1024 and not args.force:
            smap[sci] = fn
            skip += 1
            continue
        try:
            download(url, dest)
            smap[sci] = fn
            ok += 1
            print(f"[{n}/{len(items)}] {sci} -> {fn}", flush=True)
        except Exception as exc:
            fail += 1
            print(f"[{n}/{len(items)}] {sci} FAILED: {exc}", flush=True)
        if ok % 25 == 0:
            save_map()  # persist progress periodically
        time.sleep(args.delay)

    save_map()
    print(f"\nDownloaded {ok}, skipped {skip} existing, failed {fail}. "
          f"{len(smap)} species in {args.map}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
