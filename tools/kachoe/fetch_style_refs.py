#!/usr/bin/env python3
"""Fetch the Edo-period kachō-e style-reference prints into refs/styles/.

pregen.py attaches one of ten Ohara Koson / Hiroshi Yoshida woodblock prints to
each request as IMAGE 3 — the model borrows the painting technique (flat washes,
confident outlines, tonal ground), not the subject. AvianVisitors deliberately
doesn't bundle these (they're someone else's art), so we fetch them. Koson
(d. 1945) and Yoshida (d. 1950) prints from this era are public domain.

Rather than hardcode brittle file URLs, this searches the Wikimedia Commons API
for each print and downloads the best image match to the filename pregen.py
expects. A missing/poor match degrades gracefully: pregen.py just skips IMAGE 3
for affected genera, falling back to the (already strong) text prompt. Review
refs/styles/ afterward and hand-replace any wrong match — the filenames are what
matter, not the source.

Usage:
    python3 fetch_style_refs.py            # fetch any missing prints
    python3 fetch_style_refs.py --force    # re-fetch all
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
COMMONS_API = "https://commons.wikimedia.org/w/api.php"
USER_AGENT = "kachoe-pipeline/1.0 (bird-listener)"

# filename pregen.py expects -> Commons search query for that print.
PRINTS = {
    "01-sparrows-on-bamboo-Koson.jpg":      "Koson sparrows bamboo",
    "02-cawing-crow-Koson.jpg":             "Cawing crow Ohara Koson",
    "03-jays-on-berry-tree-Koson.jpg":      "Ohara Koson jay",
    "04-kingfisher-Koson.jpg":              "Koson kingfisher",
    "05-owl-on-ginkgo-Koson.jpg":           "Koson owl ginkgo",
    "06-goose-flying-in-moonlight-Koson.jpg": "Koson goose moon",
    "07-swallows-in-flight-Koson.jpg":      "Koson swallows flight",
    "08-crane-in-small-water-Koson.jpg":    "Koson crane water",
    "09-cockatoo-Yoshida.jpg":              "Hiroshi Yoshida cockatoo",
    "10-mandarin-ducks-Yoshida.jpg":        "Koson mandarin ducks",
}


def _api(params: dict) -> dict:
    """Commons API call with bounded retry/backoff on 429 (Commons throttles
    rapid anonymous requests)."""
    url = COMMONS_API + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    backoff = 5.0
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < 3:
                time.sleep(backoff)
                backoff *= 2
                continue
            raise
    return {}


def search_image_url(query: str) -> str | None:
    """Return the direct image URL of the best File:-namespace match, or None."""
    data = _api({
        "action": "query", "format": "json",
        "generator": "search",
        "gsrsearch": query,
        "gsrnamespace": "6",          # File: namespace
        "gsrlimit": "5",
        "prop": "imageinfo",
        "iiprop": "url|mime|size",
        "iiurlwidth": "1024",         # downscaled copy is plenty for a style ref
    })
    pages = (data.get("query") or {}).get("pages") or {}
    # Prefer the best search rank (lowest index), among raster images.
    best = sorted(pages.values(), key=lambda p: p.get("index", 1e9))
    for p in best:
        info = (p.get("imageinfo") or [{}])[0]
        mime = info.get("mime", "")
        if mime in ("image/jpeg", "image/png"):
            return info.get("thumburl") or info.get("url")
    return None


def download(url: str, dest: Path, timeout: float = 60) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        dest.write_bytes(r.read())


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, default=HERE / "refs" / "styles")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    got = skipped = failed = 0
    for fname, query in PRINTS.items():
        dest = args.out / fname
        if dest.exists() and not args.force:
            skipped += 1
            continue
        try:
            url = search_image_url(query)
            if not url:
                print(f"  [miss] {fname}: no match for '{query}'", file=sys.stderr)
                failed += 1
                continue
            download(url, dest)
            got += 1
            print(f"  [got]  {fname}  <- {url.rsplit('/', 1)[-1][:60]}")
        except Exception as e:
            print(f"  [fail] {fname}: {e}", file=sys.stderr)
            failed += 1
        time.sleep(2.0)  # be polite to the Commons API (avoids 429)

    print(f"\nfetched {got} · skipped {skipped} (present) · failed {failed}")
    print(f"style refs in {args.out}/ — review and hand-replace any wrong match; "
          f"pregen.py skips a missing one gracefully.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
