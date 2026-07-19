# Window node — bird detection (BirdNET-Go + Mosquitto)

Runs on the **Raspberry Pi 4** (or Pi 5) by the window. BirdNET-Go listens to
the USB mic 24/7, identifies species, and publishes detections to MQTT, which
the wall node subscribes to.

> BirdNET-Go needs a Pi 4 or Pi 5 — it dropped Pi 3 / Zero 2 W support.

## Setup

### 0. Get the code onto the Pi

The repo is private, so rather than cloning (which needs GitHub creds on the Pi)
just copy it from your Mac over SSH — no credentials needed:

```bash
# from the repo root on your Mac:
rsync -av --delete \
  --exclude '.git' --exclude '*/.venv' --exclude '*/out' \
  --exclude '__pycache__' --exclude '*/data' \
  ./ pi@birdpi.local:~/bird-listener/
```

(Re-run that anytime to push updates. Alternatively, generate a GitHub token and
`git clone` on the Pi.)

### 1. Bootstrap (one command)

SSH in and run the bootstrap — it installs Docker, adds you to the docker group,
installs `mosquitto-clients`, and brings the stack up:

```bash
ssh pi@birdpi.local
cd ~/bird-listener
bash window-node/setup.sh
```

This starts **BirdNET-Go** (web UI at `http://birdpi.local:8080`) and
**Mosquitto** (MQTT on `:1883`). Log out/in once afterward so `docker` works
without `sudo`.

### 2. Configure detection + MQTT output

1. Plug in the USB sound card + mic. Confirm it's seen: `arecord -l`.
2. BirdNET-Go generates `birdnet-go/config/config.yaml` on first run — edit it
   (or use the web UI → Settings) to set your **latitude/longitude**,
   **threshold**, and enable the **MQTT** output. See
   `birdnet-go/config/config.yaml.template` for the exact keys (broker
   `tcp://mosquitto:1883`, topic `birdnet/detection`).
3. Restart BirdNET-Go to pick up config changes:
   `docker compose restart birdnet-go`.

## Verify

Watch detections flow onto the bus (install `mosquitto-clients` or use the
container):

```bash
mosquitto_sub -h localhost -t birdnet/detection -v -u birds -P "$(grep BL_MQTT_PASS ~/bird-listener/wall-node/.env | cut -d= -f2)"
# or:  docker exec -it mosquitto mosquitto_sub -t birdnet/detection -v -u birds -P '<password>'
```

Play a bird call near the mic (or wait for a real one) — you should see JSON
events appear, and they should also show in the BirdNET-Go web UI with live
spectrograms.

## MQTT credentials

The broker requires auth (`allow_anonymous false`) — anything on the LAN that
could publish to `birdnet/detection` controls what the wall node displays.

Credentials live in generated, gitignored files, one per node:

| Node | File | Consumed by |
|---|---|---|
| birdpi | `window-node/mosquitto/passwd` | the broker (hashed, mode 600, uid 1883) |
| birdpi | `window-node/birdnet-go/config/config.yaml` | BirdNET-Go's `realtime.mqtt` block |
| birdwall | `wall-node/.env` | `bird-display.service` via `EnvironmentFile` |

To rotate, update all three and restart both services:

```bash
docker exec -it mosquitto mosquitto_passwd -b /mosquitto/config/passwd birds NEWPASS
# edit realtime.mqtt.password in birdnet-go/config/config.yaml, then:
docker compose restart mosquitto birdnet-go
# on birdwall: edit wall-node/.env, then sudo systemctl restart bird-display
```

## Container image updates

`docker-update.sh` (weekly via `docker-update.timer`) pulls floating tags and
recreates what changed. Two deliberate policies:

- **mosquitto** is on `eclipse-mosquitto:2`, a maintained major tag — patched
  automatically.
- **birdnet-go** is pinned to a dated release. Upstream's `:latest` and
  `:nightly` are the *same* moving, unreviewed build, so neither is a stable
  channel to follow. The script only *reports* when a newer release exists;
  bumping the tag in `docker-compose.yml` stays a deliberate act.

## Networking

Give this Pi a stable hostname (e.g. `birdpi.local` via mDNS) or a static DHCP
lease so the wall node's `BL_MQTT_HOST` stays valid across reboots.

## Mic notes

- Recommended: omnidirectional electret/lavalier (e.g. Boya BY-LM40) on a
  CM108-based USB sound card; low self-noise matters more than sensitivity.
- Weatherproof the capsule if it sits outside (foam windscreen + drip cover);
  use a powered USB hub if the cable run is long.
