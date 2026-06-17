#!/usr/bin/env python3
"""Compute a subject bounding box for each plate, for subject-aware cropping.

Uses rembg (U2-Net / ISNet salient-object segmentation) to find the bird(s) +
branch on the cream paper background, takes the bounding box of the foreground
mask, pads it slightly, and writes wall-node/crops.json:

    {"model": "...", "boxes": {"<filename>": [x, y, w, h], ...}}

This is an OFFLINE batch (run on a Mac/dev box); the Pi only reads crops.json
and applies the box (renderer._smart_fill / collage). Plates whose mask is empty
or degenerate (covers almost none or almost all of the sheet) are omitted, so
the renderer falls back to its plain cover-crop for those.

Usage:
  pip install rembg            # one-time (pulls onnxruntime + numpy)
  python compute_crops.py                 # all images, skip ones already cached
  python compute_crops.py --force         # recompute everything
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEFAULT_IMAGES = HERE.parent / "wall-node" / "images"
DEFAULT_OUT = HERE.parent / "wall-node" / "crops.json"
MODEL = "isnet-general-use"


def main() -> int:
    ap = argparse.ArgumentParser(description="Compute subject crop boxes via rembg")
    ap.add_argument("--images-dir", type=Path, default=DEFAULT_IMAGES)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--pad", type=float, default=0.04, help="fractional padding around the subject")
    ap.add_argument("--thresh", type=int, default=12, help="mask threshold (0-255)")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    try:
        import numpy as np
        import rembg
        from PIL import Image
    except ImportError as exc:
        print(f"Missing dependency ({exc}); run: pip install rembg", file=sys.stderr)
        return 2

    cache = {}
    if args.out.exists() and not args.force:
        try:
            cache = json.loads(args.out.read_text()).get("boxes", {})
        except Exception:
            cache = {}

    session = rembg.new_session(MODEL)
    images = sorted(args.images_dir.glob("*.jpg"))
    print(f"{len(images)} plates; {len(cache)} already cached", flush=True)

    done = skipped = omitted = 0
    for n, path in enumerate(images, 1):
        name = path.name
        if name in cache and not args.force:
            skipped += 1
            continue
        try:
            img = Image.open(path).convert("RGB")
            mask = rembg.remove(img, session=session, only_mask=True)
            m = np.array(mask.convert("L")) > args.thresh
            frac = m.mean()
            if not m.any() or frac < 0.01 or frac > 0.97:
                omitted += 1                      # degenerate -> renderer falls back
                print(f"[{n}/{len(images)}] {name}: mask {frac:.0%} -> omit (fallback)", flush=True)
            else:
                ys, xs = np.where(m)
                x0, x1 = int(xs.min()), int(xs.max())
                y0, y1 = int(ys.min()), int(ys.max())
                px, py = int((x1 - x0) * args.pad), int((y1 - y0) * args.pad)
                x0, y0 = max(0, x0 - px), max(0, y0 - py)
                x1, y1 = min(img.width, x1 + px), min(img.height, y1 + py)
                cache[name] = [x0, y0, x1 - x0, y1 - y0]
                done += 1
                print(f"[{n}/{len(images)}] {name}: box {cache[name]} ({frac:.0%})", flush=True)
        except Exception as exc:
            omitted += 1
            print(f"[{n}/{len(images)}] {name}: FAILED ({exc}) -> omit", flush=True)
        if done and done % 25 == 0:
            args.out.write_text(json.dumps({"model": MODEL, "boxes": cache}, indent=0) + "\n")

    args.out.write_text(json.dumps({"model": MODEL, "boxes": cache}, indent=0) + "\n")
    print(f"\nComputed {done}, skipped {skipped} cached, omitted {omitted}. "
          f"{len(cache)} boxes in {args.out}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
