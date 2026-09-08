# Wall node — framed e-ink display

Runs on the **Raspberry Pi Zero 2 W** inside the Waveshare PhotoPainter.
Subscribes to BirdNET-Go detections over MQTT and refreshes the 7.3" E6 panel
with a kachō-e cutout collage of the birds heard recently (or the legacy
Audubon plate mode).

## Install

`birdlistener flash --node wall` does all of this on first boot. By hand, on
a Pi running Raspberry Pi OS Lite with SSH:

```bash
sudo cp node.env.example /etc/bird-listener/node.env   # from a checkout; fill it in (BL_NODE=wall)
sudo bash install.sh                                     # clones the repo, runs wall-node/setup.sh
```

`setup.sh` enables SPI/I2C, clones the Waveshare e-Paper library and patches
it for this board, creates the venv, writes `.env` from node.env, and installs
the `bird-display` systemd service. Re-run it any time; it's idempotent.

> **PhotoPainter PWR-pin quirk:** this board routes the e-paper power-enable
> to **BCM27**, not the HAT-default **BCM18**. With the stock Waveshare
> driver every panel refresh hangs forever in `ReadBusy()`. `setup.sh`
> patches the cloned driver (`waveshare_epd/epdconfig.py`, `PWR_PIN = 27`).
> Source: Waveshare RPi Zero PhotoPainter manual, Hardware Connection.

## Configure

All runtime settings are in `wall-node/.env` (see `.env.example`), read by the
service through `EnvironmentFile=`. Edit, then
`sudo systemctl restart bird-display`. `config.py` documents every knob:

```bash
BL_MQTT_HOST=birdpi.local        # the window node
BL_MQTT_USER=birds
BL_MQTT_PASS=...                 # same as the window node's
BL_ROTATE=180                    # panel is mounted upside down in the frame
BL_MIN_CONFIDENCE=0.65
BL_MAX_BIRDS=4                   # collage of up to 4 recent birds (1 = single)
BL_MULTI_WINDOW_SECONDS=900      # birds heard within 15 min are grouped
BL_MIN_REFRESH_SECONDS=30        # protect the slow panel from rapid redraws
BL_ART_MODE=collage              # or "plates" for Audubon plates
BL_LIGHT_GATE=0                  # 1 with a BH1750: blank when the room is dark
```

### Collage

Detections within `BL_MULTI_WINDOW_SECONDS` are grouped. Transparent cutouts
from `cutouts/` (built by `birdlistener art`) are nested into an organic
cluster, newest bird largest, with an optional name strip
(`BL_COLLAGE_NAMES=0` to hide). The panel only refreshes when the *set* of
recent birds changes, never faster than `BL_MIN_REFRESH_SECONDS`. Species with
no cutout show as a name card. `BL_ART_MODE=plates` restores the Audubon-plate
row layout from `images/` (`tools/fetch_plates.py`).

## Run

```bash
./.venv/bin/python display_service.py                       # service loop
./.venv/bin/python display_service.py --once "Cardinalis cardinalis"   # one bird
./.venv/bin/python display_service.py --once "Cardinalis cardinalis" "Cyanocitta cristata"  # collage
./.venv/bin/python display_service.py --clear               # blank the panel
./.venv/bin/python doctor.py                                # health report (--json)
```

On a machine without the Waveshare/BH1750 libraries (your laptop) it runs in
**mock mode**: frames go to `out/last_frame.png` and the room is assumed lit.
Force mock on the Pi with `BL_FORCE_MOCK_DISPLAY=1` / `BL_FORCE_MOCK_LIGHT=1`.

Service: `sudo systemctl status bird-display`, `journalctl -u bird-display -f`.

## Files

| File | Purpose |
|------|---------|
| `display_service.py` | MQTT subscriber, grouping window, light gate, orchestration |
| `renderer.py`        | Collage packer + plate compositor, dither to the Spectra-6 palette |
| `display_driver.py`  | Waveshare `epd7in3e` driver + mock PNG driver |
| `light_sensor.py`    | BH1750 read with on/off hysteresis (+ mock) |
| `localtime.py`       | Detection timestamp -> local caption clock |
| `config.py`          | Every setting, from environment variables |
| `doctor.py`          | Health checks (settings, service, panel, MQTT auth, art, last render) |
| `setup.sh`           | Idempotent installer |
| `.env.example`       | Runtime settings template |
| `cutouts/`           | Transparent kachō-e cutouts (synced by `birdlistener art`; not in git) |
| `images/`, `species_map.json` | Legacy Audubon plates for `BL_ART_MODE=plates` |
