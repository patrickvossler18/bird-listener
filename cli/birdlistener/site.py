"""The laptop-side record of one bird-listener install: hostnames, credentials
shared by both Pis, location. Written by `flash`, read by everything else, so
the second card and every later command ask nothing already answered.

Location: ~/.config/bird-listener/site.json (mode 0600; it holds the WiFi and
MQTT passwords so the second flash needs no retyping).
"""
from __future__ import annotations

import json
import os
from pathlib import Path

SITE_DIR = Path(os.environ.get("BIRDLISTENER_HOME", Path.home() / ".config" / "bird-listener"))
SITE_FILE = SITE_DIR / "site.json"

DEFAULTS = {
    "user": "pi",
    "window_host": "birdpi",
    "wall_host": "birdwall",
    "mqtt_user": "birds",
    "repo_url": "https://github.com/patrickvossler18/bird-listener.git",
    "repo_ref": "main",
    "threshold": 0.7,
    "rotate": 180,
}


def load() -> dict:
    data = dict(DEFAULTS)
    if SITE_FILE.exists():
        try:
            data.update(json.loads(SITE_FILE.read_text()))
        except json.JSONDecodeError as e:
            raise SystemExit(f"error: {SITE_FILE} is not valid JSON ({e})")
    return data


def save(data: dict) -> Path:
    SITE_DIR.mkdir(parents=True, exist_ok=True)
    SITE_FILE.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
    os.chmod(SITE_FILE, 0o600)
    return SITE_FILE


def redacted(data: dict) -> dict:
    return {k: ("<set>" if ("pass" in k or "key" in k) and v else v) for k, v in data.items()}
