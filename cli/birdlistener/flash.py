"""`birdlistener flash`: write an SD card that turns into a bird-listener node
on first boot, no keyboard or monitor needed.

Asks (or takes flags for): which node, WiFi, where you are, and generates the
rest (MQTT password, SSH key, login password). Everything is remembered in
the site file so the second card asks nothing new.
"""
from __future__ import annotations

import datetime as dt
import os
import re
import secrets
import sys
from pathlib import Path

from . import cloudinit, geocode, imager, site, sshkeys
from .prompts import ask, choose, confirm, human_step, say, step

MQTT_ALPHABET = "abcdefghijkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def gen_password(n: int = 20) -> str:
    return "".join(secrets.choice(MQTT_ALPHABET) for _ in range(n))


def local_timezone() -> str | None:
    """The laptop's IANA zone, as a default for the Pis."""
    try:
        target = Path("/etc/localtime").resolve()
        parts = target.parts
        if "zoneinfo" in parts:
            return "/".join(parts[parts.index("zoneinfo") + 1:])
    except OSError:
        pass
    tzfile = Path("/etc/timezone")
    if tzfile.exists():
        return tzfile.read_text().strip() or None
    return None


def locale_country() -> str | None:
    """'en_US' -> 'US', from the environment; None if unknown."""
    import locale
    try:
        loc = locale.getlocale()[0] or ""
    except ValueError:
        loc = ""
    loc = loc or os.environ.get("LANG", "")
    m = re.match(r"^[a-z]{2}[_-]([A-Z]{2})", loc)
    return m.group(1) if m else None


def resolve_location(args, s: dict) -> tuple[float, float, str, str]:
    """Return (lat, lon, place label, country code)."""
    if args.lat is not None and args.lon is not None:
        cc = (args.country or s.get("country") or "").upper()
        return args.lat, args.lon, f"{args.lat}, {args.lon}", cc
    if s.get("lat") is not None and s.get("lon") is not None and not args.location:
        return s["lat"], s["lon"], s.get("place", ""), (s.get("country") or "").upper()

    while True:
        text = ask("Where is the mic? Town and state/country is plenty (or paste 'lat, lon')",
                   flag="--location", value=args.location, default=s.get("place"))
        coords = geocode.parse_coords(text)
        if coords:
            cc = (args.country or s.get("country") or "").upper()
            return coords[0], coords[1], text, cc
        # A bare postcode is ambiguous across countries; scope it when we can.
        hint = args.country or s.get("country") or (locale_country() if text.strip().isdigit() else None)
        try:
            place = geocode.lookup(text, country_hint=hint)
        except Exception as e:  # noqa: BLE001
            raise SystemExit(f"error: geocoding failed ({e}); pass --lat/--lon instead")
        if not place:
            say(f"  nothing found for {text!r}; try a bigger town, or paste coordinates")
            args.location = None
            continue
        say(f"  {place.name}\n  -> {place.lat}, {place.lon}  (country {place.country_code})")
        if confirm("Use this?", yes=args.yes, default=True):
            return place.lat, place.lon, place.name, place.country_code
        args.location = None


