#!/usr/bin/env bash
#
# Bootstrap the wall (display) node on a Raspberry Pi Zero 2 W in the Waveshare
# RPi-Zero-PhotoPainter: enable SPI/I2C, install the Waveshare e-Paper driver +
# Python deps, and install the systemd service that renders detections.
#
# Run ON THE PI ZERO, from inside the repo:
#     bash wall-node/setup.sh
#
# Point it at the detection node with BL_MQTT_HOST (defaults to birdpi's IP):
#     BL_MQTT_HOST=192.168.4.107 bash wall-node/setup.sh
#
# Idempotent: safe to re-run after pulling updates.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WALL_DIR="$REPO_ROOT/wall-node"
EPAPER_DIR="$HOME/e-Paper"
MQTT_HOST="${BL_MQTT_HOST:-192.168.4.107}"   # detection node (birdpi)

echo "==> bird-listener wall-node bootstrap"
echo "    repo:      $REPO_ROOT"
echo "    MQTT host: $MQTT_HOST"

# 1) Interfaces (SPI for the panel, I2C for the BH1750 light sensor) ----------
echo "==> Enabling SPI and I2C…"
sudo raspi-config nonint do_spi 0
sudo raspi-config nonint do_i2c 0

# 2) System packages ---------------------------------------------------------
echo "==> Installing apt packages…"
sudo apt-get update
sudo apt-get install -y git python3-venv python3-pip python3-dev \
  libopenjp2-7 libfreetype6 fonts-dejavu i2c-tools

# 3) Waveshare e-Paper driver library ----------------------------------------
if [ ! -d "$EPAPER_DIR" ]; then
  echo "==> Cloning Waveshare e-Paper library…"
  git clone --depth 1 https://github.com/waveshareteam/e-Paper "$EPAPER_DIR"
else
  echo "==> Updating Waveshare e-Paper library…"
  git -C "$EPAPER_DIR" pull --ff-only || true
fi
EPD_LIB="$EPAPER_DIR/RaspberryPi_JetsonNano/python/lib"

# 3b) PhotoPainter board quirk: it routes the e-paper power-enable to BCM27, not
#     the HAT-default BCM18 (per the RPi Zero PhotoPainter manual). With the stock
#     driver, module_init() powers the wrong pin and EVERY refresh hangs forever in
#     ReadBusy(). Patch the freshly-cloned driver (idempotent).
EPD_CONFIG="$EPD_LIB/waveshare_epd/epdconfig.py"
if grep -q 'PWR_PIN  = 18' "$EPD_CONFIG"; then
  echo "==> Patching e-Paper PWR_PIN 18 -> 27 (RPi Zero PhotoPainter board)…"
  sed -i 's/PWR_PIN  = 18/PWR_PIN  = 27/' "$EPD_CONFIG"
fi

# 4) Python venv (system-site-packages so it can see spidev/lgpio/gpiozero) ---
echo "==> Creating venv + installing Python deps…"
cd "$WALL_DIR"
python3 -m venv --system-site-packages .venv
./.venv/bin/pip install --upgrade pip
./.venv/bin/pip install -r requirements.txt smbus2 spidev gpiozero lgpio

# 5) systemd service ---------------------------------------------------------
SERVICE=/etc/systemd/system/bird-display.service
echo "==> Installing systemd service ($SERVICE)…"
sudo tee "$SERVICE" >/dev/null <<EOF
[Unit]
Description=Bird Listener wall-node e-ink display service
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$USER
WorkingDirectory=$WALL_DIR
Environment=BL_MQTT_HOST=$MQTT_HOST
Environment=BL_MIN_CONFIDENCE=0.65
Environment=BL_MAX_BIRDS=4
Environment=BL_MULTI_WINDOW_SECONDS=900
Environment=BL_MIN_REFRESH_SECONDS=30
Environment=BL_ROTATE=180
Environment=BL_SHARPEN=0.8
Environment=BL_CAPTION_SCALE=1.5
Environment=PYTHONPATH=$EPD_LIB
ExecStart=$WALL_DIR/.venv/bin/python display_service.py
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable bird-display

cat <<EOF

==> Done. Before starting the service, smoke-test a render to the panel:
      PYTHONPATH=$EPD_LIB ./.venv/bin/python display_service.py --once "Cardinalis cardinalis"
    Check the light sensor is on the I2C bus (expect 0x23):
      i2cdetect -y 1
    Then run the service:
      sudo systemctl start bird-display
      journalctl -u bird-display -f
EOF
