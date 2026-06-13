#!/usr/bin/env python3
"""Wall-node display service.

Subscribes to BirdNET-Go detections over MQTT and refreshes the framed e-ink
panel with the matching Audubon plate. A BH1750 light sensor blanks the display
when the room is dark.

Usage:
  python display_service.py                 # run the MQTT service loop
  python display_service.py --once "<sci>"  # render one species and exit (no MQTT)
  python display_service.py --clear         # clear the panel and exit
"""
from __future__ import annotations

import argparse
import json
import sys
import threading
import time
from pathlib import Path

from config import CONFIG
from display_driver import get_driver
from light_sensor import LightSensor
from renderer import compose, to_panel


def load_species_map(path: Path) -> dict:
    if not path.exists():
        print(f"[map] {path} not found; all detections will use the fallback card")
        return {}
    with path.open() as f:
        return json.load(f)


def resolve_plate(species_map: dict, scientific_name: str) -> Path | None:
    """Look up the image filename for a scientific name (case-insensitive)."""
    key = scientific_name.strip().lower()
    by_lower = {k.lower(): v for k, v in species_map.items()}
    filename = by_lower.get(key)
    if not filename:
        return None
    path = CONFIG.images_dir / filename
    return path if path.exists() else None


def render_and_show(driver, species_map, *, common, scientific, when) -> None:
    plate = resolve_plate(species_map, scientific)
    if plate is None:
        print(f"[render] no plate for '{scientific}' -> fallback card")
    frame = compose(
        width=CONFIG.panel_width,
        height=CONFIG.panel_height,
        common_name=common or scientific,
        scientific_name=scientific,
        detected_at=when,
        plate_path=plate,
        fonts_dir=CONFIG.fonts_dir,
    )
    driver.show(to_panel(frame))


class Service:
    def __init__(self):
        self.species_map = load_species_map(CONFIG.species_map_path)
        self.driver = get_driver(CONFIG.out_dir, force_mock=CONFIG.force_mock_display)
        self.light = LightSensor(
            CONFIG.lux_off, CONFIG.lux_on, force_mock=CONFIG.force_mock_light
        )
        self._last_shown: dict[str, float] = {}  # scientific_name -> monotonic ts
        self._lock = threading.Lock()
        self._display_on = True
        self._pending = None  # (common, scientific, when) deferred while dark
        print(f"[service] display={self.driver.name} "
              f"light={'mock' if self.light.is_mock else 'BH1750'}")

    # --- detection handling ---
    def _accept(self, scientific: str, confidence: float) -> bool:
        if confidence < CONFIG.min_confidence:
            return False
        now = time.monotonic()
        last = self._last_shown.get(scientific.lower())
        if last is not None and (now - last) < CONFIG.debounce_seconds:
            return False
        return True

    def handle_detection(self, payload: dict) -> None:
        scientific = (payload.get("scientificName")
                      or payload.get("scientific_name") or "").strip()
        common = (payload.get("commonName")
                  or payload.get("common_name") or "").strip()
        confidence = float(payload.get("confidence", 0) or 0)
        when = payload.get("timestamp") or payload.get("time")
        if not scientific:
            print(f"[detect] ignoring payload without scientific name: {payload}")
            return
        if not self._accept(scientific, confidence):
            return

        with self._lock:
            self._last_shown[scientific.lower()] = time.monotonic()
            triple = (common, scientific, when)
            if self._display_on:
                print(f"[detect] {common or scientific} ({confidence:.2f}) -> drawing")
                render_and_show(self.driver, self.species_map,
                                common=common, scientific=scientific, when=when)
            else:
                # Remember the latest bird so we can show it when lights return.
                print(f"[detect] {common or scientific} held (room dark)")
                self._pending = triple

    # --- light gate loop ---
    def light_loop(self) -> None:
        while True:
            on = self.light.display_should_be_on()
            with self._lock:
                if on and not self._display_on:
                    self._display_on = True
                    print("[light] room lit -> display on")
                    if self._pending:
                        c, s, w = self._pending
                        self._pending = None
                        render_and_show(self.driver, self.species_map,
                                        common=c, scientific=s, when=w)
                elif not on and self._display_on:
                    self._display_on = False
                    print("[light] room dark -> display off")
                    self.driver.clear()
            time.sleep(CONFIG.light_poll_seconds)

    # --- mqtt loop ---
    def run(self) -> None:
        import paho.mqtt.client as mqtt

        threading.Thread(target=self.light_loop, daemon=True).start()

        def on_connect(client, userdata, flags, rc, *args):
            print(f"[mqtt] connected rc={rc}; subscribing {CONFIG.mqtt_topic}")
            client.subscribe(CONFIG.mqtt_topic)

        def on_message(client, userdata, msg):
            try:
                payload = json.loads(msg.payload.decode("utf-8"))
            except (ValueError, UnicodeDecodeError) as exc:
                print(f"[mqtt] bad payload ({exc!s}): {msg.payload!r}")
                return
            self.handle_detection(payload)

        client = mqtt.Client()
        if CONFIG.mqtt_username:
            client.username_pw_set(CONFIG.mqtt_username, CONFIG.mqtt_password)
        client.on_connect = on_connect
        client.on_message = on_message
        print(f"[mqtt] connecting to {CONFIG.mqtt_host}:{CONFIG.mqtt_port}")
        client.connect(CONFIG.mqtt_host, CONFIG.mqtt_port, keepalive=60)
        client.loop_forever()


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="Bird Listener wall-node display service")
    ap.add_argument("--once", metavar="SCIENTIFIC_NAME",
                    help="render one species to the panel and exit (no MQTT)")
    ap.add_argument("--common", default="", help="common name for --once")
    ap.add_argument("--clear", action="store_true", help="clear the panel and exit")
    args = ap.parse_args(argv)

    if args.clear:
        get_driver(CONFIG.out_dir, force_mock=CONFIG.force_mock_display).clear()
        return 0

    if args.once:
        species_map = load_species_map(CONFIG.species_map_path)
        driver = get_driver(CONFIG.out_dir, force_mock=CONFIG.force_mock_display)
        render_and_show(driver, species_map,
                        common=args.common, scientific=args.once, when=None)
        return 0

    Service().run()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
