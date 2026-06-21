#!/usr/bin/env python3
"""Generate kachō-e bird illustrations for the species we couldn't seed.

Step 2 of the wall-node illustration pipeline:
    1. build_species_list.py     range list from BirdNET-Go -> species.txt
    2. fetch_seed_illustrations  download AvianVisitors' overlap (cream ground)
    3. pregen.py (this)          generate the remaining species via Gemini
    4. cutout.py                 BiRefNet ground removal -> wall-node/cutouts/

Adapted from AvianVisitors' avian/scripts/pregen.py
(https://github.com/Twarner491/AvianVisitors, CC BY-NC-SA 4.0). The generation
logic — Wikipedia anatomy references, contrastive anti-references for look-alike
drift, per-genus Edo style-print mapping, retry/backoff — is theirs; we changed
only the defaults (paths under tools/kachoe/, GEMINI_API_KEY auto-loaded from the
repo .env) and dropped the eBird filter (build_species_list.py already scopes the
list to our coordinates via BirdNET-Go's range model).

Each species renders two poses on a flat CREAM ground (the model can't cut clean
transparency itself; cutout.py removes the known ground in step 4):
    <slug>.png    perched
    <slug>-2.png  in flight
Skips files that already exist (seeded or previously generated) unless --force.

Usage:
    python3 pregen.py                       # generate everything in species.txt
                                            #   not already in illustrations/
    python3 pregen.py --species "Calypte anna|Anna's Hummingbird" --force
    python3 pregen.py --limit 2             # smoke-test a couple

GEMINI_API_KEY is read from the repo .env (or the environment, or --gemini-key).
"""
from __future__ import annotations
import argparse
import base64
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[1]

# Gemini's image-out model. The endpoint changes occasionally; if you
# get a 404 here, check Google's model catalog and bump this.
GEMINI_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    "gemini-2.5-flash-image:generateContent"
)
POSES = {1: "perched", 2: "in flight with wings spread"}

# Genera where Gemini's prior collapses to Blue Jay markings unless we
# attach a Blue Jay anti-reference.
JAY_GENERA = {
    "Cyanocitta", "Aphelocoma", "Cyanolyca", "Calocitta", "Cyanopica",
    "Garrulus", "Cyanocorax", "Gymnorhinus",
}

# Genera where Gemini's prior collapses to Barn Swallow (rufous throat,
# deeply forked tail) unless we attach a Barn Swallow anti-reference.
# Hirundo rustica is itself the Barn Swallow so it's excluded.
SWALLOW_GENERA = {
    "Tachycineta", "Riparia", "Progne", "Petrochelidon", "Stelgidopteryx",
}

# ---- Style references ----
# Edo-period kachō-e woodblock prints by Ohara Koson and Hiroshi Yoshida,
# kept in refs/styles/. Mapped by genus + pose. The bird in each print is
# irrelevant — only the painting technique is borrowed. The prints are not
# bundled (they are someone else's art, though old enough to be public domain);
# fetch_style_refs.py pulls them, and a missing one simply isn't attached.
STYLE_REFS = {
    "small_songbird_perched": "01-sparrows-on-bamboo-Koson.jpg",
    "dark_bird_perched":      "02-cawing-crow-Koson.jpg",
    "vivid_perched":          "03-jays-on-berry-tree-Koson.jpg",
    "vibrant_perched":        "04-kingfisher-Koson.jpg",
    "owl":                    "05-owl-on-ginkgo-Koson.jpg",
    "large_flight":           "06-goose-flying-in-moonlight-Koson.jpg",
    "small_flight":           "07-swallows-in-flight-Koson.jpg",
    "wader":                  "08-crane-in-small-water-Koson.jpg",
    "pale_perched":           "09-cockatoo-Yoshida.jpg",
    "waterfowl_perched":      "10-mandarin-ducks-Yoshida.jpg",
}

