#!/usr/bin/env bash
#
# Bootstrap the wall (display) node: a Raspberry Pi Zero 2 W (or original
# Zero W) inside the Waveshare PhotoPainter frame. Enables SPI/I2C, installs
# the Waveshare e-Paper driver + Python deps, writes wall-node/.env, and
# installs the bird-display systemd service.
#
# Normally run for you by install.sh (first boot, or `sudo bash install.sh`).
# By hand, ON THE PI, from inside the repo:
#     bash wall-node/setup.sh
#
# Settings come from, in order: /etc/bird-listener/node.env (see
# node.env.example), then environment variables, e.g.
#     BL_MQTT_HOST=birdpi.local BL_MQTT_PASS=secret bash wall-node/setup.sh
#
# Idempotent: safe to re-run after pulling updates. An existing wall-node/.env
# is kept as is.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WALL_DIR="$REPO_ROOT/wall-node"
EPAPER_DIR="$HOME/e-Paper"
NODE_ENV="${BL_NODE_ENV:-/etc/bird-listener/node.env}"

if [ -f "$NODE_ENV" ]; then
  # Environment already set in the shell wins over the file.
  while IFS='=' read -r k v; do
    case "$k" in ''|\#*) continue ;; esac
    if [ -z "${!k:-}" ]; then export "$k=$v"; fi
  done < "$NODE_ENV"
fi
MQTT_HOST="${BL_MQTT_HOST:-birdpi.local}"
MQTT_USER="${BL_MQTT_USER:-birds}"
MQTT_PASS="${BL_MQTT_PASS:-}"
ROTATE="${BL_ROTATE:-180}"
TIMEZONE="${BL_TIMEZONE:-}"

echo "==> bird-listener wall-node bootstrap"
echo "    repo:      $REPO_ROOT"
echo "    MQTT host: $MQTT_HOST (user $MQTT_USER)"
echo "    arch:      $(uname -m)"

# 1) Interfaces (SPI for the panel, I2C for the optional BH1750) ------------
echo "==> Enabling SPI and I2C…"
sudo raspi-config nonint do_spi 0
sudo raspi-config nonint do_i2c 0

# 2) System packages ---------------------------------------------------------
echo "==> Installing apt packages…"
sudo apt-get update
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y git python3-venv python3-pip \
  python3-dev libopenjp2-7 libfreetype6 fonts-dejavu i2c-tools rsync

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
#     ReadBusy(). Patch the cloned driver (idempotent).
EPD_CONFIG="$EPD_LIB/waveshare_epd/epdconfig.py"
if grep -q 'PWR_PIN  = 18' "$EPD_CONFIG"; then
  echo "==> Patching e-Paper PWR_PIN 18 -> 27 (RPi Zero PhotoPainter board)…"
  sed -i 's/PWR_PIN  = 18/PWR_PIN  = 27/' "$EPD_CONFIG"
fi

# 4) Python venv (system-site-packages so it can see spidev/lgpio/gpiozero) ---
#    Raspberry Pi OS points pip at piwheels, so numpy/Pillow install as
#    prebuilt wheels on both arm64 and the original Zero W's armv6.
echo "==> Creating venv + installing Python deps…"
cd "$WALL_DIR"
python3 -m venv --system-site-packages .venv
./.venv/bin/pip install --upgrade pip
./.venv/bin/pip install -r requirements.txt smbus2 spidev gpiozero lgpio

# 5) Runtime settings file ---------------------------------------------------
if [ -f "$WALL_DIR/.env" ]; then
  echo "==> Keeping existing $WALL_DIR/.env"
else
  echo "==> Writing $WALL_DIR/.env"
  if [ -z "$MQTT_PASS" ]; then
    echo "!! BL_MQTT_PASS is not set; writing a placeholder. Edit $WALL_DIR/.env" >&2
    echo "   with the window node's MQTT password, then: sudo systemctl restart bird-display" >&2
    MQTT_PASS="change-me"
  fi
  sed -e "s|^BL_MQTT_HOST=.*|BL_MQTT_HOST=$MQTT_HOST|" \
      -e "s|^BL_MQTT_USER=.*|BL_MQTT_USER=$MQTT_USER|" \
      -e "s|^BL_MQTT_PASS=.*|BL_MQTT_PASS=$MQTT_PASS|" \
      -e "s|^BL_ROTATE=.*|BL_ROTATE=$ROTATE|" \
      -e "s|^BL_TIMEZONE=.*|BL_TIMEZONE=$TIMEZONE|" \
      "$WALL_DIR/.env.example" > "$WALL_DIR/.env"
  chmod 600 "$WALL_DIR/.env"
fi
mkdir -p "$WALL_DIR/cutouts" "$WALL_DIR/images" "$WALL_DIR/out"

# 6) systemd service ---------------------------------------------------------
SERVICE=/etc/systemd/system/bird-display.service
echo "==> Installing systemd service ($SERVICE)…"
sudo tee "$SERVICE" >/dev/null <<UNIT
[Unit]
Description=Bird Listener wall-node e-ink display service
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$USER
WorkingDirectory=$WALL_DIR
# All tunables live in wall-node/.env (see .env.example).
EnvironmentFile=$WALL_DIR/.env
# Unbuffer Python stdout so [detect]/[render] logs reach the journal live.
Environment=PYTHONUNBUFFERED=1
Environment=PYTHONPATH=$EPD_LIB
ExecStart=$WALL_DIR/.venv/bin/python display_service.py
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
UNIT

sudo systemctl daemon-reload
sudo systemctl enable bird-display
# Start (or restart, to pick up code/config changes) unless asked not to.
if [ "${BL_NO_START:-0}" != "1" ]; then
  sudo systemctl restart bird-display
fi

cat <<EOT

==> Done. Useful checks:
      $WALL_DIR/.venv/bin/python $WALL_DIR/doctor.py        # health report
      journalctl -u bird-display -f                          # live log
    Render one bird to the panel without waiting for a detection:
      sudo systemctl stop bird-display
      cd $WALL_DIR && PYTHONPATH=$EPD_LIB ./.venv/bin/python display_service.py --once "Cardinalis cardinalis"
      sudo systemctl start bird-display
    Art: the panel needs cutouts in $WALL_DIR/cutouts/ -- run
      \`birdlistener art\` on your computer to build and sync them.
EOT
