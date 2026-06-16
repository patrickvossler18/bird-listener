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

    # --- Multi-bird display ---
    # Max birds shown at once (1 = always show only the most recent bird).
    max_birds: int = _env_int("BL_MAX_BIRDS", 4)
    # A detected species stays in the on-screen group for this long (seconds);
    # birds heard within the same window are shown together as a collage.
    multi_window_seconds: float = _env_float("BL_MULTI_WINDOW_SECONDS", 900.0)
    # Never refresh the (slow) e-ink panel more often than this, to protect it
    # and avoid flicker when several distinct species arrive in quick succession.
    min_refresh_seconds: float = _env_float("BL_MIN_REFRESH_SECONDS", 30.0)

    # --- Display panel ---
    panel_width: int = _env_int("BL_PANEL_WIDTH", 800)
    panel_height: int = _env_int("BL_PANEL_HEIGHT", 480)
    # Crop the empty cream margin off plates in a collage so birds sit closer.
    plate_trim: bool = os.environ.get("BL_PLATE_TRIM", "1") != "0"
    # Rotate the final frame before pushing to the panel (0 or 180). Use 180 if
    # the panel is mounted upside-down in the frame.
    rotate: int = _env_int("BL_ROTATE", 0)
    # Floyd-Steinberg dithering on (default), or "none" for hard nearest-color
    # (sharper edges, but visible color banding).
    dither: bool = os.environ.get("BL_DITHER", "floyd").lower() != "none"
    # Pre-sharpen (UnsharpMask) amount applied before dithering; 0 = off.
    # ~0.6-1.2 crisps up detail so the dithered result reads sharper.
    sharpen: float = _env_float("BL_SHARPEN", 0.0)
    # Snap the cream paper background to pure white before dithering, so it
    # doesn't dither into yellow/red speckle. On by default; BL_CLEAN_BG=0 off.
    clean_bg: bool = os.environ.get("BL_CLEAN_BG", "1") != "0"
    # Caption text scale for the single-bird name bar (1.0 = default size).
    caption_scale: float = _env_float("BL_CAPTION_SCALE", 1.0)

    # --- Light gate (BH1750, lux) ---
    # OFF by default: e-ink holds its image with no power, so blanking when the
    # room is dark isn't needed. Set BL_LIGHT_GATE=1 to re-enable the sensor.
    light_gate: bool = os.environ.get("BL_LIGHT_GATE", "0") == "1"
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