# Genus → perched style category. First match wins; fallback is the Koson
# sparrows-on-bamboo print for any uncategorized genus.
GENUS_STYLE_PERCHED = {
    # Owls
    "Tyto":"owl","Bubo":"owl","Asio":"owl","Megascops":"owl","Athene":"owl",
    "Strix":"owl","Glaucidium":"owl","Aegolius":"owl",
    # Hummingbirds + jays + colorful crested (vibrant color anchor)
    "Calypte":"vibrant_perched","Archilochus":"vibrant_perched",
    "Selasphorus":"vibrant_perched","Calothorax":"vibrant_perched",
    "Cyanocitta":"vibrant_perched","Aphelocoma":"vibrant_perched",
    "Pica":"vibrant_perched","Nucifraga":"vibrant_perched",
    "Perisoreus":"vibrant_perched",
    # Waxwings + orioles + tanagers (vivid perching)
    "Bombycilla":"vivid_perched","Icterus":"vivid_perched",
    "Piranga":"vivid_perched","Pheucticus":"vivid_perched",
    "Passerina":"vivid_perched","Cardellina":"vivid_perched",
    "Setophaga":"vivid_perched","Icteria":"vivid_perched",
    # Corvids + vultures (dark perching)
    "Corvus":"dark_bird_perched","Coragyps":"dark_bird_perched",
    "Cathartes":"dark_bird_perched","Gymnogyps":"dark_bird_perched",
    # Waterfowl perched (mandarin-ducks anchor)
    "Anas":"waterfowl_perched","Aix":"waterfowl_perched","Mareca":"waterfowl_perched",
    "Spatula":"waterfowl_perched","Branta":"waterfowl_perched","Anser":"waterfowl_perched",
    "Cygnus":"waterfowl_perched","Aythya":"waterfowl_perched",
    "Bucephala":"waterfowl_perched","Lophodytes":"waterfowl_perched",
    "Mergus":"waterfowl_perched","Oxyura":"waterfowl_perched",
    "Podiceps":"waterfowl_perched","Podilymbus":"waterfowl_perched",
    "Aechmophorus":"waterfowl_perched","Gavia":"waterfowl_perched",
    "Pelecanus":"waterfowl_perched","Phalacrocorax":"waterfowl_perched",
    "Urile":"waterfowl_perched",
    # Waders + herons (crane-in-reeds anchor)
    "Ardea":"wader","Egretta":"wader","Bubulcus":"wader","Butorides":"wader",
    "Nycticorax":"wader","Plegadis":"wader","Limosa":"wader","Numenius":"wader",
    "Himantopus":"wader","Recurvirostra":"wader","Charadrius":"wader",
    "Actitis":"wader","Calidris":"wader","Tringa":"wader",
    # Pale-bodied (gulls, terns, skimmer — cockatoo anchor)
    "Larus":"pale_perched","Leucophaeus":"pale_perched","Sterna":"pale_perched",
    "Thalasseus":"pale_perched","Hydroprogne":"pale_perched","Rynchops":"pale_perched",
}

# Genera that should use large_flight (instead of small_flight) for pose 2.
LARGE_FLIGHT_GENERA = {
    "Tyto","Bubo","Asio","Megascops","Athene","Strix","Glaucidium","Aegolius",
    "Anas","Aix","Mareca","Spatula","Branta","Anser","Cygnus","Aythya",
    "Bucephala","Lophodytes","Mergus","Oxyura","Pelecanus","Phalacrocorax",
    "Urile","Ardea","Egretta","Bubulcus","Butorides","Nycticorax","Plegadis",
    "Limosa","Numenius","Himantopus","Recurvirostra",
    "Buteo","Accipiter","Aquila","Circus","Falco","Cathartes","Coragyps",
    "Haliaeetus","Pandion","Elanus","Gymnogyps","Corvus",
}


