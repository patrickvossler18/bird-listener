# Window node — bird detection (BirdNET-Go + Mosquitto)

Runs on the **Raspberry Pi 4** (or Pi 5) by the window. BirdNET-Go listens to
the USB mic 24/7, identifies species, and publishes detections to MQTT, which
the wall node subscribes to.

> BirdNET-Go needs a Pi 4 or Pi 5 — it dropped Pi 3 / Zero 2 W support.

## Setup

1. Plug in the USB sound card + mic. Confirm it's seen: `arecord -l`.
2. Bring the stack up:
   ```bash
   cd window-node
   docker compose up -d
   ```
   This starts **BirdNET-Go** (web UI at `http://<pi>:8080`) and **Mosquitto**
   (MQTT on `:1883`).
3. Configure detection + MQTT output. BirdNET-Go generates
   `birdnet-go/config/config.yaml` on first run — edit it (or use the web UI →
   Settings) to set your **latitude/longitude**, **threshold**, and enable the
   **MQTT** output. See `birdnet-go/config/config.yaml.template` for the exact
   keys (broker `tcp://mosquitto:1883`, topic `birdnet/detection`).
4. Restart BirdNET-Go to pick up config changes: `docker compose restart birdnet-go`.

## Verify

Watch detections flow onto the bus (install `mosquitto-clients` or use the
container):

```bash
mosquitto_sub -h localhost -t birdnet/detection -v
# or:  docker exec -it mosquitto mosquitto_sub -t birdnet/detection -v
```

Play a bird call near the mic (or wait for a real one) — you should see JSON
events appear, and they should also show in the BirdNET-Go web UI with live
spectrograms.

## Networking

Give this Pi a stable hostname (e.g. `birdpi.local` via mDNS) or a static DHCP
lease so the wall node's `BL_MQTT_HOST` stays valid across reboots.

## Mic notes

- Recommended: omnidirectional electret/lavalier (e.g. Boya BY-LM40) on a
  CM108-based USB sound card; low self-noise matters more than sensitivity.
- Weatherproof the capsule if it sits outside (foam windscreen + drip cover);
  use a powered USB hub if the cable run is long.
