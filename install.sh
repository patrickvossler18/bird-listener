#!/usr/bin/env bash
#
# One-shot node installer. Reads /etc/bird-listener/node.env, makes sure the
# repo is checked out in the login user's home, and runs that node's setup.
#
# Called two ways:
#   * automatically on first boot, by the cloud-init that `birdlistener flash`
#     writes to the SD card (runs as root, logs to /var/log/bird-listener-install.log)
#   * by hand on a Pi you set up yourself:
#         sudo bash install.sh            # after writing /etc/bird-listener/node.env
#
# Idempotent: re-running pulls the latest code and re-applies setup.
set -euo pipefail

NODE_ENV="${BL_NODE_ENV:-/etc/bird-listener/node.env}"
LOG=/var/log/bird-listener-install.log

if [ "$(id -u)" -ne 0 ]; then
  echo "install.sh must run as root (sudo bash install.sh)" >&2
  exit 1
fi
if [ ! -f "$NODE_ENV" ]; then
  echo "missing $NODE_ENV -- copy node.env.example there and fill it in" >&2
  exit 1
fi

# shellcheck disable=SC1090
set -a; . "$NODE_ENV"; set +a
: "${BL_NODE:?BL_NODE must be 'window' or 'wall'}"
BL_REPO_URL="${BL_REPO_URL:-https://github.com/patrickvossler18/bird-listener.git}"
BL_REPO_REF="${BL_REPO_REF:-main}"

# The unprivileged user that owns the checkout and runs the services: the
# first regular account (cloud-init's user, normally "pi").
RUN_USER="${BL_USER:-$(awk -F: '$3>=1000 && $3<60000 {print $1; exit}' /etc/passwd)}"
RUN_HOME="$(getent passwd "$RUN_USER" | cut -d: -f6)"
REPO_DIR="$RUN_HOME/bird-listener"

exec > >(tee -a "$LOG") 2>&1
echo "==> bird-listener install ($(date -Is)) node=$BL_NODE user=$RUN_USER repo=$REPO_DIR"

chmod 600 "$NODE_ENV" || true

# 1) Wait for the network: first boot can reach here before DNS is usable.
for i in $(seq 1 30); do
  if getent hosts github.com >/dev/null 2>&1; then break; fi
  echo "    waiting for network ($i)…"; sleep 5
done

# 2) Base packages every node needs.
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y git avahi-daemon

# 3) Code checkout (as the run user, so later `git pull` works without sudo).
if [ -d "$REPO_DIR/.git" ]; then
  echo "==> updating $REPO_DIR"
  sudo -u "$RUN_USER" git -C "$REPO_DIR" fetch --quiet origin
  sudo -u "$RUN_USER" git -C "$REPO_DIR" checkout --quiet "$BL_REPO_REF"
  sudo -u "$RUN_USER" git -C "$REPO_DIR" pull --quiet --ff-only origin "$BL_REPO_REF" || true
elif [ -d "$REPO_DIR" ]; then
  echo "==> $REPO_DIR exists without .git (rsync deployment); leaving it as is"
else
  echo "==> cloning $BL_REPO_URL ($BL_REPO_REF)"
  sudo -u "$RUN_USER" git clone --quiet --branch "$BL_REPO_REF" "$BL_REPO_URL" "$REPO_DIR"
fi

# 4) Node setup. The setup scripts expect to run as the login user and use
#    sudo internally; root's sudo never prompts, and neither does a
#    cloud-init user (NOPASSWD), so this works on first boot and by hand.
case "$BL_NODE" in
  window) SETUP="$REPO_DIR/window-node/setup.sh" ;;
  wall)   SETUP="$REPO_DIR/wall-node/setup.sh" ;;
  *) echo "BL_NODE='$BL_NODE' is not 'window' or 'wall'" >&2; exit 1 ;;
esac
sudo -u "$RUN_USER" -H env BL_NODE_ENV="$NODE_ENV" bash "$SETUP"

# 5) Unattended security updates on every node.
sudo -u "$RUN_USER" -H bash "$REPO_DIR/auto-updates.sh" || echo "!! auto-updates.sh failed (non-fatal)"

echo "==> install complete ($(date -Is))"
