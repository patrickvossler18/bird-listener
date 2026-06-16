# Wall node — framed e-ink display

Runs on the **Raspberry Pi Zero 2 W** inside the Waveshare RPi-Zero-PhotoPainter.
Subscribes to BirdNET-Go detections over MQTT and refreshes the 7.3" E6 panel
with the matching Audubon plate; the BH1750 blanks it when the room is dark.

## Install (on the Pi Zero)

First copy the repo over from your Mac (no GitHub creds needed):

```bash
# from the repo root on your Mac (use the Zero's IP or hostname):
rsync -av --delete --exclude '.git' --exclude '*/.venv' --exclude '*/out' \
  --exclude '__pycache__' --exclude '*/data' ./ pi@<zero-ip>:~/bird-listener/
```

Then bootstrap with one command — it enables SPI/I2C, installs the Waveshare
e-Paper driver + Python deps, and installs the `bird-display` systemd service:

```bash
ssh pi@<zero-ip>
cd ~/bird-listener
BL_MQTT_HOST=192.168.4.107 bash wall-node/setup.sh   # point at birdpi
```

(Manual equivalent, if you'd rather: `sudo raspi-config` to enable SPI+I2C,
`git clone https://github.com/waveshareteam/e-Paper ~/e-Paper`, then a venv with
`pip install -r requirements.txt smbus2 spidev gpiozero lgpio` and
`PYTHONPATH=$HOME/e-Paper/RaspberryPi_JetsonNano/python/lib`.)

> **PhotoPainter PWR-pin quirk (important):** this board routes the e-paper
> power-enable to **BCM27**, not the HAT-default **BCM18**. With the stock
> Waveshare driver every panel refresh hangs forever in `ReadBusy()`. `setup.sh`
> patches the cloned driver automatically; if you install by hand, edit
> `…/waveshare_epd/epdconfig.py` and set `PWR_PIN = 27`. (Source: Waveshare RPi
> Zero PhotoPainter manual, Hardware Connection.)

## Configure

Point it at the detection Pi and tune thresholds via env vars (see `config.py`
for the full list):

```bash
export BL_MQTT_HOST=birdpi.local        # hostname/IP of the window node
export BL_MIN_CONFIDENCE=0.65
export BL_MAX_BIRDS=4                    # show up to 4 recent birds as a collage (1 = single)
export BL_MULTI_WINDOW_SECONDS=900       # birds heard within 15 min are grouped
export BL_MIN_REFRESH_SECONDS=30         # protect the slow panel from rapid redraws
export BL_LUX_OFF=5 BL_LUX_ON=15         # light-gate hysteresis
```

### Multi-bird collage

Detections within `BL_MULTI_WINDOW_SECONDS` are grouped and shown together:
1 bird → full-bleed plate + caption; 2–4 birds → the plates are grouped as a
centered row (most-recent first) with one shared name bar listing all of them at
the bottom. In a collage the plates are auto-trimmed to their illustration
(`BL_PLATE_TRIM=0` to disable) so the birds sit close together rather than
floating in cream margin; full-sheet compositions are left intact. The panel
only refreshes when the *set* of recent birds changes, and never more often than
`BL_MIN_REFRESH_SECONDS`. Set `BL_MAX_BIRDS=1` for classic single-bird behavior.

## Run

```bash
python display_service.py             # service loop (MQTT + light gate)
python display_service.py --once "Cardinalis cardinalis"                       # one bird
python display_service.py --once "Cardinalis cardinalis" "Cyanocitta cristata" # collage preview
python display_service.py --clear     # blank the panel
```

On a machine without the Waveshare/BH1750 libs (e.g. your laptop) it runs in
**mock mode**: frames are written to `out/last_frame.png` and the room is assumed
lit. Force mock on the Pi with `BL_FORCE_MOCK_DISPLAY=1` / `BL_FORCE_MOCK_LIGHT=1`.

## Run as a service (always-on)

```bash
sudo cp bird-display.service /etc/systemd/system/
sudo systemctl enable --now bird-display
journalctl -u bird-display -f
```

Edit the unit's `Environment=` lines and paths first.

## Files

| File | Purpose |
|------|---------|
| `display_service.py` | MQTT subscriber, debounce, light gate, orchestration |
| `display_driver.py`  | Waveshare `epd7in3e` driver + mock PNG driver |
| `renderer.py`        | Compose plate + caption, dither to Spectra-6 palette |
| `light_sensor.py`    | BH1750 read with on/off hysteresis (+ mock) |
| `config.py`          | Env-var configuration |
| `species_map.json`   | `scientificName` → image filename in `images/` |
| `images/`            | Cropped Audubon plates (built by `../tools/build_images.py`) |
