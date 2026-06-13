# Wall node — framed e-ink display

Runs on the **Raspberry Pi Zero 2 W** inside the Waveshare RPi-Zero-PhotoPainter.
Subscribes to BirdNET-Go detections over MQTT and refreshes the 7.3" E6 panel
with the matching Audubon plate; the BH1750 blanks it when the room is dark.

## Install (on the Pi)

```bash
sudo raspi-config        # enable SPI and I2C
sudo apt install -y python3-pip python3-venv git
git clone https://github.com/waveshareteam/e-Paper ~/e-Paper   # Waveshare driver

cd ~/bird-listener/wall-node
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
pip install smbus2                                             # BH1750
export PYTHONPATH=$HOME/e-Paper/RaspberryPi_JetsonNano/python/lib:$PYTHONPATH
```

## Configure

Point it at the detection Pi and tune thresholds via env vars (see `config.py`
for the full list):

```bash
export BL_MQTT_HOST=birdpi.local      # hostname/IP of the window node
export BL_MIN_CONFIDENCE=0.65
export BL_DEBOUNCE_SECONDS=300        # don't redraw same species within 5 min
export BL_LUX_OFF=5 BL_LUX_ON=15      # light-gate hysteresis
```

## Run

```bash
python display_service.py             # service loop (MQTT + light gate)
python display_service.py --once "Cardinalis cardinalis" --common "Northern Cardinal"
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
