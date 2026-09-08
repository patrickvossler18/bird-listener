"""`birdlistener update`: pull the latest code onto each node and re-run its
setup. Nodes installed by `flash` have a git checkout and passwordless sudo,
so this is fully unattended. --rsync pushes this checkout instead of pulling
from GitHub (for a node without git, or to test local changes) and runs the
setup script interactively.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

from . import site
from .prompts import say, step
from .sshkeys import ssh

EXCLUDES = [".git", "*/.venv", ".venv", "*/out", "__pycache__", "*/data", "tools/kachoe/illustrations",
            "tools/kachoe/refs", "wall-node/cutouts", "wall-node/images", "window-node/mosquitto/passwd",
            "window-node/birdnet-go/config", ".env", "wall-node/.env"]


def run(args) -> int:
    s = site.load()
    targets = {"window": args.window_host or s["window_host"], "wall": args.wall_host or s["wall_host"]}
    if args.node:
        targets = {args.node: targets[args.node]}
    rc = 0
    for node, host in targets.items():
        step(f"{node} node ({host})")
        if args.rsync:
            repo = Path(args.repo or ".").resolve()
            if not (repo / "install.sh").exists():
                raise SystemExit("error: --rsync needs to run from a bird-listener checkout (or --repo)")
            cmd = ["rsync", "-az", "--delete"] + [x for e in EXCLUDES for x in ("--exclude", e)]
            cmd += [f"{repo}/", f"{host}:bird-listener/"]
            say("    " + " ".join(cmd))
            subprocess.run(cmd, check=True)
            r = ssh(host, f"bash ~/bird-listener/{node}-node/setup.sh", tty=True, timeout=1800)
        else:
            r = ssh(host, "sudo -n bash ~/bird-listener/install.sh", tty=True, timeout=1800)
        if r.returncode != 0:
            say(f"    !! {host} exited {r.returncode}")
            rc = 1
    return rc