def select_style_ref(sci: str, pose: int) -> str:
    """Pick the style reference filename for a (sci, pose) pair."""
    genus = sci.split()[0]
    if sci == "Aeronautes saxatalis":
        return STYLE_REFS["vibrant_perched"]  # vertical aerial-feeder posture, no swallow bias
    if pose == 2:
        return STYLE_REFS["large_flight" if genus in LARGE_FLIGHT_GENERA else "small_flight"]
    return STYLE_REFS[GENUS_STYLE_PERCHED.get(genus, "small_songbird_perched")]


ANTI_REFS = {
    "bluejay": {
        "common_name": "Blue Jay",
        "sci_name": "Cyanocitta cristata",
        "do_not_copy": (
            "its facial mask, its white wingbars, its black necklace, "
            "its crest pattern, or its white-tipped tail"
        ),
    },
    "barnswallow": {
        "common_name": "Barn Swallow",
        "sci_name": "Hirundo rustica",
        "do_not_copy": (
            "its deep rufous throat, its long deeply forked outer tail "
            "streamers, or its blue-black back"
        ),
    },
}

# Which anti-ref to attach for which genus, and the species to exclude
# (the lookalike itself). First match wins.
ANTI_REF_TRIGGERS = (
    (JAY_GENERA, "bluejay", "Cyanocitta cristata"),
    (SWALLOW_GENERA, "barnswallow", "Hirundo rustica"),
)

USER_AGENT = "kachoe-pipeline/1.0 (bird-listener)"


def load_dotenv(path: Path) -> None:
    """Minimal .env loader: set KEY=VALUE pairs that aren't already in env."""
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        key, val = key.strip(), val.strip().strip('"').strip("'")
        os.environ.setdefault(key, val)


def slugify(sci: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", sci.lower()).strip("-")


def parse_species_line(line: str) -> tuple[str, str] | None:
    """Accept 'Sci|Com', 'Sci_Com', or 'Sci,Com'. Skip blanks + #."""
    line = line.strip()
    if not line or line.startswith("#"):
        return None
    for sep in ("|", "_", ","):
        if sep in line:
            sci, com = line.split(sep, 1)
            sci, com = sci.strip(), com.strip()
            if sci and com:
                return (sci, com)
    return None


def parse_species_list(lines: list[str]) -> tuple[list[tuple[str, str]], int]:
    out, skipped = [], 0
    for line in lines:
        parsed = parse_species_line(line)
        if parsed:
            out.append(parsed)
        elif line.strip() and not line.lstrip().startswith("#"):
            skipped += 1
    return out, skipped


def load_prompt(path: Path) -> str:
    """Everything after the `## Prompt` heading, up to the next `##`."""
    text = path.read_text()
    m = re.search(r"##\s*Prompt\s*\n(.+?)(?=\n##\s|\Z)", text, flags=re.DOTALL)
    return (m.group(1) if m else text).strip()


# ---- Reference photo handling ----

REF_EXTS = (".jpg", ".png")


def fetch_wikipedia_thumb(sci: str, com: str) -> tuple[bytes, str] | None:
    """Fetch the Wikipedia article's lead/infobox image bytes. Returns
    (bytes, ext) sniffed from magic bytes, or None if no usable image."""
    titles = [sci.replace(" ", "_"), com.replace(" ", "_"), com.split()[0]]
    for title in titles:
        url = ("https://en.wikipedia.org/api/rest_v1/page/summary/"
               + urllib.parse.quote(title))
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=20) as r:
                meta = json.loads(r.read())
        except (urllib.error.HTTPError, urllib.error.URLError):
            continue
        for k in ("originalimage", "thumbnail"):
            src = (meta.get(k) or {}).get("source")
            if not src or not src.lower().endswith((".jpg", ".jpeg", ".png")):
                continue
            try:
                req2 = urllib.request.Request(src, headers={"User-Agent": USER_AGENT})
                with urllib.request.urlopen(req2, timeout=30) as r:
                    data = r.read()
            except (urllib.error.HTTPError, urllib.error.URLError):
                continue
            if data.startswith(b"\x89PNG\r\n\x1a\n"):
                return data, ".png"
            if data.startswith(b"\xff\xd8\xff"):
                return data, ".jpg"
    return None


