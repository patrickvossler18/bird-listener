# Bird Listener

A microphone by the window listens for birds around the clock. When one is
identified, a framed e-ink print on the wall quietly changes to a kachō-e
style illustration of that bird, or a small collage of the birds heard in the
last quarter hour. No cloud, no glow, nothing to charge.

Two Raspberry Pis on your home WiFi, talking over MQTT:

```
  [ Window node ]                                [ Wall node ]
  Raspberry Pi 4 / 5                              Pi Zero 2 W in a Waveshare PhotoPainter
   ├─ USB lavalier mic                             ├─ 7.3" Spectra-6 colour e-ink, wood frame
   ├─ BirdNET-Go (Docker), 24/7 inference          └─ display service (Python)
   └─ Mosquitto MQTT broker
            │
            └───────  MQTT topic birdnet/detection  ───────┘
```

This project is a remix of [AvianVisitors](https://github.com/Twarner491/AvianVisitors)
by Teagan Warner: the idea of a cutout collage of recent visitors, the
illustration style, and most of the illustrations themselves come from there.
See [Credits and license](#credits-and-license).

## What you need

| Part | Notes | Approx. |
|---|---|---|
| Raspberry Pi 4 (2 GB is fine) or Pi 5 | BirdNET-Go needs this class; Pi 3 and Zero are too slow | $45–80 |
| USB lavalier microphone | e.g. [this USB-C/USB-A lavalier](https://www.amazon.com/dp/B0DFGMHM4B); it has its own audio interface, so no sound card needed | $20 |
| [Waveshare 7.3" E6 PhotoPainter, wood frame, without battery](https://www.amazon.com/dp/B0G4RJSPJC) | The frame, panel and Pi Zero carrier in one. Get the **without battery** variant and run it from USB | $110 |
| Raspberry Pi Zero 2 W | Sits inside the frame. An original Zero W also works (`--pi zero-w`) but is slow | $15 |
| 2 microSD cards (16 GB+) and 2 USB power supplies | | $25 |

Optional: a BH1750 light sensor (I2C) if you want the panel to blank when the
room is dark. The e-ink holds its image unpowered, so most people skip it.

Do not connect a battery to the PhotoPainter. A LiPo on this board damaged
the charge circuit on the original build; USB power is all it needs.

## Setting it up

Everything runs from your own computer with one tool. You never need to type
an SSH command or edit a file on a Pi, though you can.

```bash
git clone https://github.com/patrickvossler18/bird-listener.git
cd bird-listener
uv tool install ./cli        # or: pipx install ./cli
```

Install [Raspberry Pi Imager](https://www.raspberrypi.com/software/) if you
don't have it. Then:

1. **Write the window node's card.** It asks for your WiFi, a town (for
   BirdNET-Go's regional species list), and picks the rest. Insert the card in
   the Pi 4/5, plug in the mic, power on. First boot installs everything
   itself and takes 10–15 minutes.

   ```bash
   birdlistener flash --node window
   ```

2. **Write the wall node's card.** Asks nothing new. Insert it in the Pi Zero
   inside the frame, power on over USB, wait 15–20 minutes.

   ```bash
   birdlistener flash --node wall
   ```

3. **Check both.**

   ```bash
   birdlistener doctor
   ```

4. **Build the art.** Fetches the species BirdNET-Go expects at your location,
   downloads the illustrations AvianVisitors already has for them (most of
   them, in North America), draws the rest with Gemini if you give it an API
   key (a few dollars; [get a key here](https://aistudio.google.com/apikey)),
   cuts them out, and puts them on the wall node. This step runs on your
   computer because the cutout model is too heavy for the Pi.

   ```bash
   birdlistener art               # add --dry-run first to see the plan and cost
   ```

Then wait for a bird. To see live detections, tunnel to the BirdNET-Go
dashboard: `ssh -L 8080:localhost:8080 birdpi` and open http://localhost:8080.

Every question `flash` asks has a flag (`birdlistener flash --help`), so an
agent can drive the whole setup, and `--dry-run` shows exactly what would be
written. If you're on Windows, `flash --emit-only` writes the three cloud-init
files for you to copy onto a card written by the Imager app.

### Living with it

- `birdlistener doctor` any time something looks off. `--json` for agents.
- `birdlistener art` again in another season: BirdNET-Go's species list shifts
  through the year, and the pipeline only draws what's missing.
- `birdlistener update` pulls the latest code onto both Pis and re-runs setup.
- Security updates install themselves weekly; so do BirdNET-Go releases after
  a three-day soak, with rollback if the new one is unhealthy.

## How it fits together

```
bird-listener/
├─ cli/             birdlistener: flash, art, doctor, update (runs on your computer)
├─ install.sh       first-boot installer; reads /etc/bird-listener/node.env
├─ node.env.example the per-node config contract
├─ window-node/     BirdNET-Go + Mosquitto (Docker), setup.sh, doctor.py
├─ wall-node/       display service, renderer, e-ink driver, setup.sh, doctor.py
└─ tools/kachoe/    the art pipeline (seed -> Gemini -> cutouts); CC BY-NC-SA
```

**Configuration** lives in one file per Pi, `/etc/bird-listener/node.env`
(see `node.env.example`), written by `flash` through cloud-init. The wall
node's runtime tunables are in `wall-node/.env` (see `.env.example`), created
from it on first install and never overwritten afterwards, so hand edits stick.

**On first boot** cloud-init sets hostname, user, SSH key and WiFi, writes
node.env, clones this repo and runs `install.sh`, which runs the node's
`setup.sh`. The log is at `/var/log/bird-listener-firstboot.log` on the Pi.

**Setting up by hand** works too: flash Raspberry Pi OS Lite however you
like, copy `node.env.example` to `/etc/bird-listener/node.env`, fill it in,
and run `sudo bash install.sh` from a checkout. Each node's README has the
details, and `TROUBLESHOOTING.md` the things that went wrong once already.

**Security posture.** The MQTT broker requires a password (anything that can
publish to the detection topic controls the wall). BirdNET-Go's web UI is
bound to loopback, since it answers unauthenticated reads including your
coordinates; reach it over an SSH tunnel. SSH is key-only. The login user has
passwordless sudo, as Raspberry Pi OS sets up by default; remove
`/etc/sudoers.d/90-cloud-init-users` on each Pi if you'd rather type a
password (then `birdlistener update` will prompt).

## Credits and license

- [AvianVisitors](https://github.com/Twarner491/AvianVisitors) by Teagan
  Warner is where the cutout-collage idea, the kachō-e prompt approach and the
  seed illustrations come from. `tools/kachoe/` is adapted from its scripts
  and, together with the illustrations it produces, is licensed
  **CC BY-NC-SA 4.0** like the original. Non-commercial use, share alike,
  credit AvianVisitors. See `tools/kachoe/LICENSE`.
- [BirdNET-Go](https://github.com/tphakala/birdnet-go) does the listening,
  built on Cornell's BirdNET.
- The Edo-period style prints by Ohara Koson and Yoshida Hiroshi are public
  domain.
- The rest of this repository (display service, node setup, the laptop CLI)
  is original work under the [MIT License](LICENSE).
