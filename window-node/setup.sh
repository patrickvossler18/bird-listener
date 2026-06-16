#!/usr/bin/env bash
#
# Bootstrap the window (detection) node: Docker + BirdNET-Go + Mosquitto.
#
# Run ON THE PI, from inside the repo:
#     bash window-node/setup.sh
#
# Idempotent: safe to re-run (e.g. after pulling updates). It installs Docker if
# missing, adds you to the docker group, and brings the stack up.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE_DIR="$REPO_ROOT/window-node"
NEED_RELOGIN=0

echo "==> bird-listener window-node bootstrap"
echo "    repo:    $REPO_ROOT"
echo "    compose: $COMPOSE_DIR"

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

# 3) Compose plugin ----------------------------------------------------------
if ! docker compose version >/dev/null 2>&1 && ! sudo docker compose version >/dev/null 2>&1; then
  echo "==> Installing docker compose plugin…"
  sudo apt-get update && sudo apt-get install -y docker-compose-plugin
fi

# 4) mosquitto-clients for debugging the MQTT bus ----------------------------
if ! command -v mosquitto_sub >/dev/null 2>&1; then
  echo "==> Installing mosquitto-clients (for mosquitto_sub/pub)…"
  sudo apt-get update && sudo apt-get install -y mosquitto-clients
fi

# 5) Pick the docker invocation (sudo until the group takes effect) ----------
DOCKER="docker"
if ! docker info >/dev/null 2>&1; then
  DOCKER="sudo docker"
fi

# 6) Bring up the stack ------------------------------------------------------
echo "==> Starting BirdNET-Go + Mosquitto…"
cd "$COMPOSE_DIR"
$DOCKER compose up -d
$DOCKER compose ps

cat <<EOF

==> Stack is up. Next steps:
  1. Plug in the USB sound card + mic, then confirm it's seen:
         arecord -l
  2. Open the BirdNET-Go web UI:
         http://birdpi.local:8080
     Set your latitude/longitude + confidence threshold, and enable the MQTT
     output (broker tcp://mosquitto:1883, topic birdnet/detection). Reference:
         window-node/birdnet-go/config/config.yaml.template
     Then restart it to apply:
         $DOCKER compose restart birdnet-go
  3. Watch detections flow onto the bus:
         mosquitto_sub -h localhost -t birdnet/detection -v
EOF

if [ "$NEED_RELOGIN" = "1" ]; then
  echo
  echo "NOTE: log out and back in (or run 'newgrp docker') to use docker without sudo."
fi
