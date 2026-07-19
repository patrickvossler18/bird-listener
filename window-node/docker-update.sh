#!/usr/bin/env bash
#
# Keep the window-node container images patched.
#
# Run by docker-update.timer (weekly), or by hand:
#     bash window-node/docker-update.sh
#
# Two different policies, on purpose:
#
#   mosquitto (eclipse-mosquitto:2) -- a maintained major-version tag. Upstream
#     publishes security fixes onto it without breaking changes, so pulling it
#     automatically is safe and is the point of this script.
#
#   birdnet-go (pinned to a dated release) -- pinned deliberately. Upstream's
#     :latest and :nightly are the SAME moving, unreviewed build, so neither is
#     a stable channel to auto-follow. A pinned tag is immutable, so `pull` is a
#     no-op for it; this script only REPORTS when a newer release exists and
#     leaves the upgrade as a deliberate edit to docker-compose.yml.
set -euo pipefail

COMPOSE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$COMPOSE_DIR"

echo "==> docker image update check ($(date -Is))"

# 1) Pull anything on a floating tag, recreate only what actually changed -----
docker compose pull
docker compose up -d

# 2) Report (don't apply) a newer birdnet-go release --------------------------
pinned="$(grep -oE 'birdnet-go:[0-9A-Za-z._-]+' docker-compose.yml | head -1 | cut -d: -f2 || true)"
latest="$(curl -fsSL --max-time 20 \
  https://api.github.com/repos/tphakala/birdnet-go/releases/latest 2>/dev/null \
  | grep -oE '"tag_name"[[:space:]]*:[[:space:]]*"[^"]+"' | cut -d'"' -f4 || true)"

if [ -n "$pinned" ] && [ -n "$latest" ] && [ "$pinned" != "$latest" ]; then
  echo "==> NOTICE: birdnet-go is pinned to '$pinned' but '$latest' is available."
  echo "    Review https://github.com/tphakala/birdnet-go/releases then:"
  echo "      sed -i 's|birdnet-go:$pinned|birdnet-go:$latest|' $COMPOSE_DIR/docker-compose.yml"
  echo "      cd $COMPOSE_DIR && docker compose up -d"
elif [ -n "$pinned" ]; then
  echo "==> birdnet-go pinned at '$pinned' (up to date)"
fi

# 3) Reclaim space from superseded layers -------------------------------------
# Only dangling images -- never touches the pinned image still referenced.
docker image prune -f >/dev/null

echo "==> done"
docker compose ps --format '    {{.Name}}\t{{.Image}}\t{{.Status}}'
