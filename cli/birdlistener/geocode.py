"""Turn a place name into rough coordinates with OpenStreetMap's Nominatim.

Nominatim is free and needs no key. Its usage policy allows light one-off
use like this (one query per setup) but requires a descriptive User-Agent and
forbids bulk or repeated identical queries: https://operations.osmfoundation.org/policies/nominatim/
BirdNET-Go's range model only needs city-level precision, so ask people for a
town or postcode rather than a street address.
"""
from __future__ import annotations

import json
import urllib.parse
import urllib.request
from dataclasses import dataclass

from . import __version__

USER_AGENT = f"bird-listener/{__version__} (https://github.com/patrickvossler18/bird-listener)"
ENDPOINT = "https://nominatim.openstreetmap.org/search"


@dataclass
class Place:
    lat: float
    lon: float
    name: str
    country_code: str  # ISO 3166-1 alpha-2, upper case (WiFi regulatory domain)


def lookup(query: str, timeout: float = 15, country_hint: str | None = None) -> Place | None:
    """country_hint: ISO alpha-2 to disambiguate bare postcodes ('94110' exists in DE too)."""
    params = {"q": query, "format": "jsonv2", "limit": 1, "addressdetails": 1}
    if country_hint:
        params["countrycodes"] = country_hint.lower()
    q = urllib.parse.urlencode(params)
    req = urllib.request.Request(f"{ENDPOINT}?{q}", headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        rows = json.loads(r.read())
    if not rows:
        return None
    row = rows[0]
    cc = (row.get("address", {}).get("country_code") or "").upper()
    return Place(lat=round(float(row["lat"]), 4), lon=round(float(row["lon"]), 4),
                 name=row.get("display_name", query), country_code=cc)


def parse_coords(text: str) -> tuple[float, float] | None:
    """Accept '37.77, -122.44' pasted from a map app."""
    parts = [p.strip() for p in text.replace(";", ",").split(",")]
    if len(parts) != 2:
        return None
    try:
        lat, lon = float(parts[0]), float(parts[1])
    except ValueError:
        return None
    if -90 <= lat <= 90 and -180 <= lon <= 180:
        return round(lat, 4), round(lon, 4)
    return None
