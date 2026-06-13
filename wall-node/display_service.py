#!/usr/bin/env python3
"""Wall-node display service.

Subscribes to BirdNET-Go detections over MQTT and refreshes the framed e-ink
panel with the matching Audubon plate(s). Birds heard within a rolling window
are shown together as a collage (up to BL_MAX_BIRDS). A BH1750 light sensor
blanks the display when the room is dark.

Usage:
  python display_service.py                       # run the MQTT service loop
  python display_service.py --once "<sci>" [...]  # render given species and exit
  python display_service.py --clear               # clear the panel and exit
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
from renderer import compose_birds, to_panel


def load_species_map(path: Path) -> dict:
    if not path.exists():
        print(f"[map] {path} not found; all detections will use the fallback card")
        return {}
    with path.open() as f:
        return json.load(f)


def resolve_plate(species_map: dict, scientific_name: str) -> Path | None:
    """Look up the image path for a scientific name (case-insensitive)."""
    by_lower = {k.lower(): v for k, v in species_map.items()}
    filename = by_lower.get(scientific_name.strip().lower())
    if not filename:
        return None
    path = CONFIG.images_dir / filename
    return path if path.exists() else None


class RecentBirds:
    """Tracks recently-heard species within a rolling window, deduped by species
    (latest wins), most-recent first, capped at `max_birds`."""

    def __init__(self, window_seconds: float, max_birds: int):
        self.window = window_seconds
        self.max_birds = max_birds
        self._by_species: dict[str, dict] = {}  # scientific(lower) -> entry

    def add(self, *, scientific, common, when, now) -> None:
        self._by_species[scientific.lower()] = {
            "scientific": scientific, "common": common, "when": when, "ts": now,
        }

    def current(self, now) -> list[dict]:
        live = [e for e in self._by_species.values() if (now - e["ts"]) <= self.window]
        live.sort(key=lambda e: e["ts"], reverse=True)
        return live[: self.max_birds]

    def signature(self, now) -> tuple:
        return tuple(e["scientific"].lower() for e in self.current(now))


class Service:
    def __init__(self):
        self.species_map = load_species_map(CONFIG.species_map_path)
        self.driver = get_driver(CONFIG.out_dir, force_mock=CONFIG.force_mock_display)
        self.light = LightSensor(
            CONFIG.lux_off, CONFIG.lux_on, force_mock=CONFIG.force_mock_light
        )
        self.recent = RecentBirds(CONFIG.multi_window_seconds, CONFIG.max_birds)
        self._lock = threading.Lock()
        self._display_on = True
        self._pending = False          # display set changed since last render
        self._last_render_ts = -1e9    # monotonic
        self._rendered_sig: tuple = ()
        print(f"[service] display={self.driver.name} "
              f"light={'mock' if self.light.is_mock else 'BH1750'} "
              f"max_birds={CONFIG.max_birds}")

    def _render_now(self, now) -> None:
        birds = [
            {**e, "plate_path": resolve_plate(self.species_map, e["scientific"])}
            for e in self.recent.current(now)
        ]
        for b in birds:
            if b["plate_path"] is None:
                print(f"[render] no plate for '{b['scientific']}' -> fallback card")
        names = ", ".join(b["common"] or b["scientific"] for b in birds)
        print(f"[render] drawing {len(birds)} bird(s): {names}")
        self.driver.show(to_panel(
            compose_birds(CONFIG.panel_width, CONFIG.panel_height, birds,
                          CONFIG.fonts_dir, trim=CONFIG.plate_trim)
        ))
        self._rendered_sig = self.recent.signature(now)
        self._last_render_ts = now
        self._pending = False

    def _try_render(self, now) -> None:
        """Render if there's a pending change, the room is lit, and we're past
        the minimum refresh interval (protects the slow panel)."""
        if not (self._pending and self._display_on):
            return
        if (now - self._last_render_ts) < CONFIG.min_refresh_seconds:
            return
        self._render_now(now)

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
        if confidence < CONFIG.min_confidence:
            return

        now = time.monotonic()
        with self._lock:
            self.recent.add(scientific=scientific, common=common, when=when, now=now)
            if self.recent.signature(now) != self._rendered_sig:
                self._pending = True
                print(f"[detect] {common or scientific} ({confidence:.2f}) "
                      f"-> group now {list(self.recent.signature(now))}")
            self._try_render(now)

    def tick_loop(self) -> None:
        """Periodic: update the light gate and flush any time-gated render."""
        while True:
            on = self.light.display_should_be_on()
            now = time.monotonic()
            with self._lock:
                if on and not self._display_on:
                    self._display_on = True
                    print("[light] room lit -> display on")
                    self._pending = self._pending or (
                        self.recent.signature(now) != self._rendered_sig)
                elif not on and self._display_on:
                    self._display_on = False
                    print("[light] room dark -> display off")
                    self.driver.clear()
                    self._rendered_sig = ()  # force redraw when lit again
                self._try_render(now)
            time.sleep(CONFIG.light_poll_seconds)

    def run(self) -> None:
        import paho.mqtt.client as mqtt

        threading.Thread(target=self.tick_loop, daemon=True).start()

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
    ap.add_argument("--once", nargs="+", metavar="SCIENTIFIC_NAME",
                    help="render the given species(s) to the panel and exit (no MQTT)")
    ap.add_argument("--clear", action="store_true", help="clear the panel and exit")
    args = ap.parse_args(argv)

    if args.clear:
        get_driver(CONFIG.out_dir, force_mock=CONFIG.force_mock_display).clear()
        return 0

    if args.once:
        species_map = load_species_map(CONFIG.species_map_path)
        driver = get_driver(CONFIG.out_dir, force_mock=CONFIG.force_mock_display)
        birds = [
            {"scientific": s, "common": "", "when": None,
             "plate_path": resolve_plate(species_map, s)}
            for s in args.once
        ]
        driver.show(to_panel(
            compose_birds(CONFIG.panel_width, CONFIG.panel_height, birds,
                          CONFIG.fonts_dir, trim=CONFIG.plate_trim)
        ))
        return 0

    Service().run()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
