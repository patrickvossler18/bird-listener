"""`birdlistener doctor`: run both nodes' health checks over SSH and show them
together. --json for agents.
"""
from __future__ import annotations

import json
import socket
import subprocess

from . import site
from .sshkeys import ssh

WINDOW_CMD = "python3 ~/bird-listener/window-node/doctor.py --json"
# The venv python has paho for the auth check; fall back to system python3.
# (An if/else, not ||: the doctor exits 1 on problems, which must not re-run it.)
WALL_CMD = ("if test -x ~/bird-listener/wall-node/.venv/bin/python; then "
            "~/bird-listener/wall-node/.venv/bin/python ~/bird-listener/wall-node/doctor.py --json; "
            "else python3 ~/bird-listener/wall-node/doctor.py --json; fi")


def reach(host: str) -> str | None:
    try:
        socket.getaddrinfo(f"{host}.local" if "." not in host else host, 22)
    except socket.gaierror:
        # Also try the bare alias (ssh config may map it to an IP).
        try:
            socket.getaddrinfo(host, 22)
        except socket.gaierror:
            return f"{host}: not found on the network (mDNS). Is it powered and on the same WiFi?"
    return None


def probe(host: str, cmd: str) -> dict:
    problem = reach(host)
    if problem:
        return dict(host=host, ok=False, error=problem, checks=[])
    try:
        r = ssh(host, cmd, timeout=90)
    except subprocess.TimeoutExpired:
        return dict(host=host, ok=False, error=f"{host}: ssh timed out", checks=[])
    out = r.stdout.strip()
    if "{" not in out:
        hint = r.stderr.strip().splitlines()[-1] if r.stderr.strip() else "no output"
        if "Permission denied" in hint:
            hint += " (the key in ~/.ssh/config was not accepted; was this Pi flashed by this computer?)"
        if "No such file" in out + r.stderr or "can't open file" in out + r.stderr:
            hint = "repo not installed yet; first boot may still be running (10-20 min)"
        return dict(host=host, ok=False, error=f"{host}: {hint}", checks=[])
    try:
        data = json.loads(out[out.index("{"):])
    except json.JSONDecodeError:
        return dict(host=host, ok=False, error=f"{host}: unreadable doctor output", checks=[])
    data["host"] = host
    return data


def print_report(rep: dict, label: str) -> None:
    if rep.get("error"):
        print(f"{label}: FAIL  {rep['error']}")
        return
    print(f"{label} ({rep.get('host')}): {'OK' if rep.get('ok') else 'PROBLEMS'}")
    for c in rep.get("checks", []):
        mark = "-- " if c.get("skipped") else ("ok " if c["ok"] else "FAIL")
        print(f"  [{mark}] {c['name']:12s} {c['detail']}")


def run(args) -> int:
    s = site.load()
    window_host = args.window_host or s["window_host"]
    wall_host = args.wall_host or s["wall_host"]
    reports = {}
    if args.node in (None, "window"):
        reports["window"] = probe(window_host, WINDOW_CMD)
    if args.node in (None, "wall"):
        reports["wall"] = probe(wall_host, WALL_CMD)
    ok = all(r.get("ok") for r in reports.values())
    if args.json:
        print(json.dumps(dict(ok=ok, nodes=reports), indent=2))
    else:
        for label, rep in reports.items():
            print_report(rep, f"{label} node")
            print()
        print("all good" if ok else "see FAIL lines above; TROUBLESHOOTING.md has the common fixes")
    return 0 if ok else 1
