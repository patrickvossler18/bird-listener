"""Find Raspberry Pi Imager, pick the right Raspberry Pi OS image, list SD
cards, and write the card with our cloud-init files.

Imager's --cli mode writes one image to one device and verifies it; the
customisation the GUI offers is passed as files with --cloudinit-userdata and
--cloudinit-networkconfig (Imager 2.x). Windows builds lack a usable CLI path
for us, so there we hand over the files and instructions instead.
"""
from __future__ import annotations

import json
import os
import plistlib
import shutil
import subprocess
import sys
import urllib.request
from dataclasses import dataclass
from pathlib import Path

CATALOG_URL = "https://downloads.raspberrypi.com/os_list_imagingutility_v4.json"

IMAGER_CANDIDATES = [
    "/Applications/Raspberry Pi Imager.app/Contents/MacOS/rpi-imager",
    "rpi-imager",
    "/usr/bin/rpi-imager",
    "/usr/local/bin/rpi-imager",
    "/snap/bin/rpi-imager",
    r"C:\Program Files (x86)\Raspberry Pi Imager\rpi-imager.exe",
    r"C:\Program Files\Raspberry Pi Imager\rpi-imager.exe",
]


def find_imager() -> str | None:
    for c in IMAGER_CANDIDATES:
        if os.path.isabs(c) and os.path.exists(c):
            return c
        found = shutil.which(c)
        if found:
            return found
    return None


@dataclass
class OsImage:
    name: str
    url: str
    sha256: str
    release_date: str
    init_format: str


def pick_image(arch: str = "arm64", timeout: float = 30) -> OsImage:
    """The current Raspberry Pi OS Lite for `arch` ('arm64' or 'armhf')."""
    want = "Raspberry Pi OS Lite (64-bit)" if arch == "arm64" else "Raspberry Pi OS Lite (32-bit)"
    req = urllib.request.Request(CATALOG_URL, headers={"User-Agent": "bird-listener"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        catalog = json.loads(r.read())

    def walk(items):
        for it in items:
            if "subitems" in it:
                yield from walk(it["subitems"])
            else:
                yield it

    for it in walk(catalog["os_list"]):
        if it.get("name") == want:
            if it.get("init_format") != "cloudinit-rpi":
                raise SystemExit(f"error: {want} no longer uses cloud-init; this tool needs updating")
            return OsImage(name=it["name"], url=it["url"], sha256=it.get("image_download_sha256", ""),
                           release_date=it.get("release_date", "?"), init_format=it["init_format"])
    raise SystemExit(f"error: could not find '{want}' in the Raspberry Pi OS catalog")


@dataclass
class Disk:
    device: str
    size_gb: float
    label: str


def list_removable_disks() -> list[Disk]:
    if sys.platform == "darwin":
        out = subprocess.run(["diskutil", "list", "-plist", "external", "physical"],
                             capture_output=True).stdout
        data = plistlib.loads(out) if out else {}
        disks = []
        for d in data.get("AllDisksAndPartitions", []):
            dev = "/dev/" + d["DeviceIdentifier"]
            size = d.get("Size", 0) / 1e9
            names = [p.get("VolumeName") for p in d.get("Partitions", []) if p.get("VolumeName")]
            info = subprocess.run(["diskutil", "info", "-plist", dev], capture_output=True).stdout
            model = plistlib.loads(info).get("MediaName", "") if info else ""
            disks.append(Disk(dev, size, ", ".join(filter(None, [model] + names)) or "unnamed"))
        return disks
    if sys.platform.startswith("linux"):
        out = subprocess.run(["lsblk", "-J", "-d", "-b", "-o", "NAME,SIZE,RM,MODEL,TRAN,TYPE"],
                             capture_output=True, text=True).stdout
        disks = []
        for d in json.loads(out or "{}").get("blockdevices", []):
            if d.get("type") != "disk":
                continue
            if not (d.get("rm") in (True, "1", 1) or d.get("tran") in ("usb", "mmc")):
                continue
            disks.append(Disk("/dev/" + d["name"], int(d.get("size") or 0) / 1e9,
                              (d.get("model") or d.get("tran") or "").strip() or "removable"))
        return disks
    return []


def write_card(imager: str, image_url: str, device: str, user_data: Path, network_config: Path,
               *, sha256: str = "", dry_run: bool = False) -> list[str]:
    cmd = [imager, "--cli", "--disable-eject",
           "--cloudinit-userdata", str(user_data),
           "--cloudinit-networkconfig", str(network_config)]
    if sha256:
        cmd += ["--sha256", sha256]
    cmd += [image_url, device]
    if sys.platform != "win32" and os.geteuid() != 0:
        cmd = ["sudo"] + cmd
    if dry_run:
        return cmd
    if sys.platform == "darwin":
        subprocess.run(["diskutil", "unmountDisk", device], capture_output=True)
    subprocess.run(cmd, check=True)
    return cmd
