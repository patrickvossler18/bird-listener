#!/usr/bin/env python3
"""Run the whole kachō-e art pipeline in one go.

    species list -> seed from AvianVisitors -> style refs -> Gemini for the gap
    -> BiRefNet cutouts in wall-node/cutouts/

`birdlistener art` drives this for you (and syncs the result to the wall
node). By hand, from the repo root with tools/kachoe/requirements.txt installed:

    python3 tools/kachoe/run_pipeline.py --from-json range.json
    python3 tools/kachoe/run_pipeline.py --from-json range.json --dry-run   # plan + cost only
    python3 tools/kachoe/run_pipeline.py --skip-generate                    # seeds only, no API key

`range.json` is BirdNET-Go's range list for your coordinates (build_species_list.py
fetches it; the CLI does so over SSH). The species list is MERGED into any
existing species.txt rather than replacing it: BirdNET-Go's range model is
seasonal, so re-running in another season adds that season's birds and only
generates what is still missing.

Every step is idempotent; re-runs skip finished work.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[1]
PY = sys.executable

# Rough Gemini 2.5 Flash Image pricing, per generated image, for the plan line.
USD_PER_IMAGE = 0.04


def sh(args: list[str], **kw) -> int:
    print("+", " ".join(str(a) for a in args), flush=True)
    return subprocess.call([str(a) for a in args], **kw)


def slugify(sci: str) -> str:
    import re
    return re.sub(r"[^a-z0-9]+", "-", sci.lower()).strip("-")


def read_species(path: Path) -> list[str]:
    if not path.exists():
        return []
    return [l.strip() for l in path.read_text().splitlines() if "|" in l]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter,
                                 epilog=__doc__)
    ap.add_argument("--from-json", type=Path, help="Saved BirdNET-Go range list (JSON)")
    ap.add_argument("--ssh", metavar="HOST", help="Or fetch the range list via ssh HOST")
    ap.add_argument("--species-file", type=Path, default=HERE / "species.txt")
    ap.add_argument("--gemini-key", help="or GEMINI_API_KEY in the environment / repo .env")
    ap.add_argument("--skip-generate", action="store_true",
                    help="Seed and cut out only; leave the gap for later")
    ap.add_argument("--limit", type=int, default=0, help="Generate at most N species (testing)")
    ap.add_argument("--dry-run", action="store_true", help="Print the plan and cost, change nothing")
    args = ap.parse_args()

    illustrations = HERE / "illustrations"
    cutouts = REPO_ROOT / "wall-node" / "cutouts"

    # 1) Species list: fetch (if asked) and merge into species.txt.
    existing = read_species(args.species_file)
    fetched: list[str] = []
    if args.from_json or args.ssh:
        tmp = HERE / ".species.fetched.txt"
        cmd = [PY, HERE / "build_species_list.py", "--out", tmp]
        cmd += ["--from-json", args.from_json] if args.from_json else ["--ssh", args.ssh]
        if sh(cmd) != 0:
            return 1
        fetched = read_species(tmp)
        tmp.unlink(missing_ok=True)
    merged = sorted(set(existing) | set(fetched))
    if not merged:
        print("error: no species. Pass --from-json range.json or --ssh <window-host>.",
              file=sys.stderr)
        return 2
    new = len(merged) - len(existing)
    if merged != existing and not args.dry_run:
        args.species_file.write_text("\n".join(merged) + "\n")
    print(f"[species] {len(merged)} total ({len(existing)} known, {new} new this run)")

    # 2) What is already drawn, what still needs generating?
    def have(sci: str) -> bool:
        s = slugify(sci)
        return (illustrations / f"{s}.png").exists() and (illustrations / f"{s}-2.png").exists()

    missing_before_seed = [l for l in merged if not have(l.split("|")[0])]
    print(f"[plan] {len(merged) - len(missing_before_seed)} species already illustrated, "
          f"{len(missing_before_seed)} to seed or generate")

    if args.dry_run:
        # Seeding is free; assume the same seed hit-rate as a typical North
        # American list (~75%) for the estimate.
        est_gen = int(len(missing_before_seed) * 0.25) + 1
        print(f"[plan] dry run: expect roughly {est_gen} species x 2 poses via Gemini "
              f"(~${est_gen * 2 * USD_PER_IMAGE:.2f}); the rest seed for free")
        return 0

    # 3) Seed the overlap from AvianVisitors (free) + the style prints.
    if sh([PY, HERE / "fetch_seed_illustrations.py", "--species", args.species_file]) != 0:
        return 1
    if sh([PY, HERE / "fetch_style_refs.py"]) != 0:
        print("!! style refs failed; continuing (prompt-only styling)", file=sys.stderr)

    still_missing = [l for l in merged if not have(l.split("|")[0])]
    print(f"[seed] {len(missing_before_seed) - len(still_missing)} species seeded; "
          f"{len(still_missing)} left to generate")

    # 4) Generate the gap with Gemini.
    if still_missing and not args.skip_generate:
        key = args.gemini_key or os.environ.get("GEMINI_API_KEY", "")
        if not key:
            env_file = REPO_ROOT / ".env"
            if env_file.exists():
                for line in env_file.read_text().splitlines():
                    if line.startswith("GEMINI_API_KEY="):
                        key = line.split("=", 1)[1].strip().strip('"').strip("'")
        if not key:
            print("!! no GEMINI_API_KEY: skipping generation. Seeded birds are cut out below;"
                  " re-run with a key to fill the gap.", file=sys.stderr)
        else:
            n = min(len(still_missing), args.limit) if args.limit else len(still_missing)
            print(f"[generate] {n} species x 2 poses (~${n * 2 * USD_PER_IMAGE:.2f})")
            cmd = [PY, HERE / "pregen.py", "--labels", args.species_file, "--gemini-key", key]
            if args.limit:
                cmd += ["--limit", str(args.limit)]
            if sh(cmd) != 0:
                print("!! generation had errors; cutting out what exists", file=sys.stderr)
    elif still_missing:
        print(f"[generate] skipped ({len(still_missing)} species without art)")

    # 5) Cut the cream ground to transparency.
    if sh([PY, HERE / "cutout.py"]) != 0:
        return 1
    n_cut = len(list(cutouts.glob("*.png")))
    print(f"[done] {n_cut} cutout files in {cutouts}")
    left = [l for l in merged if not have(l.split("|")[0])]
    if left:
        print(f"[done] {len(left)} species still have no art; they show as a name card until "
              f"you re-run with a Gemini key")
    return 0


if __name__ == "__main__":
    sys.exit(main())
