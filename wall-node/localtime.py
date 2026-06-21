"""Timestamp localization for the caption bar.

BirdNET-Go publishes detection timestamps in whatever its host clock emits —
typically UTC (which is why the panel was showing GMT). We parse that timestamp
once, at the point we receive it, and reformat it in the configured local zone
(Pacific by default) so the e-ink caption reads like a wall clock.

The parser is deliberately permissive: BirdNET-Go's payload key and format have
varied across versions (ISO 8601 with or without a `Z`/offset, plain
`date time`, time-only `HH:MM:SS`, or a Unix epoch). Anything we can't parse is
passed through unchanged rather than dropped, so a format we didn't anticipate
degrades to "show the raw string" instead of a blank caption.
"""
from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

# Naive timestamps (no zone in the string) are assumed to be UTC, which matches
# BirdNET-Go's default output and the GMT behaviour we're correcting.
_ASSUMED_SOURCE_TZ = timezone.utc

_NAIVE_DATETIME_FORMATS = (
    "%Y-%m-%d %H:%M:%S",
    "%Y/%m/%d %H:%M:%S",
    "%Y-%m-%dT%H:%M:%S",
)
_TIME_ONLY_FORMATS = ("%H:%M:%S", "%H:%M")


def _parse_to_utc(raw) -> datetime | None:
    """Best-effort parse of a BirdNET-Go timestamp into an aware UTC datetime.

    Returns None if `raw` is empty or can't be recognized as a time."""
    if raw is None:
        return None

    # Epoch seconds, as a number or a numeric string.
    if isinstance(raw, (int, float)):
        try:
            return datetime.fromtimestamp(float(raw), tz=timezone.utc)
        except (ValueError, OverflowError, OSError):
            return None

    s = str(raw).strip()
    if not s:
        return None
    if s.replace(".", "", 1).isdigit():
        try:
            return datetime.fromtimestamp(float(s), tz=timezone.utc)
        except (ValueError, OverflowError, OSError):
            pass

    # ISO 8601. Normalize a trailing Z, which datetime.fromisoformat can't parse
    # on Python < 3.11 (the Pi may run an older interpreter).
    iso = s[:-1] + "+00:00" if s.endswith(("Z", "z")) else s
    try:
        dt = datetime.fromisoformat(iso)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=_ASSUMED_SOURCE_TZ)
        return dt.astimezone(timezone.utc)
    except ValueError:
        pass

    for fmt in _NAIVE_DATETIME_FORMATS:
        try:
            return datetime.strptime(s, fmt).replace(tzinfo=_ASSUMED_SOURCE_TZ)
        except ValueError:
            continue

    # Time-only — attach today's UTC date so it can still be zone-converted.
    for fmt in _TIME_ONLY_FORMATS:
        try:
            t = datetime.strptime(s, fmt).time()
        except ValueError:
            continue
        today = datetime.now(timezone.utc).date()
        return datetime.combine(today, t, tzinfo=_ASSUMED_SOURCE_TZ)

    return None


def format_local(raw, tz_name: str) -> str | None:
    """Format a detection timestamp in the named zone for the caption bar.

    - None / empty -> None (caption simply omits the time).
    - Parseable -> local time as "3:07 PM" (today) or "Jun 16, 3:07 PM" (older).
    - Unparseable -> the original string, untouched.
    """
    if raw is None:
        return None

    dt = _parse_to_utc(raw)
    if dt is None:
        s = str(raw).strip()
        return s or None

    try:
        local = dt.astimezone(ZoneInfo(tz_name))
    except (ZoneInfoNotFoundError, ValueError):
        # Bad/unknown zone name: fall back to the host's local time rather than
        # silently keeping UTC.
        local = dt.astimezone()

    today = datetime.now(local.tzinfo).date()
    fmt = "%-I:%M %p" if local.date() == today else "%b %-d, %-I:%M %p"
    return local.strftime(fmt)
