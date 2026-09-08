# Window node — bird detection (BirdNET-Go + Mosquitto)

Runs on a **Raspberry Pi 4 or 5** by the window. BirdNET-Go listens to the
USB mic around the clock, identifies species, and publishes detections to
MQTT, which the wall node subscribes to.

> BirdNET-Go needs a Pi 4 or Pi 5; it dropped Pi 3 / Zero 2 W support.

## Install

`birdlistener flash --node window` does all of this on first boot. By hand,
on a Pi running Raspberry Pi OS Lite with SSH:

```bash
sudo cp node.env.example /etc/bird-listener/node.env   # from a checkout; fill it in (BL_NODE=window)
sudo bash install.sh                                     # clones the repo, runs window-node/setup.sh
```

`setup.sh` installs Docker, creates the MQTT user from node.env, starts
BirdNET-Go + Mosquitto, waits for BirdNET-Go to write its config, and patches
in your coordinates, threshold and the MQTT output
(`configure_birdnet.py`). Re-run any time; it only changes what differs.

## Check

```bash
python3 ~/bird-listener/window-node/doctor.py        # docker, containers, mic, config, MQTT auth, last detection
arecord -l                                             # the USB mic should be listed
mosquitto_sub -h localhost -t birdnet/detection -v -u birds -P '<password>'
```

Play a bird call near the mic (or wait for a real one): JSON events appear on
the bus and in the web UI with live spectrograms.

## The web UI

Bound to **loopback only**, so it isn't reachable from the LAN. Tunnel:

```bash
ssh -L 8080:localhost:8080 birdpi     # leave running; browse http://localhost:8080
```

It's closed because the UI answers unauthenticated reads: full config
(secrets masked), system info, detection history, and your coordinates.
Upstream's `security.basicauth` is an OAuth2 flow that expects a domain and
HTTPS, a poor fit for a bare LAN IP, so the tunnel is both stronger and simpler.

## MQTT credentials

The broker requires auth (`allow_anonymous false`): anything on the LAN that
could publish to `birdnet/detection` controls what the wall node displays.
The password is `BL_MQTT_PASS` in node.env on both Pis. Generated, gitignored
files hold it on this node:

| File | Consumed by |
|---|---|
| `mosquitto/passwd` | the broker (hashed, mode 600, uid 1883) |
| `birdnet-go/config/config.yaml` | BirdNET-Go's `realtime.mqtt` block |

To rotate: change `BL_MQTT_PASS` in node.env on both Pis, then
`birdlistener update` (or `bash setup.sh` here and
`sudo systemctl restart bird-display` on the wall node after editing its `.env`).

## Container image updates

`docker-update.sh` (weekly via `docker-update.timer`) patches both images:

- **mosquitto** is on `eclipse-mosquitto:2`, a maintained major tag; a plain
  `docker compose pull` follows it.
- **birdnet-go** is pinned to an immutable dated tag and upgraded by
  *rewriting the pin* from the GitHub releases API. It can't follow a floating
  tag: upstream moves both `:latest` and `:nightly` on every nightly build.

Three rails, since it runs unattended at 04:00 Sunday: a soak period
(`MIN_RELEASE_AGE_DAYS`, default 3), pull before mutate, and a health check
with rollback (`HEALTH_TIMEOUT`, default 180 s). `AUTO_UPGRADE_BIRDNET=false`
reverts to report-only. `journalctl -u docker-update.service` shows what it did.

## Mic notes

- A USB lavalier with its own interface (e.g. the one in the root README) is
  the simplest path: one cable, no sound card.
- Low self-noise matters more than sensitivity. Weatherproof the capsule if it
  sits outside (foam windscreen + drip cover); a powered hub helps on long runs.
- BirdNET-Go's audio source defaults to the system capture device, which is
  the USB mic when it's the only one.