def run(args) -> int:
    s = site.load()
    node = choose("Which Pi is this card for", [("window", "window node: mic + BirdNET-Go (Pi 4/5)"),
                                                ("wall", "wall node: e-ink frame (Pi Zero 2 W)")],
                  flag="--node", value=args.node)

    # --- shared answers, remembered in site.json ---------------------------
    s["user"] = ask("Login user on the Pis", flag="--user", value=args.user, default=s["user"])
    s["window_host"] = ask("Hostname for the window node", flag="--window-host",
                           value=args.window_host, default=s["window_host"])
    s["wall_host"] = ask("Hostname for the wall node", flag="--wall-host",
                         value=args.wall_host, default=s["wall_host"])
    s["wifi_ssid"] = ask("WiFi network name", flag="--wifi-ssid", value=args.wifi_ssid,
                         default=s.get("wifi_ssid"))
    s["wifi_password"] = ask("WiFi password", flag="--wifi-password", value=args.wifi_password,
                             default=s.get("wifi_password"), secret=True)
    lat, lon, place, cc = resolve_location(args, s)
    s.update(lat=lat, lon=lon, place=place)
    s["country"] = ask("Country code for WiFi regulations (2 letters)", flag="--country",
                       value=args.country, default=cc or s.get("country"),
                       validate=lambda v: None if len(v) == 2 and v.isalpha() else "two letters, e.g. US").upper()
    s["timezone"] = ask("Timezone (IANA name)", flag="--timezone", value=args.timezone,
                        default=s.get("timezone") or local_timezone())
    s.setdefault("mqtt_pass", gen_password())
    s.setdefault("login_password", gen_password(12))
    if args.repo_url:
        s["repo_url"] = args.repo_url
    if args.repo_ref:
        s["repo_ref"] = args.repo_ref

    step("SSH key for the Pis")
    pubkey = sshkeys.ensure_key()
    hosts = {s["window_host"]: f"{s['window_host']}.local", s["wall_host"]: f"{s['wall_host']}.local"}
    sshkeys.write_config(hosts, s["user"])
    say(f"    {sshkeys.KEY_FILE}  (ssh {s['window_host']} / ssh {s['wall_host']} will just work)")

    # --- the node's own config file ----------------------------------------
    hostname = s["window_host"] if node == "window" else s["wall_host"]
    node_env = {
        "BL_NODE": node,
        "BL_MQTT_USER": s["mqtt_user"],
        "BL_MQTT_PASS": s["mqtt_pass"],
        "BL_REPO_URL": s["repo_url"],
        "BL_REPO_REF": s["repo_ref"],
    }
    if node == "window":
        node_env.update(BL_LATITUDE=str(lat), BL_LONGITUDE=str(lon), BL_THRESHOLD=str(s["threshold"]))
    else:
        node_env.update(BL_MQTT_HOST=f"{s['window_host']}.local", BL_ROTATE=str(s["rotate"]),
                        BL_TIMEZONE=s["timezone"])

    plan = cloudinit.NodePlan(
        node=node, hostname=hostname, user=s["user"], password=s["login_password"],
        ssh_pubkey=pubkey, timezone=s["timezone"], wifi_ssid=s["wifi_ssid"],
        wifi_password=s["wifi_password"], country=s["country"], node_env=node_env,
        repo_url=s["repo_url"], repo_ref=s["repo_ref"],
    )
    out_dir = Path(args.out_dir) if args.out_dir else site.SITE_DIR / "cloud-init" / hostname
    out_dir.mkdir(parents=True, exist_ok=True)
    user_data = out_dir / "user-data"
    network_config = out_dir / "network-config"
    meta_data = out_dir / "meta-data"
    instance_id = f"bird-listener-{hostname}-{dt.datetime.now():%Y%m%d%H%M%S}"
    user_data.write_text(cloudinit.render_user_data(plan))
    network_config.write_text(cloudinit.render_network_config(plan))
    meta_data.write_text(cloudinit.render_meta_data(plan, instance_id))
    for f in (user_data, network_config, meta_data):
        f.chmod(0o600)
    site.save(s)

    say()
    step(f"Plan for the {node} node")
    say(f"    hostname   {hostname}.local   user {s['user']}")
    say(f"    location   {place} ({lat}, {lon})   tz {s['timezone']}   wifi {s['wifi_ssid']} [{s['country']}]")
    say(f"    cloud-init {out_dir}")
    say(f"    site file  {site.SITE_FILE}  (holds the generated passwords)")

    if args.emit_only:
        say("\nCopy user-data, network-config and meta-data onto the card's boot partition "
            "after writing Raspberry Pi OS Lite with Raspberry Pi Imager, then boot the Pi.")
        return 0

    # --- the image and the card ---------------------------------------------
    arch = "armhf" if (node == "wall" and args.pi == "zero-w") else "arm64"
    step("Looking up the current Raspberry Pi OS Lite image")
    image = imager.pick_image(arch)
    say(f"    {image.name} ({image.release_date})")

    binary = imager.find_imager()
    if sys.platform == "win32" or not binary:
        say("\nRaspberry Pi Imager's command line isn't available here"
            + ("" if binary else " (install it from https://www.raspberrypi.com/software/)") + ".")
        say(f"Write '{image.name}' with the Imager app (no customisation needed), then copy the three")
        say(f"files in {out_dir} onto the card's boot partition and boot the Pi.")
        return 0

    human_step("Insert the microSD card for this Pi into your computer.", yes=args.yes or args.dry_run)
    disks = imager.list_removable_disks()
    device = args.device
    if not device:
        if not disks:
            raise SystemExit("error: no removable disks found; pass --device explicitly")
        opts = [(d.device, f"{d.device}  {d.size_gb:.1f} GB  {d.label}") for d in disks]
        device = choose("Which disk is the SD card? (everything on it will be erased)", opts,
                        flag="--device", value=None if len(opts) > 1 else opts[0][0])
    say(f"    will write {image.name} to {device}")
    cmd = imager.write_card(binary, image.url, device, user_data, network_config, dry_run=True)
    say("    " + " ".join(cmd))
    if args.dry_run:
        say("\n(dry run) nothing written")
        return 0
    if not confirm(f"Erase {device} and write the card?", yes=args.yes, default=False):
        say("aborted")
        return 1
    step("Writing (downloads the image on first use; a few minutes)")
    imager.write_card(binary, image.url, device, user_data, network_config)

    say()
    step("Done. Next:")
    if node == "window":
        say(f"  1. Put the card in the Pi 4/5, plug in the USB mic, power it on.")
        say(f"  2. First boot installs everything itself (10-15 min). Then: birdlistener doctor")
        say(f"  3. Flash the wall card: birdlistener flash --node wall")
    else:
        say(f"  1. Put the card in the Pi Zero inside the frame and power it on (USB only, no battery).")
        say(f"  2. First boot installs everything itself (15-20 min). Then: birdlistener doctor")
        say(f"  3. Build the art: birdlistener art")
    return 0
