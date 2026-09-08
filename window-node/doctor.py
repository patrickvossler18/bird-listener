#!/usr/bin/env python3
"""Health report for the window node. Text by default, --json for machines.

    python3 doctor.py            # on the Pi (stdlib only)

Every check is independent and never raises. Exit status is 1 if any failed.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
CONFIG = HERE / "birdnet-go" / "config" / "config.yaml"
PASSWD = HERE / "mosquitto" / "passwd"


def _run(cmd: list[str], timeout: float = 15) -> tuple[int, str]:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return p.returncode, (p.stdout + p.stderr).strip()
    except (OSError, subprocess.TimeoutExpired) as e:
        return 127, str(e)


def _docker() -> list[str]:
    rc, _ = _run(["docker", "info"], timeout=20)
    return ["docker"] if rc == 0 else ["sudo", "-n", "docker"]


def _read_node_env() -> dict[str, str]:
    env: dict[str, str] = {}
    p = Path("/etc/bird-listener/node.env")
    try:
        for line in p.read_text().splitlines():
            if line.strip() and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    except OSError:
        pass
    return env


def check_docker(docker: list[str]) -> dict:
    rc, out = _run(docker + ["info", "--format", "{{.ServerVersion}}"], timeout=20)
    if rc != 0:
        return dict(name="docker", ok=False, detail="docker daemon not reachable; bash window-node/setup.sh")
    return dict(name="docker", ok=True, detail=f"engine {out.splitlines()[-1]}")


def check_containers(docker: list[str]) -> dict:
    problems = []
    for name in ("birdnet-go", "mosquitto"):
        rc, out = _run(docker + ["inspect", name, "--format",
                                 "{{.State.Status}} {{if .State.Health}}{{.State.Health.Status}}{{end}}"])
        if rc != 0:
            problems.append(f"{name} not created")
            continue
        status = out.split()
        if status[0] != "running":
            problems.append(f"{name} is {status[0]}")
        elif len(status) > 1 and status[1] not in ("healthy", ""):
            problems.append(f"{name} is {status[1]}")
    if problems:
        return dict(name="containers", ok=False,
                    detail="; ".join(problems) + " (docker compose up -d; docker compose logs)")
    return dict(name="containers", ok=True, detail="birdnet-go and mosquitto running")


def check_mic() -> dict:
    cards = Path("/proc/asound/cards")
    if not cards.exists():
        return dict(name="mic", ok=True, detail="no ALSA here (laptop dry run)", skipped=True)
    text = cards.read_text()
    names = re.findall(r"^\s*\d+\s+\[([^\]]+)\]:\s*(.*)$", text, re.M)
    capture = [n for n in names if "usb" in (n[0] + n[1]).lower()]
    if not capture:
        return dict(name="mic", ok=False,
                    detail="no USB audio device; plug the mic in and check `arecord -l`")
    return dict(name="mic", ok=True, detail=", ".join(n[0].strip() for n in capture))


def _yaml_scalar(text: str, section_indent: int, key: str, after: str | None = None) -> str | None:
    """Tiny targeted lookup so the doctor needs no PyYAML."""
    start = 0
    if after:
        m = re.search(rf"^{re.escape(after)}\s*$", text, re.M)
        if not m:
            return None
        start = m.end()
    m = re.search(rf"^ {{{section_indent}}}{re.escape(key)}:\s*(.*)$", text[start:], re.M)
    return m.group(1).strip().strip("'\"") if m else None


def check_config() -> dict:
    if not CONFIG.exists():
        return dict(name="config", ok=False, detail=f"{CONFIG} missing; start BirdNET-Go once")
    text = CONFIG.read_text()
    lat = _yaml_scalar(text, 4, "latitude")
    lon = _yaml_scalar(text, 4, "longitude")
    mqtt_block = re.search(r"^    mqtt:\n((?:\s{8}.*\n)+)", text, re.M)
    enabled = broker = topic = user = None
    if mqtt_block:
        b = mqtt_block.group(1)
        enabled = _yaml_scalar(b, 8, "enabled")
        broker = _yaml_scalar(b, 8, "broker")
        topic = _yaml_scalar(b, 8, "topic")
        user = _yaml_scalar(b, 8, "username")
    problems = []
    try:
        if float(lat or 0) == 0.0 and float(lon or 0) == 0.0:
            problems.append("latitude/longitude are 0,0")
    except ValueError:
        problems.append("latitude/longitude unreadable")
    if enabled != "true":
        problems.append("realtime.mqtt.enabled is not true")
    if topic != "birdnet/detection":
        problems.append(f"mqtt topic is {topic!r}")
    if not user:
        problems.append("mqtt username empty")
    if problems:
        return dict(name="config", ok=False,
                    detail="; ".join(problems) + " (python3 window-node/configure_birdnet.py)")
    return dict(name="config", ok=True, detail=f"at {lat},{lon}; mqtt -> {broker} {topic} as {user}")


def check_mqtt(docker: list[str]) -> dict:
    env = _read_node_env()
    user, password = env.get("BL_MQTT_USER", "birds"), env.get("BL_MQTT_PASS", "")
    if not PASSWD.exists():
        return dict(name="mqtt", ok=False, detail=f"{PASSWD} missing; bash window-node/setup.sh")
    if not password:
        try:
            with socket.create_connection(("localhost", 1883), timeout=3):
                pass
            return dict(name="mqtt", ok=True, detail="broker listening (auth untested: no node.env password)")
        except OSError as e:
            return dict(name="mqtt", ok=False, detail=f"broker not listening on 1883 ({e})")
    if shutil.which("mosquitto_sub"):
        cmd = ["mosquitto_sub", "-h", "localhost"]
    else:
        cmd = docker + ["exec", "mosquitto", "mosquitto_sub"]
    rc, out = _run(cmd + ["-C", "1", "-W", "4", "-t", "$SYS/broker/version", "-u", user, "-P", password])
    if rc == 0 and out:
        return dict(name="mqtt", ok=True, detail=f"authenticated as {user}: {out.splitlines()[-1]}")
    if "not authorised" in out.lower() or "not authorized" in out.lower():
        return dict(name="mqtt", ok=False, detail="broker refused the node.env password; re-run setup.sh")
    return dict(name="mqtt", ok=False, detail=f"subscribe failed: {out or 'timeout'}")


def check_detections() -> dict:
    try:
        with urllib.request.urlopen("http://localhost:8080/api/v2/detections/recent?limit=1", timeout=8) as r:
            data = json.loads(r.read())
    except Exception as e:  # noqa: BLE001
        return dict(name="detections", ok=False, detail=f"BirdNET-Go API not answering on :8080 ({e})")
    if not data:
        return dict(name="detections", ok=True, detail="API up, no detections yet (be patient, or play a bird call)")
    d = data[0]
    when = d.get("timestamp") or f"{d.get('date')} {d.get('time')}"
    age = ""
    try:
        ts = datetime.fromisoformat(str(when).replace("Z", "+00:00"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        mins = int((datetime.now(timezone.utc) - ts).total_seconds() // 60)
        age = f" ({mins} min ago)"
    except ValueError:
        pass
    return dict(name="detections", ok=True,
                detail=f"last: {d.get('commonName')} {d.get('confidence')}{age}")


def check_disk() -> dict:
    free_gb = shutil.disk_usage(HERE).free / 1e9
    return dict(name="disk", ok=free_gb > 1.0, detail=f"{free_gb:.1f} GB free")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    docker = _docker()
    checks = [check_docker(docker), check_containers(docker), check_mic(), check_config(),
              check_mqtt(docker), check_detections(), check_disk()]
    ok = all(c["ok"] for c in checks)
    report = dict(node="window", host=socket.gethostname(), ok=ok, checks=checks)
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(f"window node on {report['host']}: {'OK' if ok else 'PROBLEMS'}")
        for c in checks:
            mark = "-- " if c.get("skipped") else ("ok " if c["ok"] else "FAIL")
            print(f"  [{mark}] {c['name']:12s} {c['detail']}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