def ensure_reference(refs_dir: Path, slug: str, sci: str, com: str) -> Path | None:
    """Cache-or-fetch a reference photo. Pre-existing references/<slug>.{jpg,png}
    are respected so you can hand-pick one."""
    refs_dir.mkdir(parents=True, exist_ok=True)
    for ext in REF_EXTS:
        cached = refs_dir / f"{slug}{ext}"
        if cached.exists() and cached.stat().st_size > 1024:
            return cached
    fetched = fetch_wikipedia_thumb(sci, com)
    if not fetched:
        return None
    data, ext = fetched
    path = refs_dir / f"{slug}{ext}"
    path.write_bytes(data)
    return path


def select_anti_ref_key(sci: str) -> str | None:
    genus = sci.split()[0]
    for genera, key, exclude in ANTI_REF_TRIGGERS:
        if genus in genera and sci != exclude:
            return key
    return None


def load_species_notes(notes_path: Path) -> dict[str, str]:
    if not notes_path.exists():
        return {}
    raw = json.loads(notes_path.read_text())
    return {k: v for k, v in raw.items()
            if not k.startswith("_") and isinstance(v, str)}


def load_anti_ref(refs_dir: Path, key: str = "bluejay") -> Path | None:
    p = refs_dir / f"_anti_{key}.jpg"
    return p if p.exists() else None


# ---- Gemini call ----

def _anti_ref_line(anti_ref_key: str | None) -> str:
    info = ANTI_REFS.get(anti_ref_key or "")
    if not info:
        return ""
    return (
        f"- IMAGE 2 (negative, when attached) is a {info['common_name']} "
        f"({info['sci_name']}). It is NOT what you are drawing. Do NOT "
        f"copy {info['do_not_copy']}. If your output looks more like "
        f"IMAGE 2 than IMAGE 1, the output is wrong."
    )


def _mime_for(p: Path) -> str:
    ext = p.suffix.lower()
    if ext in (".jpg", ".jpeg"):
        return "image/jpeg"
    if ext == ".png":
        return "image/png"
    if ext == ".webp":
        return "image/webp"
    return "application/octet-stream"


