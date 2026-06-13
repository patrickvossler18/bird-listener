"""Configuration for the wall-node display service.

All settings come from environment variables with sensible defaults so the
service runs unconfigured in mock mode on a laptop, and is fully configurable
on the Pi via a systemd unit / .env file.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

HERE = Path(__file__).resolve().parent


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ[name])
    except (KeyError, ValueError):
        return default


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ[name])
    except (KeyError, ValueError):
        return default


@dataclass(frozen=True)
class Config:
    # --- MQTT ---
    mqtt_host: str = os.environ.get("BL_MQTT_HOST", "localhost")
    mqtt_port: int = _env_int("BL_MQTT_PORT", 1883)
    mqtt_topic: str = os.environ.get("BL_MQTT_TOPIC", "birdnet/detection")
    mqtt_username: str | None = os.environ.get("BL_MQTT_USER") or None
    mqtt_password: str | None = os.environ.get("BL_MQTT_PASS") or None

    # --- Detection filtering ---
    # Ignore detections below this confidence (BirdNET confidence is 0..1).
    min_confidence: float = _env_float("BL_MIN_CONFIDENCE", 0.65)
    # Don't redraw the same species more often than this (seconds).
    debounce_seconds: float = _env_float("BL_DEBOUNCE_SECONDS", 300.0)

    # --- Display panel ---
    panel_width: int = _env_int("BL_PANEL_WIDTH", 800)
    panel_height: int = _env_int("BL_PANEL_HEIGHT", 480)

    # --- Light gate (BH1750, lux) ---
    # Hysteresis: turn off below `lux_off`, back on above `lux_on`.
    lux_off: float = _env_float("BL_LUX_OFF", 5.0)
    lux_on: float = _env_float("BL_LUX_ON", 15.0)
    light_poll_seconds: float = _env_float("BL_LIGHT_POLL_SECONDS", 10.0)

    # --- Paths ---
    images_dir: Path = Path(os.environ.get("BL_IMAGES_DIR", str(HERE / "images")))
    species_map_path: Path = Path(
        os.environ.get("BL_SPECIES_MAP", str(HERE / "species_map.json"))
    )
    fonts_dir: Path = Path(os.environ.get("BL_FONTS_DIR", str(HERE / "fonts")))
    out_dir: Path = Path(os.environ.get("BL_OUT_DIR", str(HERE / "out")))

    # Force the mock display driver even if Waveshare libs are present
    # (useful for testing on the Pi without refreshing the slow panel).
    force_mock_display: bool = os.environ.get("BL_FORCE_MOCK_DISPLAY", "") == "1"
    force_mock_light: bool = os.environ.get("BL_FORCE_MOCK_LIGHT", "") == "1"


CONFIG = Config()
