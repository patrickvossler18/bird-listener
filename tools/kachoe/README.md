# kachō-e illustration pipeline

Offline pipeline that produces the transparent kachō-e bird cutouts the wall
node composes into its collage. Runs on a dev machine (a Mac), **not** the Pi —
the Pi only reads the finished `wall-node/cutouts/`.

Each species gets two poses on a flat cream ground (`<slug>.png` perched,
`<slug>-2.png` flight); the cream is then matted to transparency. We **seed**
most species from AvianVisitors' bundled art and only **generate** the gap, so a
full build is cheap.

## Prerequisites

- The project venv with `rembg`, `onnxruntime`, `Pillow` (the cutout step).
- `GEMINI_API_KEY` in the repo `.env` (the generate step). Billing enabled.
- Network access to `birdpi.local:8080` (the species-list step) or a saved dump.

## Steps

```bash
# 1. Target species: BirdNET-Go's range-filtered list at our coordinates.
python3 tools/kachoe/build_species_list.py            # -> species.txt (235 spp)

# 2. Seed: download the overlap from AvianVisitors (cream ground, both poses).
python3 tools/kachoe/fetch_seed_illustrations.py      # -> illustrations/ (~177 spp)

# 3. Style refs: the Edo prints pregen attaches as IMAGE 3 (public domain).
python3 tools/kachoe/fetch_style_refs.py              # -> refs/styles/ (10 prints)

# 4. Generate the gap with Gemini 2.5 Flash Image (~58 spp × 2 ≈ 116 images).
python3 tools/kachoe/pregen.py                        # -> illustrations/

# 5. Cut the cream ground to transparency and crop to the bird.
python3 tools/kachoe/cutout.py                        # -> wall-node/cutouts/
```

Then sync `wall-node/cutouts/` to the wall node (birdwall).

All steps are idempotent — re-running skips work already done. Regenerate one
bird after a prompt/notes tweak:

```bash
python3 tools/kachoe/pregen.py --species "Calypte anna|Anna's Hummingbird" --force
python3 tools/kachoe/cutout.py calypte-anna calypte-anna-2 --force
```

## Files

| File | Role |
|------|------|
| `build_species_list.py` | Pull the range-filtered species list from BirdNET-Go → `species.txt` |
| `fetch_seed_illustrations.py` | Download AvianVisitors' overlapping cream-ground art |
| `fetch_style_refs.py` | Fetch the 10 Koson/Yoshida style prints from Wikimedia Commons |
| `pregen.py` | Generate the remaining species via Gemini (cream ground) |
| `cutout.py` | BiRefNet ground removal → transparent `wall-node/cutouts/` |
| `prompt.template.md` | The kachō-e prompt (edit to restyle) |
| `species-notes.json` | Per-species anti-drift addenda for hard birds |
| `species.txt` | Generated target list (`Sci\|Com` per line) |
| `illustrations/` | Cream-ground art (seeded + generated); cutout source |
| `refs/` | Cached Wikipedia anatomy refs + `refs/styles/` Edo prints |

`illustrations/`, `refs/`, and `species.txt` are build intermediates — see
`.gitignore`. The committed artifact is `wall-node/cutouts/`.

## Tuning quality

The image model drifts on look-alike species. In order of effort:

1. Add a one-line entry to `species-notes.json` naming the diagnostic field
   marks and the look-alikes to avoid, then `--force` regenerate that species.
2. For blue corvids / swallows, an anti-reference is already wired
   (`pregen.py` `ANTI_REF_TRIGGERS`); drop the photo at
   `refs/_anti_<key>.jpg`.
3. Hand-pick a better anatomy reference: drop `refs/<slug>.jpg` before running.
4. Hand-replace a wrong style print in `refs/styles/` (keep the filename).

## Attribution

The seeded illustrations and the prompt/notes/pipeline approach are from
**AvianVisitors** by Teagan Warner — <https://github.com/Twarner491/AvianVisitors>,
licensed **CC BY-NC-SA 4.0**. Our adaptations (`pregen.py`, `cutout.py`,
seeded art) inherit that license: non-commercial, share-alike, with attribution.
The Koson/Yoshida style prints are public domain (artists d. 1945 / 1950).
