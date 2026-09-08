"""`birdlistener art`: build the kachō-e cutouts for your birds and put them
on the wall node.

    species list (over SSH from the window node) -> tools/kachoe/run_pipeline.py
    (locally in a venv, or in Docker) -> rsync wall-node/cutouts/ to the wall node

Or skip generation with a prebuilt regional bundle: --bundle sf-bay-area.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

from . import site
from .prompts import ask, say, step
from .sshkeys import ssh

BUNDLE_RELEASE = "art-bundles"


def find_repo(explicit: str | None) -> Path:
    for candidate in [explicit, os.environ.get("BIRDLISTENER_REPO"), site.load().get("repo_dir"), os.getcwd()]:
        if candidate and (Path(candidate) / "tools" / "kachoe" / "run_pipeline.py").exists():
            return Path(candidate).resolve()
    raise SystemExit("error: run this inside a bird-listener checkout, or pass --repo PATH\n"
                     "       (git clone https://github.com/patrickvossler18/bird-listener.git)")


def pipeline_python(repo: Path) -> Path:
    """A venv under tools/kachoe with the pipeline deps; created on first use."""
    venv = repo / "tools" / "kachoe" / ".venv"
    py = venv / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
    if not py.exists():
        step("Creating the pipeline venv (one time; rembg + onnxruntime are large)")
        subprocess.run([sys.executable, "-m", "venv", str(venv)], check=True)
        subprocess.run([str(py), "-m", "pip", "install", "-q", "--upgrade", "pip"], check=True)
        subprocess.run([str(py), "-m", "pip", "install", "-q", "-r",
                        str(repo / "tools" / "kachoe" / "requirements.txt")], check=True)
    return py


def fetch_range(window_host: str, repo: Path) -> Path:
    step(f"Fetching the species list from {window_host} (BirdNET-Go's range model)")
    out = repo / "tools" / "kachoe" / "range.json"
    cfg = "~/bird-listener/window-node/birdnet-go/config/config.yaml"
    r = ssh(window_host, f"grep -E '^    (latitude|longitude):' {cfg}")
    coords = dict(l.strip().split(": ") for l in r.stdout.splitlines() if ": " in l)
    if r.returncode != 0 or "latitude" not in coords:
        raise SystemExit(f"error: could not read coordinates from {window_host} ({r.stderr.strip()})")
    q = f"lat={coords['latitude']}&lon={coords['longitude']}"
    r = ssh(window_host, f"curl -sf 'http://localhost:8080/api/v2/range/species/list?{q}'", timeout=90)
    if r.returncode != 0 or not r.stdout.strip():
        raise SystemExit(f"error: BirdNET-Go on {window_host} did not answer; birdlistener doctor")
    out.write_text(r.stdout)
    say(f"    at {coords['latitude']}, {coords['longitude']} -> {out}")
    return out


def sync_to_wall(wall_host: str, repo: Path, *, dry_run: bool) -> None:
    src = repo / "wall-node" / "cutouts"
    n = len(list(src.glob("*.png")))
    step(f"Syncing {n} cutout files to {wall_host}")
    cmd = ["rsync", "-az", "--info=stats1", f"{src}/", f"{wall_host}:bird-listener/wall-node/cutouts/"]
    if dry_run:
        say("    " + " ".join(cmd))
        return
    if not shutil.which("rsync"):
        raise SystemExit("error: rsync not installed (brew install rsync / apt install rsync)")
    subprocess.run(cmd, check=True)
    r = ssh(wall_host, "sudo -n systemctl restart bird-display")
    if r.returncode == 0:
        say("    bird-display restarted; the next detection uses the new art")
    else:
        say(f"    could not restart bird-display without a password; on the Pi run:\n"
            f"      sudo systemctl restart bird-display")


def fetch_bundle(name_or_url: str, repo: Path) -> None:
    url = name_or_url
    if not url.startswith("http"):
        base = site.load()["repo_url"].removesuffix(".git")
        url = f"{base}/releases/download/{BUNDLE_RELEASE}/{name_or_url}.zip"
    dest = repo / "wall-node" / "cutouts"
    dest.mkdir(parents=True, exist_ok=True)
    step(f"Downloading art bundle {url}")
    tmp = dest / ".bundle.zip"
    with urllib.request.urlopen(url, timeout=120) as r, open(tmp, "wb") as f:
        shutil.copyfileobj(r, f)
    with zipfile.ZipFile(tmp) as z:
        names = [n for n in z.namelist() if n.endswith(".png")]
        for n in names:
            (dest / Path(n).name).write_bytes(z.read(n))
    tmp.unlink()
    say(f"    {len(names)} files into {dest}")


def run(args) -> int:
    s = site.load()
    repo = find_repo(args.repo)
    window_host = args.window_host or s["window_host"]
    wall_host = args.wall_host or s["wall_host"]

    if args.bundle:
        fetch_bundle(args.bundle, repo)
    else:
        range_json = Path(args.from_json) if args.from_json else fetch_range(window_host, repo)
        key = args.gemini_key or os.environ.get("GEMINI_API_KEY", "")
        env_file = repo / ".env"
        if not key and env_file.exists():
            for line in env_file.read_text().splitlines():
                if line.startswith("GEMINI_API_KEY="):
                    key = line.split("=", 1)[1].strip().strip("'\"")
        if not key and not args.skip_generate and not args.dry_run:
            key = ask("Gemini API key (https://aistudio.google.com/apikey; Enter to skip generation)",
                      flag="--gemini-key", value=None, default="-", secret=True)
            key = "" if key == "-" else key
            if key and not env_file.exists():
                env_file.write_text(f"GEMINI_API_KEY={key}\n")
                env_file.chmod(0o600)
                say(f"    saved to {env_file} (gitignored)")

        pipeline = ["tools/kachoe/run_pipeline.py", "--from-json", str(range_json)]
        if args.skip_generate or not key:
            pipeline.append("--skip-generate")
        if args.limit:
            pipeline += ["--limit", str(args.limit)]
        if args.dry_run:
            pipeline.append("--dry-run")

        if args.docker:
            step("Running the pipeline in Docker")
            subprocess.run(["docker", "build", "-q", "-t", "bird-listener-art",
                            str(repo / "tools" / "kachoe")], check=True)
            cache = Path.home() / ".u2net"
            cache.mkdir(exist_ok=True)
            cmd = ["docker", "run", "--rm", "-t", "-v", f"{repo}:/repo", "-v", f"{cache}:/root/.u2net",
                   "-e", f"GEMINI_API_KEY={key}", "bird-listener-art", "python3"] + pipeline
        else:
            py = pipeline_python(repo)
            cmd = [str(py)] + pipeline
        env = dict(os.environ, GEMINI_API_KEY=key)
        rc = subprocess.call(cmd, cwd=repo, env=env)
        if rc != 0:
            return rc
        if args.dry_run:
            return 0

    if args.no_sync:
        return 0
    sync_to_wall(wall_host, repo, dry_run=args.dry_run)
    return 0
