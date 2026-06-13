# Bird Listener — Framed Audubon Display

A microphone outside the window listens for birds 24/7. When a species is
identified, a framed e-ink display on the wall swaps to the matching
*Birds of America* (Audubon, public domain) plate. The display goes dark when
the room lights go off at night.

Two devices on your home WiFi, decoupled by MQTT — no cloud:

```
  [ Window node ]                              [ Wall node ]
  Raspberry Pi 4 (2-4GB)                        Pi Zero 2 W (Waveshare RPi-Zero-PhotoPainter)
   ├─ USB mic + sound card                       ├─ 7.3" E6 Spectra-6 e-ink (pre-framed wood)
   ├─ BirdNET-Go (Docker), 24/7 inference        ├─ BH1750 ambient light sensor (I2C)
   └─ Mosquitto MQTT broker                       └─ display_service.py
            │                                              │
            └────────  MQTT topic: birdnet/detection ──────┘
                       {commonName, scientificName, confidence, ...}
```

## Repo layout

```
bird-listener/
├─ window-node/        # BirdNET-Go + Mosquitto (Docker) for the detection Pi
├─ wall-node/          # Python display service for the Pi Zero 2 W
│   ├─ display_service.py    # MQTT subscriber → render → e-ink refresh
│   ├─ display_driver.py     # Waveshare epd7in3e driver + mock PNG driver
│   ├─ renderer.py           # compose plate + caption (Pillow)
│   ├─ light_sensor.py       # BH1750 read + threshold/hysteresis (+ mock)
│   ├─ config.py             # env-var configuration
│   ├─ species_map.json      # scientificName → image filename
│   ├─ requirements.txt
│   └─ images/               # cropped Audubon plates (built by tools/)
└─ tools/
    └─ build_images.py       # crop/resize Audubon source → images/ + species_map
```

## Quick start

### Dry run on your laptop (no hardware)

The display service runs in **mock mode** when the Pi/e-ink/I2C libraries aren't
present: it writes the rendered frame to `wall-node/out/last_frame.png` instead
of pushing to the panel, and simulates a "lit room". This lets you verify the
whole render + MQTT + debounce pipeline before any hardware arrives.

```bash
cd wall-node
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt        # Pillow + paho-mqtt (hardware libs are optional)

# 1) Render a single plate to a PNG, no MQTT needed:
python display_service.py --once "Cardinalis cardinalis"
open out/last_frame.png

# 2) Run the full service against a local broker (see window-node), then:
#    mosquitto_pub -t birdnet/detection -m '{"scientificName":"Cardinalis cardinalis","commonName":"Northern Cardinal","confidence":0.9}'
python display_service.py
```

### Window node (detection Pi)

See [`window-node/README.md`](window-node/README.md). In short:
`docker compose up -d` brings up BirdNET-Go (web UI on `:8080`) and Mosquitto
(`:1883`). Configure the mic + your lat/long + MQTT output in
`window-node/birdnet-go/config.yaml`.

### Wall node (Pi Zero 2 W in the PhotoPainter)

See [`wall-node/README.md`](wall-node/README.md). Install requirements + the
Waveshare e-Paper Python library, point `BL_MQTT_HOST` at the detection Pi, and
run `display_service.py` (as a systemd service for always-on).

## Building the image library

`tools/build_images.py` crops/resizes Audubon plates to the panel and writes
`species_map.json`. The Audubon *Birds of America* plates are public domain
(published 1827–1838); download high-res scans from audubon.org, the Internet
Archive, or Rawpixel (CC0). See [`tools/README.md`](tools/README.md).

## Status / roadmap

- [ ] Window node hardware + BirdNET-Go detecting (verify in its web UI)
- [ ] Wall node renders a static plate on the real panel
- [ ] BH1750 light gate verified
- [ ] End-to-end: real bird call → matching plate on the wall
- [ ] Image library filled out for the local region
- [ ] (Deferred) phone notifications via BirdNET-Go (ntfy/Pushover/Telegram)