def gen_one(
    api_key: str, prompt: str, sci: str, com: str, pose: int,
    positive_ref: Path | None = None, anti_ref: Path | None = None,
    anti_ref_key: str | None = None, species_note: str | None = None,
    style_ref: Path | None = None,
) -> bytes:
    """Single Gemini call with bounded retry on 429 + transient 5xx. Returns
    raw PNG bytes."""
    body = (prompt
            .replace("{sci_name}", sci)
            .replace("{com_name}", com)
            .replace("{pose}", POSES[pose])
            .replace("{anti_ref_line}", _anti_ref_line(anti_ref_key)))
    if species_note:
        body = body + "\n\nSpecies-specific note: " + species_note

    parts: list[dict] = [{"text": body}]
    if positive_ref:
        # Downscale the anatomy reference to 384px on the long side so the model
        # reads species/markings/colors without mimicking photographic detail.
        try:
            from io import BytesIO

            from PIL import Image
            img = Image.open(positive_ref).convert("RGB")
            w, h = img.size
            if max(w, h) > 384:
                scale = 384 / max(w, h)
                img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
            buf = BytesIO()
            img.save(buf, format="PNG", optimize=True)
            ref_bytes, ref_mime = buf.getvalue(), "image/png"
        except Exception:
            ref_bytes, ref_mime = positive_ref.read_bytes(), _mime_for(positive_ref)
        parts.append({"text": "IMAGE 1 (positive, target species):"})
        parts.append({"inline_data": {
            "mime_type": ref_mime, "data": base64.b64encode(ref_bytes).decode()}})
    if anti_ref:
        anti_name = (ANTI_REFS.get(anti_ref_key or "") or {}).get(
            "common_name", "lookalike species")
        parts.append({"text": f"IMAGE 2 (negative, {anti_name}, do NOT copy):"})
        parts.append({"inline_data": {
            "mime_type": _mime_for(anti_ref),
            "data": base64.b64encode(anti_ref.read_bytes()).decode()}})
    if style_ref:
        parts.append({"text": (
            "IMAGE 3 (positive STYLE reference — Edo-period kachō-e woodblock "
            "print). The species in IMAGE 3 is irrelevant; only its painting "
            "technique is borrowed (flat washes, confident outlines, tonal "
            "mineral-pigment ground). DO NOT copy any branches, leaves, water, "
            "moon, or scenery from IMAGE 3.")})
        parts.append({"inline_data": {
            "mime_type": _mime_for(style_ref),
            "data": base64.b64encode(style_ref.read_bytes()).decode()}})

    payload = {
        "contents": [{"parts": parts}],
        "generationConfig": {"responseModalities": ["TEXT", "IMAGE"]},
    }
    req = urllib.request.Request(
        GEMINI_URL, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "x-goog-api-key": api_key},
        method="POST")

    backoff = 4.0
    resp = None
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=180) as r:
                resp = json.loads(r.read())
            break
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503, 504) and attempt < 3:
                ra = e.headers.get("Retry-After")
                try:
                    retry_after = float(ra) if ra else backoff
                except (TypeError, ValueError):
                    retry_after = backoff
                time.sleep(retry_after)
                backoff *= 2
                continue
            raise
        except urllib.error.URLError:
            if attempt < 3:
                time.sleep(backoff)
                backoff *= 2
                continue
            raise

    for cand in (resp or {}).get("candidates", []):
        for part in cand.get("content", {}).get("parts", []):
            inline = part.get("inlineData") or part.get("inline_data")
            if inline and inline.get("data"):
                return base64.b64decode(inline["data"])
    finish = ((resp or {}).get("candidates", [{}]) or [{}])[0].get("finishReason", "?")
    block = (resp or {}).get("promptFeedback", {}).get("blockReason", "")
    raise RuntimeError(f"no image (finish={finish} block={block})")


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    src = ap.add_mutually_exclusive_group()
    src.add_argument("--labels", type=Path, default=HERE / "species.txt",
                     help="Sci|Com species list (default: tools/kachoe/species.txt)")
    src.add_argument("--species", action="append", default=[],
                     help="Manual 'Sci|Com' (repeatable)")
    src.add_argument("--stdin", action="store_true", help="Read Sci|Com from stdin")
    ap.add_argument("--gemini-key", help="Gemini API key (or GEMINI_API_KEY env/.env)")
    ap.add_argument("--out", type=Path, default=HERE / "illustrations")
    ap.add_argument("--refs", type=Path, default=HERE / "refs",
                    help="Reference photo cache (default: tools/kachoe/refs/)")
    ap.add_argument("--styles", type=Path, default=HERE / "refs" / "styles")
    ap.add_argument("--prompt", type=Path, default=HERE / "prompt.template.md")
    ap.add_argument("--notes", type=Path, default=HERE / "species-notes.json")
    ap.add_argument("--poses", nargs="+", type=int, default=[1, 2], choices=[1, 2],
                    help="Which poses to render. 1=perched, 2=flight. Default: both.")
    ap.add_argument("--force", action="store_true", help="Re-render even if file exists")
    ap.add_argument("--no-refs", action="store_true",
                    help="Skip the Wikipedia reference fetch (lower quality)")
    ap.add_argument("--sleep", type=float, default=6.0,
                    help="Seconds between API calls (default 6)")
    ap.add_argument("--limit", type=int, default=0, help="Cap species count (testing)")
    args = ap.parse_args()

    load_dotenv(REPO_ROOT / ".env")
    gemini_key = args.gemini_key or os.environ.get("GEMINI_API_KEY", "")
    if not gemini_key:
        print("error: GEMINI_API_KEY required (set in .env, env, or --gemini-key)",
              file=sys.stderr)
        return 2

    if args.species:
        species, skipped = parse_species_list(args.species)
    elif args.stdin:
        species, skipped = parse_species_list(sys.stdin.read().splitlines())
    else:
        species, skipped = parse_species_list(args.labels.read_text().splitlines())
    if skipped:
        print(f"[parse] skipped {skipped} malformed line(s)", file=sys.stderr)
    if not species:
        print("error: no species resolved", file=sys.stderr)
        return 2
    if args.limit:
        species = species[:args.limit]

    prompt = load_prompt(args.prompt)
    args.out.mkdir(parents=True, exist_ok=True)
    anti_paths: dict[str, Path] = {}
    if not args.no_refs:
        for key in ANTI_REFS:
            p = load_anti_ref(args.refs, key)
            if p:
                anti_paths[key] = p
    notes = load_species_notes(args.notes)
    if notes:
        print(f"[notes] loaded per-species addenda for {len(notes)} species")
    for key, p in anti_paths.items():
        print(f"[refs] {ANTI_REFS[key]['common_name']} anti-reference: {p.name}")

    # Only count species that actually need a render (missing a pose file).
    pending = []
    for sci, com in species:
        slug = slugify(sci)
        need = [pose for pose in args.poses
                if args.force or not (args.out / (f"{slug}.png" if pose == 1
                                                  else f"{slug}-{pose}.png")).exists()]
        if need:
            pending.append((sci, com, need))
    total = sum(len(n) for _, _, n in pending)
    print(f"{len(pending)} species need art; generating up to {total} illustrations "
          f"into {args.out}/")

    done = failed = 0
    first_fail = None
    for idx, (sci, com, need) in enumerate(pending):
        slug = slugify(sci)
        pos_ref = None
        if not args.no_refs:
            pos_ref = ensure_reference(args.refs, slug, sci, com)
            if not pos_ref:
                print(f"  [warn] no Wikipedia photo for {sci} — no positive ref",
                      file=sys.stderr)
        anti_key = select_anti_ref_key(sci)
        anti = anti_paths.get(anti_key) if anti_key else None
        anti_key_for_call = anti_key if anti else None

        for pose in need:
            fname = f"{slug}.png" if pose == 1 else f"{slug}-{pose}.png"
            path = args.out / fname
            try:
                style_ref_path = args.styles / select_style_ref(sci, pose)
                if not style_ref_path.exists():
                    style_ref_path = None
                data = gen_one(gemini_key, prompt, sci, com, pose,
                               positive_ref=pos_ref, anti_ref=anti,
                               anti_ref_key=anti_key_for_call,
                               species_note=notes.get(sci), style_ref=style_ref_path)
                path.write_bytes(data)
                done += 1
                tags = ("+ref" if pos_ref else "") + ("+anti" if anti else "") \
                    + ("+style" if style_ref_path else "") + ("+note" if notes.get(sci) else "")
                print(f"  [ok]   {fname} ({len(data)//1024} KB){tags}")
            except (urllib.error.HTTPError, urllib.error.URLError, RuntimeError) as e:
                failed += 1
                first_fail = first_fail or fname
                print(f"  [fail] {fname}: {e}", file=sys.stderr)
            if not (idx == len(pending) - 1 and pose == need[-1]):
                time.sleep(args.sleep)

    print(f"\ngenerated {done} · failed {failed}")
    if first_fail:
        print(f"first failure: {first_fail} (re-run to retry only the misses)",
              file=sys.stderr)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
