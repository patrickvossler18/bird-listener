#!/usr/bin/env python3
"""Patch the settings bird-listener needs into BirdNET-Go's config.yaml.

BirdNET-Go writes a complete config.yaml on first start; this sets only the
keys we care about and leaves everything else as generated:

    birdnet.latitude / longitude / threshold
    realtime.mqtt.{enabled, broker, topic, username, password}

Values come from flags, else /etc/bird-listener/node.env, else are left alone.
Idempotent; prints what changed. Restart BirdNET-Go afterwards:
    docker compose restart birdnet-go

Needs PyYAML (apt: python3-yaml). The generated file carries no comments, so a
load/dump round trip loses nothing that matters.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover
    print("error: PyYAML missing (sudo apt-get install -y python3-yaml)", file=sys.stderr)
    sys.exit(2)

HERE = Path(__file__).resolve().parent
DEFAULT_CONFIG = HERE / "birdnet-go" / "config" / "config.yaml"


def read_node_env(path: Path) -> dict[str, str]:
    env: dict[str, str] = {}
    if path.exists():
        for line in path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    return env


def set_path(doc: dict, dotted: str, value) -> bool:
    node = doc
    parts = dotted.split(".")
    for p in parts[:-1]:
        if not isinstance(node.get(p), dict):
            node[p] = {}
        node = node[p]
    changed = node.get(parts[-1]) != value
    node[parts[-1]] = value
    return changed


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    ap.add_argument("--node-env", type=Path, default=Path("/etc/bird-listener/node.env"))
    ap.add_argument("--lat", type=float)
    ap.add_argument("--lon", type=float)
    ap.add_argument("--threshold", type=float)
    ap.add_argument("--mqtt-user")
    ap.add_argument("--mqtt-pass")
    ap.add_argument("--broker", default="tcp://mosquitto:1883")
    ap.add_argument("--topic", default="birdnet/detection")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    env = read_node_env(args.node_env)

    def pick(flag, key, cast):
        if flag is not None:
            return flag
        raw = env.get(key)
        if raw in (None, ""):
            return None
        try:
            return cast(raw)
        except ValueError:
            return None

    lat = pick(args.lat, "BL_LATITUDE", float)
    lon = pick(args.lon, "BL_LONGITUDE", float)
    threshold = pick(args.threshold, "BL_THRESHOLD", float)
    user = pick(args.mqtt_user, "BL_MQTT_USER", str)
    password = pick(args.mqtt_pass, "BL_MQTT_PASS", str)

    if not args.config.exists():
        print(f"error: {args.config} not found; start BirdNET-Go once so it writes its config",
              file=sys.stderr)
        return 1
    doc = yaml.safe_load(args.config.read_text()) or {}

    updates: dict[str, object] = {
        "realtime.mqtt.enabled": True,
        "realtime.mqtt.broker": args.broker,
        "realtime.mqtt.topic": args.topic,
    }
    if lat is not None and lon is not None and (lat, lon) != (0.0, 0.0):
        updates["birdnet.latitude"] = lat
        updates["birdnet.longitude"] = lon
    if threshold is not None:
        updates["birdnet.threshold"] = threshold
    if user:
        updates["realtime.mqtt.username"] = user
    if password:
        updates["realtime.mqtt.password"] = password

    changed = [k for k, v in updates.items() if set_path(doc, k, v)]
    for k, v in updates.items():
        shown = "<set>" if "password" in k else v
        print(f"  {'*' if k in changed else ' '} {k} = {shown}")
    if not changed:
        print("config.yaml already up to date")
        return 0
    if args.dry_run:
        print(f"(dry run) would update {len(changed)} key(s) in {args.config}")
        return 0
    args.config.write_text(yaml.safe_dump(doc, sort_keys=False, default_flow_style=False))
    print(f"updated {len(changed)} key(s) in {args.config}; restart birdnet-go to apply")
    return 0


if __name__ == "__main__":
    sys.exit(main())
