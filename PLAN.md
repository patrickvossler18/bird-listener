# Bird Listener — Framed Audubon Display (Plan)

## Context

Inspired by a Twitter project (a window microphone that listens for birds and
notifies you), this project is centered on a **nicely framed display** that shows
full-color naturalist watercolor illustrations — in the style of Audubon's
*Birds of America* (public domain) — of whatever bird the microphone hears nearby.
Requirements:

- Continuous outdoor bird-song detection from a mic at the window.
- A framed wall display that swaps to the matching Audubon plate on detection.
- **Light detection** so the display goes dark when the room lights go off at night.
- Mic and display are in **different locations** (separate nodes on WiFi).
- Detection runs **locally** (not cloud/Lambda — confirmed).
- Display node is a **Raspberry Pi Zero 2 W** in a **Waveshare RPi-Zero-PhotoPainter**
  (pre-framed wood, 7.3" color e-ink) — chosen variant.
- Phone notifications: **deferred** (easy to add later — BirdNET-Go supports it natively).

The outcome: a quiet, paper-like framed print on the wall that quietly updates
itself to "what bird is outside right now," with zero glow at night.

## Architecture

Two nodes on the home WiFi, decoupled via MQTT. No cloud.

```
  [ Window node ]                              [ Wall node ]
  Raspberry Pi 4 (2-4GB)                        Pi Zero 2 W (in Waveshare wood frame)
   ├─ USB sound card + electret/lavalier mic     ├─ 7.3" E6 Spectra-6 e-ink (pre-framed)
   ├─ BirdNET-Go (Docker) — 24/7 inference       ├─ BH1750 ambient light sensor (I2C)
   └─ Mosquitto MQTT broker                       └─ Python display service
            │                                              │
            └────────  MQTT: "birdnet/detection" ──────────┘
                       {common, scientific, confidence, time}
```

Data flow:
1. BirdNET-Go analyzes 3-second audio segments continuously and, on a confident
   detection, publishes a JSON event to MQTT (`commonName`, `scientificName`,
   `confidence`, `timestamp`).
2. The wall node subscribes to that topic. It keeps a **rolling window** of
   recent species (deduped) and renders the **scientific name → local Audubon
   plate image(s)**, dithered to the 6-color palette: a single bird fills the
   panel with a caption; multiple birds heard in the window are shown as a 2–4
   cell **collage**. The panel only refreshes when the set of recent birds
   changes (and never faster than a min-refresh interval).
3. The BH1750 gates the display: below a lux threshold (lights off), the service
   stops refreshing / clears to blank. E-ink holds its last image with zero
   power, so "off" simply means "don't drive it."

Why local, not cloud: continuous 24/7 audio makes Lambda's 15-min cap + cold
starts awkward and adds bandwidth/cost; BirdNET-Go is free, low-latency, and
debuggable via its own local web UI.

## Bill of materials

**Window / detection node**
- Raspberry Pi 4 (2GB ok, 4GB comfortable) — *required tier; BirdNET-Go dropped
  Pi 3 / Zero 2 W support.* Pi 5 if you want headroom.
- USB sound card (CM108-based, or Sound Blaster Play! 3) + omnidirectional
  electret/lavalier mic (e.g. Boya BY-LM40, or PUI AOM-5024L capsule on shielded
  cable). Weatherproof the capsule if it sits outside.
- Power supply, microSD (32GB+), small enclosure near the window.

**Wall / display node — Waveshare RPi-Zero-PhotoPainter (chosen)**
- **Waveshare RPi-Zero-PhotoPainter** — solid-wood pre-framed 7.3" E6 (Spectra 6,
  800×480) panel designed to host a **Raspberry Pi Zero 2 W**. The display node
  *already framed* — solves mounting/framing in one purchase.
- Raspberry Pi Zero 2 W (has WiFi, which we need) + microSD (32GB+ for the
  image library).
- **BH1750** I2C light sensor (STEMMA QT / Qwiic version for solderless wiring),
  routed so it can "see" the room (small hole/edge gap in the frame). USB power.

Variants considered (controller is what matters):
- ✅ **RPi-Zero-PhotoPainter** — hosts a Pi Zero 2 W (WiFi). Best-supported path
  (Python + MQTT). **Chosen.**
- **ESP32-S3-PhotoPainter** — ESP32-S3 (WiFi/BT) onboard; the "use my ESP-32s"
  option (GxEPD2 firmware). Viable alternative, not chosen.
- ❌ **PhotoPainter (B)** — RP2350A, **no WiFi/BT**; a battery frame that cycles
  TF-card images on an RTC timer. Can't receive live detections over the network
  without tethering/custom radio. Avoided.

**Upgrade option:** Waveshare 13.3" Spectra 6 (1600×1200) for a gallery-size
piece (~$190–200) — same software approach, larger (unframed) panel.

## Software components

Repo at `/Users/patrick/bird-listener`:

```
bird-listener/
├─ window-node/        # BirdNET-Go docker-compose + config
├─ wall-node/          # display service (Python)
│   ├─ display_service.py    # MQTT subscriber → render loop
│   ├─ display_driver.py     # Waveshare epd7in3e + mock PNG driver
│   ├─ renderer.py           # compose plate + caption (Pillow)
│   ├─ light_sensor.py       # BH1750 read + threshold/hysteresis
│   ├─ config.py             # env-var configuration
│   ├─ species_map.json      # scientificName → image filename
│   └─ images/               # cropped Audubon plates
└─ tools/
    ├─ fetch_plates.py       # pull plates from Wikimedia Commons by scientific name
    └─ build_images.py       # process manually-sourced plates (local folder + CSV)
```

**1. BirdNET-Go (window node)** — run via Docker (`tphakala/birdnet-go`).
Configure: audio input device, **location/lat-long** (so it weights to local
species), confidence threshold, and the **MQTT output** (broker = localhost
Mosquitto, topic e.g. `birdnet/detection`). Has a web UI for live spectrograms
and debugging. Mosquitto runs as a second container/service on the same Pi.

**2. Display service (wall node)** — Python, libraries: `paho-mqtt` (subscribe),
Waveshare's `epd7in3e` Python driver (E6 panel; feed it a `Pillow` image,
Floyd-Steinberg dithered to the 6-color palette), `Pillow` (compose art +
caption), `smbus2`/BH1750 driver.
- Subscribe to `birdnet/detection`; debounce so the same species doesn't thrash
  the panel; ignore detections below threshold.
- Map scientific name → local image via `species_map.json`. Fallback when a
  detected species has **no Audubon plate** (Audubon = 435 N. American species,
  BirdNET knows ~6000): show a neutral "card" with the name. Log misses so the
  map can be extended.
- Render: fit plate to 800×480, overlay a small caption (common name + time).
- Light gate: poll BH1750 with hysteresis (e.g. off below ~5 lux, on above
  ~15 lux) to avoid flicker at dusk. When "off," skip refreshes / optionally clear.

**3. Image pipeline** — primary tool `tools/fetch_plates.py` pulls plates from
**Wikimedia Commons** by scientific name (category intersection of
`The Birds of America` × `{species} (illustrations)`), resized via the Commons
CDN, into `wall-node/images/` + `species_map.json`. Public domain, no API key.
`tools/build_images.py` remains for plates sourced manually (local folder + CSV).
(No official Audubon API exists; Commons is the reliable scientific-name-keyed
source — verified by fetching real plates.)

## Build & framing notes

- **Two Pis on the same WiFi/LAN.** Give the detection Pi a stable hostname/IP so
  the wall node's MQTT broker address is fixed.
- **RPi-Zero-PhotoPainter** ships the Pi Zero 2 W mount + 7.3" panel inside the
  wood frame; the Zero connects via Waveshare's driver board (SPI). Confirm which
  GPIO pins the driver board uses so the **BH1750 I2C** lines stay free (use a
  stacking header / break out I2C if needed).
- **Frame:** already done by the PhotoPainter wood frame — just route the light
  sensor to a discreet opening/edge gap so it samples room light, not the panel.
- Mic outside: weatherproof the capsule (foam windscreen + drip protection);
  keep the USB run within spec or use a powered hub.

## Implementation milestones

1. **Detection works (window node):** Pi 4 + mic, BirdNET-Go running, confirm
   detections in its web UI; enable MQTT + Mosquitto; watch events with
   `mosquitto_sub -t birdnet/detection`.
2. **Display works (wall node):** Pi Zero 2 W in the PhotoPainter frame; render a
   single static Audubon plate end-to-end to validate the panel + dithering.
3. **Light gate:** wire BH1750, implement threshold + hysteresis; verify panel
   blanks/holds when room goes dark and resumes when lit.
4. **Glue:** display service subscribes to MQTT, maps species → image, refreshes
   on real detections with debounce + fallback.
5. **Image library:** run `build_images.py` for your regional species; fill out
   `species_map.json`; handle "no plate" fallback.
6. **(Deferred) Notifications:** enable a BirdNET-Go push provider
   (ntfy/Pushover/Telegram) — config-only, no extra hardware.

## Verification (end-to-end)

- `mosquitto_sub -t birdnet/detection` shows JSON events while birds (or test
  playback near the mic) are detected.
- Publish a fake event by hand and confirm the wall panel swaps to the matching
  plate with caption:
  `mosquitto_pub -t birdnet/detection -m '{"scientificName":"Cardinalis cardinalis","commonName":"Northern Cardinal","confidence":0.9}'`
- **Light gate:** cover the BH1750 / lights off → service stops refreshing;
  restore light → resumes.
- **Full loop:** play a recorded bird call near the mic; within seconds the
  matching plate appears on the framed display.
- **Fallback:** publish an event for a species with no plate; confirm graceful
  fallback card + a logged "missing image" entry.

## Open items
- Confirm BH1750 I2C pins stay free given the PhotoPainter driver board's GPIO
  usage on the Zero 2 W header (may need a stacking header) — verify in milestone 3.
- Decide regional species scope for the image library (drives how many plates to
  prep up front).
- Notifications: revisit after the display is working.
