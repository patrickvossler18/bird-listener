#!/usr/bin/env python3
"""Cut the cream ground off the illustrations -> transparent panel cutouts.

Step 4 of the wall-node illustration pipeline (after seeding + pregen). Both the
seeded and generated illustrations sit on a flat cream ground, because the image
model can't cut clean transparency itself but a flat known ground removes
cleanly. This runs each illustration through the BiRefNet matting model (via
rembg), crops to the bird's bounding box with a small even margin, and writes an
RGBA cutout into wall-node/cutouts/ — the directory the renderer reads.

Sources in illustrations/ are left untouched (re-runnable, and a bad cut never
destroys the original). Idempotent: a cutout already newer than its source is
skipped unless --force.

Adapted from AvianVisitors' avian/scripts/cutout.py
(https://github.com/Twarner491/AvianVisitors, CC BY-NC-SA 4.0); the matting +
crop logic is theirs, the separate-output-dir handling is ours.

Requires rembg + onnxruntime. The first run downloads the BiRefNet model
(~1 GB) to ~/.u2net/.

Usage:
    python3 cutout.py                      # every illustration -> cutouts/
    python3 cutout.py calypte-anna         # one slug, both poses
    python3 cutout.py calypte-anna-2 --force
"""
from __future__ import annotations
import argparse
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[1]


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("slugs", nargs="*",
                    help="Slugs to process (e.g. calypte-anna, calypte-anna-2). "
                         "Default: all.")
    ap.add_argument("--src", type=Path, default=HERE / "illustrations",
                    help="Cream-ground illustrations (default: tools/kachoe/illustrations/)")
    ap.add_argument("--out", type=Path, default=REPO_ROOT / "wall-node" / "cutouts",
                    help="Transparent cutout output (default: wall-node/cutouts/)")
    ap.add_argument("--model", default="birefnet-general",
                    help="rembg model name (default: birefnet-general)")
    ap.add_argument("--margin", type=float, default=0.02,
                    help="Even margin around the bird, fraction of its long side "
                         "(default: 0.02)")
    ap.add_argument("--force", action="store_true",
                    help="Re-cut even if the cutout is already up to date")
    args = ap.parse_args()

    try:
        from PIL import Image
        from rembg import new_session, remove
    except ImportError:
        print("error: needs Pillow + rembg (pip install rembg onnxruntime)",
              file=sys.stderr)
        return 2

    if args.slugs:
        paths = [args.src / f"{s}.png" for s in args.slugs]
        missing = [p for p in paths if not p.exists()]
        if missing:
            print("error: not found: " + ", ".join(p.name for p in missing),
                  file=sys.stderr)
            return 2
    else:
        paths = sorted(args.src.glob("*.png"))
    if not paths:
        print(f"error: no illustrations in {args.src}", file=sys.stderr)
        return 1

    args.out.mkdir(parents=True, exist_ok=True)
    session = new_session(args.model)
    done = skipped = failed = 0
    for p in paths:
        dest = args.out / p.name
        if (not args.force and dest.exists()
                and dest.stat().st_mtime >= p.stat().st_mtime):
            skipped += 1
            continue
        try:
            im = Image.open(p).convert("RGB")
            cut = remove(im, session=session)  # RGBA, ground -> transparent
            bbox = cut.getchannel("A").getbbox()
            if not bbox:
                print(f"  [warn] {p.name}: empty mask, skipping", file=sys.stderr)
                failed += 1
                continue
            pad = round(args.margin * max(bbox[2] - bbox[0], bbox[3] - bbox[1]))
            x0, y0 = max(0, bbox[0] - pad), max(0, bbox[1] - pad)
            x1, y1 = min(cut.width, bbox[2] + pad), min(cut.height, bbox[3] + pad)
            cut.crop((x0, y0, x1, y1)).save(dest)
            done += 1
            print(f"  [cut]  {p.name} -> {x1 - x0}x{y1 - y0}")
        except Exception as e:
            print(f"  [fail] {p.name}: {e}", file=sys.stderr)
            failed += 1

    print(f"\ncut {done} · skipped {skipped} (up to date) · failed {failed}")
    print(f"cutouts in {args.out}/")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
