#!/usr/bin/env python3
"""Prepare Audubon plates for the e-ink panel.

Takes a directory of source images (high-res Audubon *Birds of America* plates,
public domain) plus a CSV mapping each source file to a species, and produces:

  - cropped/resized JPEGs in wall-node/images/ (fitted to the panel aspect)
  - an updated wall-node/species_map.json (scientificName -> output filename)

The actual color dithering to the Spectra-6 palette happens at display time in
the wall node (renderer.to_panel), so here we only crop/resize to keep things
flexible.

CSV format (header required):

    source,scientific_name,common_name,output
    plate_102.jpg,Cardinalis cardinalis,Northern Cardinal,northern_cardinal.jpg
    plate_021.jpg,Cyanocitta cristata,Blue Jay,blue_jay.jpg

`output` is optional; if blank, a filename is derived from the common name.

Usage:
    python build_images.py --src ./source_plates --csv ./plates.csv
    python build_images.py --src ./source_plates --csv ./plates.csv \
        --images-dir ../wall-node/images --map ../wall-node/species_map.json \
        --width 800 --height 480
"""
from __future__ import annotations

import argparse
import csv
import json
import re
from pathlib import Path

from PIL import Image

HERE = Path(__file__).resolve().parent
DEFAULT_IMAGES = HERE.parent / "wall-node" / "images"
DEFAULT_MAP = HERE.parent / "wall-node" / "species_map.json"

# Art fills the top portion of the panel (the caption bar takes ~1/10 at the
# bottom). Crop sources to this aspect so nothing important is lost at runtime.
ART_FRACTION = 0.9


def slugify(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
    return s or "bird"


def fit_cover(img: Image.Image, w: int, h: int) -> Image.Image:
    img = img.convert("RGB")
    scale = max(w / img.width, h / img.height)
    new = img.resize((round(img.width * scale), round(img.height * scale)))
    left = (new.width - w) // 2
    top = (new.height - h) // 2
    return new.crop((left, top, left + w, top + h))


def main() -> int:
    ap = argparse.ArgumentParser(description="Build Audubon image library")
    ap.add_argument("--src", required=True, type=Path,
                    help="directory of source plate images")
    ap.add_argument("--csv", required=True, type=Path,
                    help="CSV mapping source files to species")
    ap.add_argument("--images-dir", type=Path, default=DEFAULT_IMAGES)
    ap.add_argument("--map", type=Path, default=DEFAULT_MAP)
    ap.add_argument("--width", type=int, default=800)
    ap.add_argument("--height", type=int, default=480)
    args = ap.parse_args()

    art_h = round(args.height * ART_FRACTION)
    args.images_dir.mkdir(parents=True, exist_ok=True)

    species_map: dict[str, str] = {}
    if args.map.exists():
        species_map = json.loads(args.map.read_text())

    processed = 0
    with args.csv.open(newline="") as f:
        for row in csv.DictReader(f):
            src_name = (row.get("source") or "").strip()
            scientific = (row.get("scientific_name") or "").strip()
            common = (row.get("common_name") or "").strip()
            if not src_name or not scientific:
                print(f"[skip] row missing source/scientific_name: {row}")
                continue
            src_path = args.src / src_name
            if not src_path.exists():
                print(f"[skip] source not found: {src_path}")
                continue

            out_name = (row.get("output") or "").strip()
            if not out_name:
                out_name = f"{slugify(common or scientific)}.jpg"

            img = fit_cover(Image.open(src_path), args.width, art_h)
            out_path = args.images_dir / out_name
            img.save(out_path, "JPEG", quality=90)
            species_map[scientific] = out_name
            processed += 1
            print(f"[ok] {scientific} -> {out_name}")

    args.map.write_text(json.dumps(species_map, indent=2, sort_keys=True) + "\n")
    print(f"\nProcessed {processed} plate(s). "
          f"{len(species_map)} species in {args.map}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
