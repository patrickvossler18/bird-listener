#!/usr/bin/env python3
"""Seed the illustration set from AvianVisitors' bundled kachō-e art.

AvianVisitors (https://github.com/Twarner491/AvianVisitors, CC BY-NC-SA 4.0)
ships 249 species × 2 poses as cream-ground PNGs. Most of our BirdNET-Go range
list overlaps theirs, so rather than pay to regenerate those, we download the
overlap here and only generate the gaps with pregen.py. Everything then goes
through the same cutout.py, so seeded and generated art get identical treatment.

Reads species.txt (Sci|Com), slugifies each name the same way they do, and
pulls <slug>.png (perched) and <slug>-2.png (flight) from their `eink` branch
into illustrations/. A species they don't have is simply skipped — pregen.py
fills it.

Usage:
    python3 fetch_seed_illustrations.py                 # both poses, skip existing
    python3 fetch_seed_illustrations.py --force         # re-download
"""
from __future__ import annotations

import argparse
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent

RAW_BASE = ("https://raw.githubusercontent.com/Twarner491/AvianVisitors/"
            "eink/avian/assets/illustrations")
POSE_SUFFIX = {1: "", 2: "-2"}  # their naming: perched=<slug>.png, flight=<slug>-2.png


def slugify(sci: str) -> str:
    """Match AvianVisitors apt.js/pregen.py slugify() exactly."""
    return re.sub(r"[^a-z0-9]+", "-", sci.lower()).strip("-")


def read_species(path: Path) -> list[str]:
    out = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        sci = re.split(r"[|_,]", line, 1)[0].strip()
        if sci:
            out.append(sci)
    return out


def download(url: str, dest: Path, timeout: float) -> bool:
    """Return True if downloaded, False on 404 (species/pose they don't have)."""
    req = urllib.request.Request(url, headers={"User-Agent": "kachoe-pipeline/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = r.read()
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return False
        raise
    dest.write_bytes(data)
    return True


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--species", type=Path, default=HERE / "species.txt")
    ap.add_argument("--out", type=Path, default=HERE / "illustrations")
    ap.add_argument("--poses", nargs="+", type=int, default=[1, 2], choices=[1, 2])
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--timeout", type=float, default=30.0)
    args = ap.parse_args()

    species = read_species(args.species)
    if not species:
        print(f"error: no species in {args.species}", file=sys.stderr)
        return 2
    args.out.mkdir(parents=True, exist_ok=True)

    got = skipped = missing = 0
    seeded_species = set()
    for sci in species:
        slug = slugify(sci)
        for pose in args.poses:
            name = f"{slug}{POSE_SUFFIX[pose]}.png"
            dest = args.out / name
            if dest.exists() and not args.force:
                skipped += 1
                seeded_species.add(slug)
                continue
            if download(f"{RAW_BASE}/{name}", dest, args.timeout):
                got += 1
                seeded_species.add(slug)
                print(f"  [seed] {name}")
            else:
                missing += 1

    to_generate = sorted(set(slugify(s) for s in species) - seeded_species)
    print(f"\nseeded {got} · skipped {skipped} (already present) · "
          f"not in their set {missing}")
    print(f"species covered by seed: {len(seeded_species)}/{len(species)}; "
          f"{len(to_generate)} still to generate via pregen.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
