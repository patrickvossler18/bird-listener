#!/usr/bin/env python3
"""Health report for the wall node. Text by default, --json for machines.

    ./.venv/bin/python doctor.py          # on the Pi
    python3 doctor.py --json              # anywhere (mock checks still run)

Every check is independent and never raises, so a half-broken node still
reports the parts that work. Exit status is 1 if any check failed.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent


def _run(cmd: list[str], timeout: float = 10) -> tuple[int, str]:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return p.returncode, (p.stdout + p.stderr).strip()
    except (OSError, subprocess.TimeoutExpired) as e:
        return 127, str(e)


def _read_env(path: Path) -> dict[str, str]:
    env: dict[str, str] = {}
    if not path.exists():
        return env
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip()
    return env


def _service_env() -> dict[str, str]:
    """Environment= lines of the installed unit, so a node whose settings live
    in the unit rather than .env still reports what the service really uses."""
    if not shutil.which("systemctl"):
        return {}
    rc, out = _run(["systemctl", "show", "bird-display", "--property=Environment", "--value"])
    env: dict[str, str] = {}
    if rc == 0:
        for tok in out.split():
            if "=" in tok:
                k, v = tok.split("=", 1)
                env[k] = v
    return env


def effective_env() -> dict[str, str]:
    env = _service_env()
    env.update(_read_env(HERE / ".env"))   # EnvironmentFile wins over Environment=
    return env


def check_env(env: dict[str, str]) -> dict:
    path = HERE / ".env"
    if not path.exists():
        return dict(name="settings", ok=False,
                    detail=f"{path} missing; run wall-node/setup.sh")
    missing = [k for k in ("BL_MQTT_HOST", "BL_MQTT_USER", "BL_MQTT_PASS") if not env.get(k)]
    if missing or env.get("BL_MQTT_PASS") == "change-me":
        return dict(name="settings", ok=False,
                    detail=f"{path}: set {', '.join(missing) or 'a real BL_MQTT_PASS'}")
    return dict(name="settings", ok=True, detail=f"{path} (broker {env['BL_MQTT_HOST']})")


def check_service() -> dict:
    if not shutil.which("systemctl"):
        return dict(name="service", ok=True, detail="no systemd here (laptop dry run)", skipped=True)
    rc, out = _run(["systemctl", "is-active", "bird-display"])
    if rc == 0:
        return dict(name="service", ok=True, detail="bird-display active")
    return dict(name="service", ok=False,
                detail=f"bird-display is {out or 'inactive'}; journalctl -u bird-display -n 50")


def check_panel() -> dict:
    if sys.platform != "linux":
        return dict(name="panel", ok=True, detail="not a Pi (mock driver)", skipped=True)
    problems = []
    if not Path("/dev/spidev0.0").exists():
        problems.append("SPI is off (/dev/spidev0.0 missing): sudo raspi-config nonint do_spi 0")
    epd = Path.home() / "e-Paper/RaspberryPi_JetsonNano/python/lib/waveshare_epd/epdconfig.py"
    if not epd.exists():
        problems.append("Waveshare e-Paper library not installed (~/e-Paper)")
    elif "PWR_PIN  = 27" not in epd.read_text():
        problems.append("e-Paper driver lacks the PhotoPainter PWR_PIN=27 patch; refreshes will hang")
    if problems:
        return dict(name="panel", ok=False, detail="; ".join(problems))
    return dict(name="panel", ok=True, detail="SPI on, e-Paper driver present and patched")


def check_mqtt(env: dict[str, str]) -> dict:
    host = env.get("BL_MQTT_HOST") or os.environ.get("BL_MQTT_HOST", "localhost")
    port = int(env.get("BL_MQTT_PORT") or os.environ.get("BL_MQTT_PORT", "1883"))
    try:
        with socket.create_connection((host, port), timeout=5):
            pass
    except OSError as e:
        return dict(name="mqtt", ok=False,
                    detail=f"cannot reach {host}:{port} ({e}); is the window node up and on the same WiFi?")
    # Authenticate if paho is importable (it is inside the wall-node venv).
    try:
        import paho.mqtt.client as mqtt  # type: ignore
    except ImportError:
        return dict(name="mqtt", ok=True, detail=f"{host}:{port} reachable (auth not tested: no paho)")
    result: dict = {}

    def on_connect(client, userdata, flags, rc, *args):
        result["rc"] = getattr(rc, "value", rc)
        client.disconnect()

    try:
        try:
            client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        except AttributeError:
            client = mqtt.Client()
        client.on_connect = on_connect
        if env.get("BL_MQTT_USER"):
            client.username_pw_set(env["BL_MQTT_USER"], env.get("BL_MQTT_PASS", ""))
        client.connect(host, port, keepalive=10)
        deadline = time.time() + 5
        while "rc" not in result and time.time() < deadline:
            client.loop(timeout=0.5)
    except Exception as e:  # noqa: BLE001
        return dict(name="mqtt", ok=False, detail=f"connect failed: {e}")
    rc = result.get("rc")
    if rc == 0:
        return dict(name="mqtt", ok=True, detail=f"{host}:{port} authenticated as {env.get('BL_MQTT_USER')}")
    if rc is None:
        return dict(name="mqtt", ok=False, detail=f"{host}:{port} no CONNACK within 5s")
    return dict(name="mqtt", ok=False,
                detail=f"{host}:{port} refused credentials (rc={rc}); BL_MQTT_PASS must match the window node")


def check_art() -> dict:
    cutouts = len(list((HERE / "cutouts").glob("*.png")))
    plates = len(list((HERE / "images").glob("*.jpg"))) + len(list((HERE / "images").glob("*.png")))
    if cutouts == 0 and plates == 0:
        return dict(name="art", ok=False,
                    detail="no cutouts or plates; run `birdlistener art` on your computer")
    return dict(name="art", ok=True, detail=f"{cutouts // 2} species as cutouts, {plates} plates")


def check_recent_render() -> dict:
    if shutil.which("journalctl"):
        rc, out = _run(["journalctl", "-u", "bird-display", "--no-pager", "-o", "short-iso",
                        "-n", "400", "--grep", r"\[render\]"], timeout=15)
        lines = [l for l in out.splitlines() if "[render]" in l]
        if lines:
            return dict(name="last-render", ok=True, detail=lines[-1][:120])
        return dict(name="last-render", ok=True, detail="no render yet since boot (waiting for a bird)")
    frame = HERE / "out" / "last_frame.png"
    if frame.exists():
        age = int(time.time() - frame.stat().st_mtime)
        return dict(name="last-render", ok=True, detail=f"{frame} written {age}s ago")
    return dict(name="last-render", ok=True, detail="no frame rendered yet")


def check_disk() -> dict:
    usage = shutil.disk_usage(HERE)
    free_gb = usage.free / 1e9
    return dict(name="disk", ok=free_gb > 0.5, detail=f"{free_gb:.1f} GB free")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    args = ap.parse_args()

    env = effective_env()
    checks = [check_env(env), check_service(), check_panel(), check_mqtt(env),
              check_art(), check_recent_render(), check_disk()]
    ok = all(c["ok"] for c in checks)
    report = dict(node="wall", host=socket.gethostname(), ok=ok, checks=checks)
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(f"wall node on {report['host']}: {'OK' if ok else 'PROBLEMS'}")
        for c in checks:
            mark = "ok " if c["ok"] else "FAIL"
            if c.get("skipped"):
                mark = "-- "
            print(f"  [{mark}] {c['name']:12s} {c['detail']}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
