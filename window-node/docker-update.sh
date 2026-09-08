#!/usr/bin/env bash
#
# Keep the window-node container images patched.
#
# Run by docker-update.timer (weekly), or by hand:
#     bash window-node/docker-update.sh
#     AUTO_UPGRADE_BIRDNET=false bash window-node/docker-update.sh   # report only
#
# Two different mechanisms, because the two images differ:
#
#   mosquitto (eclipse-mosquitto:2) -- a maintained major-version tag. Upstream
#     publishes security fixes onto it without breaking changes, so a plain
#     `docker compose pull` is the right way to follow it.
#
#   birdnet-go -- pinned to an immutable dated release tag, and upgraded by
#     REWRITING that pin, not by following a floating tag. Upstream's :latest
#     and :nightly are both moved by every nightly build (nightly-build.yml and
#     release-build.yml each pass create-latest-tag: true), so neither is a
#     release-only channel. The GitHub releases API is. This script follows the
#     releases API, so it tracks releases and never a nightly build.
#
# Safety rails on the birdnet-go upgrade: a soak period so we never take a
# release on its publication day, a pull before any config change, and a health
# check with automatic rollback to the previous tag if the new one comes up
# unhealthy.
set -euo pipefail

COMPOSE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$COMPOSE_DIR"

REPO="tphakala/birdnet-go"
# Set false to go back to report-only (the upgrade is then a manual tag edit).
AUTO_UPGRADE_BIRDNET="${AUTO_UPGRADE_BIRDNET:-true}"
# Let a release sit this long before taking it, so a bad one has time to be
# pulled or superseded before it reaches a box with a mic in the house.
MIN_RELEASE_AGE_DAYS="${MIN_RELEASE_AGE_DAYS:-3}"
# How long to wait for the new container to report healthy before rolling back.
HEALTH_TIMEOUT="${HEALTH_TIMEOUT:-180}"

echo "==> docker image update check ($(date -Is))"

# 1) Follow floating tags (mosquitto) ----------------------------------------
docker compose pull
docker compose up -d

# 2) birdnet-go: follow the releases API, not a docker tag --------------------
pinned="$(grep -oE 'birdnet-go:[0-9A-Za-z._-]+' docker-compose.yml | head -1 | cut -d: -f2 || true)"
release_json="$(curl -fsSL --max-time 30 \
  "https://api.github.com/repos/$REPO/releases/latest" 2>/dev/null || true)"
latest="$(printf '%s' "$release_json" \
  | grep -oE '"tag_name"[[:space:]]*:[[:space:]]*"[^"]+"' | cut -d'"' -f4 || true)"
published="$(printf '%s' "$release_json" \
  | grep -oE '"published_at"[[:space:]]*:[[:space:]]*"[^"]+"' | cut -d'"' -f4 || true)"

upgrade_birdnet() {
  local from="$1" to="$2"

  # Pull first: if this fails we have changed nothing.
  echo "    pulling $REPO:$to …"
  if ! docker pull -q "ghcr.io/$REPO:$to" >/dev/null 2>&1; then
    echo "    !! pull failed; staying on '$from'"
    return 1
  fi

  cp docker-compose.yml docker-compose.yml.bak-"$from"
  sed -i "s|birdnet-go:${from}|birdnet-go:${to}|" docker-compose.yml
  docker compose up -d --no-deps birdnet-go

  # Wait for the container's own healthcheck to go green.
  local waited=0
  while [ "$waited" -lt "$HEALTH_TIMEOUT" ]; do
    local state
    state="$(docker inspect birdnet-go --format '{{.State.Health.Status}}' 2>/dev/null || echo unknown)"
    case "$state" in
      healthy)
        echo "==> upgraded birdnet-go $from -> $to (healthy after ${waited}s)"
        rm -f docker-compose.yml.bak-"$from"
        return 0 ;;
      unhealthy)
        break ;;
    esac
    sleep 5
    waited=$((waited + 5))
  done

  echo "    !! '$to' did not become healthy in ${HEALTH_TIMEOUT}s -- rolling back to '$from'"
  mv docker-compose.yml.bak-"$from" docker-compose.yml
  docker compose up -d --no-deps birdnet-go
  return 1
}

if [ -z "$pinned" ] || [ -z "$latest" ]; then
  echo "==> birdnet-go: could not determine pinned/latest version; skipping"
elif [ "$pinned" = "$latest" ]; then
  echo "==> birdnet-go at '$pinned' (current release)"
elif [ "$AUTO_UPGRADE_BIRDNET" != "true" ]; then
  echo "==> NOTICE: birdnet-go pinned '$pinned', release '$latest' available (auto-upgrade off)"
else
  # Soak period. `date -d` is GNU date; both nodes are Debian-family.
  age_days=-1
  if [ -n "$published" ]; then
    pub_epoch="$(date -d "$published" +%s 2>/dev/null || echo 0)"
    [ "$pub_epoch" -gt 0 ] && age_days=$(( ( $(date +%s) - pub_epoch ) / 86400 ))
  fi

  if [ "$age_days" -lt 0 ]; then
    echo "==> birdnet-go: '$latest' available but its age is unknown; not upgrading"
  elif [ "$age_days" -lt "$MIN_RELEASE_AGE_DAYS" ]; then
    echo "==> birdnet-go: holding '$latest' (${age_days}d old, soak is ${MIN_RELEASE_AGE_DAYS}d)"
  else
    echo "==> birdnet-go: '$latest' is ${age_days}d old, upgrading from '$pinned'"
    upgrade_birdnet "$pinned" "$latest" || true
  fi
fi

# 3) Reclaim space from superseded layers -------------------------------------
docker image prune -f >/dev/null

echo "==> done"
docker compose ps --format '    {{.Name}}\t{{.Image}}\t{{.Status}}'
