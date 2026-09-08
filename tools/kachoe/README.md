# kachō-e illustration pipeline

Offline pipeline that produces the transparent kachō-e bird cutouts the wall
node composes into its collage. Runs on your computer, **not** the Pi (the
matting model is too heavy for it); the Pi only reads the finished
`wall-node/cutouts/`.

Each species gets two poses on a flat cream ground (`<slug>.png` perched,
`<slug>-2.png` flight); the cream is then matted to transparency. We **seed**
most species from AvianVisitors' bundled art and only **generate** the gap, so a
full build is cheap.

## Running it

`birdlistener art` (see `cli/`) runs everything below and syncs the result to
the wall node. Add `--dry-run` to see how many species need generating and
the rough cost first, `--docker` to run inside the container built from the
Dockerfile here instead of a local venv, and `--bundle sf-bay-area` to fetch a
prebuilt regional bundle instead of generating.

By hand, from the repo root:

```bash
python3 -m venv tools/kachoe/.venv && tools/kachoe/.venv/bin/pip install -r tools/kachoe/requirements.txt
tools/kachoe/.venv/bin/python tools/kachoe/run_pipeline.py --ssh birdpi              # all steps
tools/kachoe/.venv/bin/python tools/kachoe/run_pipeline.py --ssh birdpi --dry-run    # plan only
```

`run_pipeline.py` does, in order (each step idempotent, each also runnable alone):

```bash
# 1. Target species: BirdNET-Go's range-filtered list at the window node's
#    coordinates, fetched over SSH (the UI is loopback-only). MERGED into
#    species.txt: the range model is for the current week, so re-running in
#    another season adds birds and only draws what is still missing.
python3 tools/kachoe/build_species_list.py --ssh birdpi

# 2. Seed: download the overlap from AvianVisitors (cream ground, both poses).
python3 tools/kachoe/fetch_seed_illustrations.py      # -> illustrations/

# 3. Style refs: the Edo prints pregen attaches as IMAGE 3 (public domain).
python3 tools/kachoe/fetch_style_refs.py              # -> refs/styles/

# 4. Generate the gap with Gemini 2.5 Flash Image (two poses per species,
#    a few cents each). GEMINI_API_KEY from the repo .env, the environment,
#    or --gemini-key.
python3 tools/kachoe/pregen.py                        # -> illustrations/

# 5. Cut the cream ground to transparency and crop to the bird (BiRefNet via
#    rembg; first run downloads the ~1 GB model to ~/.u2net/).
python3 tools/kachoe/cutout.py                        # -> wall-node/cutouts/
```

Then sync `wall-node/cutouts/` to the wall node (`birdlistener art` does;
by hand `rsync -az wall-node/cutouts/ birdwall:bird-listener/wall-node/cutouts/`).

Regenerate one bird after a prompt/notes tweak:

```bash
python3 tools/kachoe/pregen.py --species "Calypte anna|Anna's Hummingbird" --force
python3 tools/kachoe/cutout.py calypte-anna calypte-anna-2 --force
```

## Files

| File | Role |
|------|------|
| `run_pipeline.py` | All steps in order, with a plan/cost dry run |
| `build_species_list.py` | Pull the range-filtered species list from BirdNET-Go (over SSH) and merge into `species.txt` |
| `fetch_seed_illustrations.py` | Download AvianVisitors' overlapping cream-ground art |
| `fetch_style_refs.py` | Fetch the 10 Koson/Yoshida style prints from Wikimedia Commons |
| `pregen.py` | Generate the remaining species via Gemini (cream ground) |
| `cutout.py` | BiRefNet ground removal → transparent `wall-node/cutouts/` |
| `prompt.template.md` | The kachō-e prompt (edit to restyle) |
| `species-notes.json` | Per-species anti-drift addenda for hard birds |
| `species.txt` | Target list (`Sci\|Com` per line), grows with each fetch |
| `requirements.txt`, `Dockerfile` | The pipeline's Python deps; the container `birdlistener art --docker` uses |
| `LICENSE` | CC BY-NC-SA 4.0, inherited from AvianVisitors |
| `illustrations/` | Cream-ground art (seeded + generated); cutout source |
| `refs/` | Cached Wikipedia anatomy refs + `refs/styles/` Edo prints |

`illustrations/` and `refs/` are build intermediates and `wall-node/cutouts/`
the deployable output; none are in git (see `.gitignore`). Back up
`illustrations/`: the generated half cost API calls to make.

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
licensed **CC BY-NC-SA 4.0** (inherited from BirdNET-Pi). Everything in this
directory and the art it produces inherits that license: non-commercial,
share-alike, with attribution. See `LICENSE` here.
The Koson/Yoshida style prints are public domain (artists d. 1945 / 1950).
