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

    # --- Art mode ---
    # "collage": nest transparent kachō-e cutouts (wall-node/cutouts/) into an
    # organic cluster. "plates": the legacy Audubon-plate row/full-bleed render.
    # Collage auto-falls-back to plates if numpy is missing or no bird has a
    # cutout, so this is safe to leave on.
    art_mode: str = os.environ.get("BL_ART_MODE", "collage")

    # --- Collage packing (only used when art_mode == "collage") ---
    # Show a small bird-name strip along the bottom of the collage. On by
    # default; BL_COLLAGE_NAMES=0 for a pure label-free collage. Text size
    # follows BL_CAPTION_SCALE.
    collage_names: bool = os.environ.get("BL_COLLAGE_NAMES", "1") != "0"
    # Fraction of a flight pose vs the default perched pose, per species.
    fly_prob: float = _env_float("BL_FLY_PROB", 0.12)
    # Soft area budget the cluster fills, as a fraction of the panel area.
    collage_budget_frac: float = _env_float("BL_COLLAGE_BUDGET", 0.5)
    # Recency size falloff: tile area scales by decay**rank (rank 0 = most
    # recent, biggest). Lower = stronger size contrast between new and old.
    collage_recency_decay: float = _env_float("BL_COLLAGE_DECAY", 0.78)
    # Floor so even the oldest bird in the window stays legible.
    collage_min_area_frac: float = _env_float("BL_COLLAGE_MIN_AREA", 0.02)
    # >1 widens the cluster (landscape panel); 1 = circular spiral.
    collage_ellipse_bias: float = _env_float("BL_COLLAGE_ELLIPSE", 2.0)
    # Gap (grid cells) kept around every silhouette so birds don't touch.
    collage_pad: int = _env_int("BL_COLLAGE_PAD", 3)
    # Occupancy-grid resolution (panel px per cell). Smaller = tighter nesting
    # but slower packing on the Pi.
    collage_grid_stride: int = _env_int("BL_COLLAGE_STRIDE", 4)

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
    # Snap near-black ink to pure black (and near-white to white) before
    # dithering so dark birds render solid instead of rainbow speckle on the
    # 6-colour palette. On by default; BL_CLEAN_INK=0 off.
    clean_ink: bool = os.environ.get("BL_CLEAN_INK", "1") != "0"
    # Caption text scale for the single-bird name bar (1.0 = default size).
    caption_scale: float = _env_float("BL_CAPTION_SCALE", 1.0)
    # IANA zone used to localize the detection timestamp in the caption. Defaults
    # to Pacific; BirdNET-Go emits UTC, so without this the panel reads GMT.
    timezone: str = os.environ.get("BL_TIMEZONE", "America/Los_Angeles")

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
    cutouts_dir: Path = Path(os.environ.get("BL_CUTOUTS_DIR", str(HERE / "cutouts")))
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
