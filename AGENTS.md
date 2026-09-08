# Notes for agents working in this repo

You are probably helping someone set up or debug their own bird-listener.
Start here; the human-facing overview is README.md.

## What this is

Two Raspberry Pis. The **window node** (Pi 4/5, hostname `birdpi` by default)
runs BirdNET-Go and an MQTT broker in Docker. The **wall node** (Pi Zero 2 W
inside a Waveshare PhotoPainter, hostname `birdwall`) subscribes to
`birdnet/detection` and draws bird cutouts on a 7.3" e-ink panel. Detections
are JSON with `scientificName`, `commonName`, `confidence`, `timestamp`.

## The one tool

`birdlistener` (in `cli/`, stdlib-only Python) runs on the person's computer.
Install with `uv tool install ./cli` or `pipx install ./cli`, or run
`PYTHONPATH=cli python3 -m birdlistener` from the repo root.

| Command | Does | Agent notes |
|---|---|---|
| `flash --node window\|wall` | writes an SD card that installs itself on first boot | every prompt has a flag; `--dry-run` prints the plan and the exact Imager command; `--emit-only` just writes the cloud-init files |
| `doctor [--json]` | runs both nodes' health checks over SSH | start here for any "it doesn't work"; each failing check names the fix |
| `art [--dry-run]` | species list -> seed -> Gemini -> cutouts -> rsync to the wall | dry-run first and tell the person the cost; needs `GEMINI_API_KEY` for the generate step only |
| `update [--rsync]` | pulls latest code on both Pis and re-runs setup | `--rsync` pushes the local checkout instead (for testing changes) |
| `site` | what this computer remembers (hostnames, location; secrets redacted) | file: `~/.config/bird-listener/site.json` |

Non-interactive runs (no TTY, or `BIRDLISTENER_NONINTERACTIVE=1`) never
prompt; a missing answer fails naming the flag to pass.

## Reaching the Pis

`flash` creates `~/.ssh/bird-listener_ed25519` and `Host birdpi` /
`Host birdwall` entries in `~/.ssh/config`, so `ssh birdpi` and
`ssh birdwall` work with no password. Both hosts resolve as `<name>.local`
over mDNS; if that fails the Pi is off, still booting, or on another network.

First boot takes 10-20 minutes. Progress on the Pi:
`/var/log/bird-listener-firstboot.log` and `/var/log/bird-listener-install.log`.

## Where configuration lives

- `/etc/bird-listener/node.env` on each Pi: the deployment contract
  (`node.env.example` documents every key). Written by cloud-init at flash
  time. `install.sh` and both `setup.sh` scripts read it.
- `wall-node/.env` on the wall node: runtime tunables for the display service
  (`wall-node/.env.example`). Created once from node.env; edits persist.
  `wall-node/config.py` lists every knob and its default.
- `window-node/birdnet-go/config/config.yaml` on the window node: BirdNET-Go's
  own config. `window-node/configure_birdnet.py` patches the keys we need
  (coordinates, threshold, MQTT output) from node.env.
- Secrets never go in git: `.env` files, `mosquitto/passwd`, `config.yaml`
  are gitignored. `GEMINI_API_KEY` lives in the repo-root `.env` on the
  person's computer.

## Debugging on the nodes

```bash
ssh birdpi  python3 ~/bird-listener/window-node/doctor.py
ssh birdpi  'cd ~/bird-listener/window-node && docker compose logs --tail 100 birdnet-go'
ssh birdpi  "mosquitto_sub -h localhost -t birdnet/detection -v -u birds -P '<pass>'"
ssh birdwall ~/bird-listener/wall-node/.venv/bin/python ~/bird-listener/wall-node/doctor.py
ssh birdwall journalctl -u bird-display -n 100 --no-pager
```

Fake a detection to test the wall without waiting for a bird (on birdpi):

```bash
mosquitto_pub -h localhost -t birdnet/detection -u birds -P '<pass>' \
  -m '{"scientificName":"Cardinalis cardinalis","commonName":"Northern Cardinal","confidence":0.9}'
```

The display service runs in **mock mode** on any machine without the Pi
libraries: `cd wall-node && python3 display_service.py --once "Cardinalis cardinalis"`
writes `wall-node/out/last_frame.png`. Use this to check rendering changes
before touching the Pi.

## Things that bit us (details in TROUBLESHOOTING.md)

- PhotoPainter routes panel power to BCM27, not the Waveshare default 18.
  Without the `PWR_PIN = 27` patch (applied by `wall-node/setup.sh`) every
  refresh hangs in `ReadBusy()`.
- The panel is mounted upside down relative to the driver: `BL_ROTATE=180`.
- Never connect a battery to the PhotoPainter.
- `PYTHONUNBUFFERED=1` in the unit, or logs never reach `journalctl`.
- BirdNET-Go's range list is for the current week; `art` merges each fetch
  into `tools/kachoe/species.txt` so it only grows.
- The BirdNET-Go UI is loopback-only on purpose (it leaks coordinates to the
  LAN); tunnel with `ssh -L 8080:localhost:8080 birdpi`.

## Don'ts

- Don't run `birdlistener art` without `--dry-run` first; it spends the
  person's Gemini credit.
- Don't commit `.env`, `passwd`, `config.yaml`, `site.json`, or anything under
  `wall-node/cutouts/`, `tools/kachoe/illustrations/`, `tools/kachoe/refs/`.
- Don't bump the BirdNET-Go image tag in `docker-compose.yml` by hand;
  `docker-update.sh` tracks releases with a soak period and rollback.
- `tools/kachoe/` is CC BY-NC-SA (from AvianVisitors); keep the attribution.
