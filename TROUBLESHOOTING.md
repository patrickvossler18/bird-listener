# Troubleshooting

Run `birdlistener doctor` first. Each failing line names its fix; this file
has the longer stories. Commands marked "on the Pi" run after `ssh birdpi` or
`ssh birdwall`.

## Setup

**A Pi never shows up on the network after flashing.**
Give it 20 minutes on the first boot. Then: is the WiFi 2.4 GHz? The Pi Zero
2 W only does 2.4 GHz, and some routers hide 2.4 and 5 GHz behind one name
with band steering, which usually works but not always. Check the SSID and
password in `~/.config/bird-listener/site.json`; re-flash if wrong
(`birdlistener flash --node wall --wifi-password ...`). If you can plug a
monitor in, the login is the user and `login_password` from that file.

**`ssh birdpi` says permission denied.**
The Pi was flashed by a different computer (a different key), or you set up
the Pi by hand. Copy `~/.ssh/bird-listener_ed25519.pub` into
`~/.ssh/authorized_keys` on the Pi, or run `flash` again from this computer.

**First boot finished but nothing is installed.**
On the Pi: `cat /var/log/bird-listener-firstboot.log`. The usual cause is no
internet at the time (the clone of this repo failed). Fix the network, then
`sudo bash /opt/bird-listener-bootstrap/install.sh` to rerun it.

**The repo is private and the clone fails.**
`install.sh` clones over HTTPS without credentials, so the repository (or
your fork, via `flash --repo-url`) must be public.

## Window node

**No detections after an hour.**
- Mic seen? On the Pi: `arecord -l` should list a USB capture device. The
  doctor's `mic` line checks the same thing. Try another USB port.
- Levels: open the dashboard (`ssh -L 8080:localhost:8080 birdpi`, then
  http://localhost:8080). The live spectrogram should react to sound.
- Threshold: `BL_THRESHOLD` in node.env (default 0.7). Lower it to 0.6 to see
  more, at the cost of some wrong guesses. Apply with `birdlistener update`.
- Location: doctor's `config` line shows the coordinates BirdNET-Go uses. 0,0
  means the range filter is off and everything sounds like a Wood Duck.

**MQTT says "not authorised".**
The wall node's password doesn't match the broker's. Both come from
node.env's `BL_MQTT_PASS`. On the window node, `bash ~/bird-listener/window-node/setup.sh`
rewrites the broker's password file from node.env; on the wall node edit
`~/bird-listener/wall-node/.env` and `sudo systemctl restart bird-display`.

**I want to see the raw stream.** On the Pi:
`mosquitto_sub -h localhost -t birdnet/detection -v -u birds -P '<pass>'`

**Container image updates.** `docker-update.sh` runs weekly. It follows
BirdNET-Go's GitHub releases (not the `:latest` tag, which is a nightly),
waits three days, pulls before changing anything, and rolls back if the new
container isn't healthy within three minutes. `journalctl -u docker-update`
shows what it did. `AUTO_UPGRADE_BIRDNET=false` in its environment makes it
report only.

## Wall node

**The panel never changes, and the log shows the service stuck.**
The PhotoPainter routes the panel's power-enable pin to BCM27, not the
Waveshare default BCM18. With the stock driver every refresh waits forever in
`ReadBusy()`. `wall-node/setup.sh` patches `PWR_PIN = 27` into
`~/e-Paper/.../waveshare_epd/epdconfig.py`; the doctor's `panel` line checks
it. Re-run setup if the driver got updated.

**The image is upside down.** `BL_ROTATE=180` (the default) or `0` in
`wall-node/.env`, then restart the service.

**Nothing in `journalctl -u bird-display` although birds are detected.**
Python buffers stdout when it isn't a terminal. The unit sets
`PYTHONUNBUFFERED=1`; if you wrote your own unit, add it.

**A bird shows as a plain name card.** There's no cutout for that species yet.
`birdlistener art` draws what's missing (it needs a Gemini key for the ones
AvianVisitors doesn't have). This also happens as seasons change.

**Test a render without waiting for a bird.** On the wall node:

```bash
sudo systemctl stop bird-display
cd ~/bird-listener/wall-node
PYTHONPATH=$HOME/e-Paper/RaspberryPi_JetsonNano/python/lib ./.venv/bin/python display_service.py --once "Cardinalis cardinalis"
sudo systemctl start bird-display
```

Or publish a fake detection from the window node (see AGENTS.md).

**Battery.** Don't. The PhotoPainter "with battery" variant's LiPo damaged the
charge IC on the original build; the Pi and panel survived on USB. Buy the
"without battery" variant and power it from the wall.

**Original Pi Zero W (armv6).** Works, with `flash --pi zero-w` for the 32-bit
image. pip installs are slow (piwheels has prebuilt numpy and Pillow; if it
compiles anything, wait). Collage packing is slower too; raise
`BL_COLLAGE_STRIDE` in `.env` if renders take more than a minute.

## Art pipeline

**`birdlistener art` can't find the species list.** It reads BirdNET-Go's
coordinates and range list over SSH from the window node; the doctor's
`config` and `detections` lines must be green first.

**Gemini returns nothing or 404.** The image model name in
`tools/kachoe/pregen.py` (`GEMINI_URL`) changes now and then; check Google's
model list and bump it. Billing must be enabled on the key.

**A bird looks like the wrong species.** `tools/kachoe/README.md`, "Tuning
quality": add a line to `species-notes.json` and regenerate that one bird.

**The cutout step is slow or runs out of memory.** BiRefNet needs about 4 GB
of RAM. `birdlistener art --docker` runs it in a container with the same
requirements; that doesn't reduce memory, just Python setup pain.
