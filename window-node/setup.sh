#!/usr/bin/env bash
#
# Bootstrap the window (detection) node: Docker + BirdNET-Go + Mosquitto, with
# the MQTT user created and BirdNET-Go's config pre-filled (coordinates,
# threshold, MQTT output) so detections flow with no clicking around.
#
# Normally run for you by install.sh (first boot, or `sudo bash install.sh`).
# By hand, ON THE PI, from inside the repo:
#     bash window-node/setup.sh
#
# Settings come from /etc/bird-listener/node.env (see node.env.example), or
# the environment:
#     BL_LATITUDE=37.77 BL_LONGITUDE=-122.44 BL_MQTT_PASS=secret bash window-node/setup.sh
#
# Idempotent: safe to re-run (e.g. after pulling updates).
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE_DIR="$REPO_ROOT/window-node"
NODE_ENV="${BL_NODE_ENV:-/etc/bird-listener/node.env}"
NEED_RELOGIN=0

if [ -f "$NODE_ENV" ]; then
  while IFS='=' read -r k v; do
    case "$k" in ''|\#*) continue ;; esac
    if [ -z "${!k:-}" ]; then export "$k=$v"; fi
  done < "$NODE_ENV"
fi
MQTT_USER="${BL_MQTT_USER:-birds}"
MQTT_PASS="${BL_MQTT_PASS:-}"

echo "==> bird-listener window-node bootstrap"
echo "    repo:    $REPO_ROOT"
echo "    compose: $COMPOSE_DIR"
echo "    coords:  ${BL_LATITUDE:-unset}, ${BL_LONGITUDE:-unset}"

# 1) Docker engine -----------------------------------------------------------
if ! command -v docker >/dev/null 2>&1; then
  echo "==> Installing Docker (get.docker.com convenience script)…"
  curl -fsSL https://get.docker.com | sh
else
  echo "==> Docker already installed: $(docker --version)"
fi

# 2) Run docker without sudo (effective after next login) --------------------
if ! id -nG "$USER" | grep -qw docker; then
  echo "==> Adding '$USER' to the docker group (effective on next login)…"
  sudo usermod -aG docker "$USER"
  NEED_RELOGIN=1
fi

# 3) Compose plugin + helpers ------------------------------------------------
sudo apt-get update
if ! docker compose version >/dev/null 2>&1 && ! sudo docker compose version >/dev/null 2>&1; then
  echo "==> Installing docker compose plugin…"
  sudo apt-get install -y docker-compose-plugin
fi
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y mosquitto-clients python3-yaml alsa-utils curl

# 4) Pick the docker invocation (sudo until the group takes effect) ----------
DOCKER="docker"
if ! docker info >/dev/null 2>&1; then
  DOCKER="sudo docker"
fi

cd "$COMPOSE_DIR"
mkdir -p birdnet-go/config birdnet-go/data mosquitto/data

# 5) MQTT credentials --------------------------------------------------------
# The broker requires auth: anything on the LAN that can publish to the
# detection topic controls what the wall node shows. The hashed password file
# must exist before `compose up`, or Docker creates a directory in its place.
PASSWD="$COMPOSE_DIR/mosquitto/passwd"
if [ -d "$PASSWD" ]; then sudo rm -rf "$PASSWD"; fi
if [ -z "$MQTT_PASS" ]; then
  if [ -f "$PASSWD" ]; then
    echo "==> Keeping existing $PASSWD (no BL_MQTT_PASS given)"
  else
    MQTT_PASS="$(tr -dc 'A-Za-z0-9' </dev/urandom | head -c 24)"
    echo "==> No BL_MQTT_PASS given; generated one. The wall node needs it too:"
    echo "    BL_MQTT_PASS=$MQTT_PASS"
  fi
fi
if [ -n "$MQTT_PASS" ]; then
  echo "==> Writing MQTT user '$MQTT_USER' to $PASSWD"
  $DOCKER run --rm -v "$COMPOSE_DIR/mosquitto:/m" eclipse-mosquitto:2 \
    sh -c "mosquitto_passwd -b -c /m/passwd '$MQTT_USER' '$MQTT_PASS' && chown 1883:1883 /m/passwd && chmod 600 /m/passwd"
fi

# 6) Bring up the stack ------------------------------------------------------
echo "==> Starting BirdNET-Go + Mosquitto…"
$DOCKER compose up -d

# 7) Pre-fill BirdNET-Go's config --------------------------------------------
# BirdNET-Go writes a complete config.yaml on first start; wait for it, then
# patch in coordinates, threshold, and the MQTT output. On re-runs this is a
# no-op unless node.env changed.
CONFIG="$COMPOSE_DIR/birdnet-go/config/config.yaml"
for i in $(seq 1 24); do
  [ -s "$CONFIG" ] && break
  echo "    waiting for BirdNET-Go to write config.yaml ($i)…"; sleep 5
done
if [ -s "$CONFIG" ]; then
  echo "==> Applying settings to $CONFIG"
  if sudo -n true 2>/dev/null; then WRITE="sudo"; else WRITE=""; fi
  # The container owns /config; patch via a temp copy we can write.
  TMP="$(mktemp)"; cp "$CONFIG" "$TMP"
  if python3 "$COMPOSE_DIR/configure_birdnet.py" --config "$TMP" --node-env "$NODE_ENV" \
       ${MQTT_PASS:+--mqtt-pass "$MQTT_PASS"} --mqtt-user "$MQTT_USER" | tee /tmp/configure_birdnet.out; then
    if grep -q '^updated' /tmp/configure_birdnet.out; then
      sudo cp "$TMP" "$CONFIG"
      $DOCKER compose restart birdnet-go
    fi
  fi
  rm -f "$TMP"
else
  echo "!! config.yaml never appeared; check: $DOCKER compose logs birdnet-go" >&2
fi

# 8) Weekly image updates ----------------------------------------------------
if [ -f "$COMPOSE_DIR/docker-update.service" ]; then
  sed "s|/home/pi/bird-listener|$REPO_ROOT|g; s|User=pi|User=$USER|" \
    "$COMPOSE_DIR/docker-update.service" | sudo tee /etc/systemd/system/docker-update.service >/dev/null
  sudo cp "$COMPOSE_DIR/docker-update.timer" /etc/systemd/system/docker-update.timer
  sudo systemctl daemon-reload
  sudo systemctl enable --now docker-update.timer
fi

$DOCKER compose ps
cat <<EOT

==> Stack is up. Next:
  1. Plug in the USB mic (if not already) and confirm it's seen:  arecord -l
  2. Health report:  python3 $COMPOSE_DIR/doctor.py
  3. Watch detections:
       mosquitto_sub -h localhost -t birdnet/detection -v -u $MQTT_USER -P '<password>'
  4. Web UI (loopback only; tunnel from your computer):
       ssh -L 8080:localhost:8080 $USER@$(hostname).local   ->  http://localhost:8080
EOT
if [ "$NEED_RELOGIN" = "1" ]; then
  echo "NOTE: log out and back in (or run 'newgrp docker') to use docker without sudo."
fi
