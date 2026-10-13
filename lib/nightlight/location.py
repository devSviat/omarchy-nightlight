"""Where the screen is: the system time zone, and coordinates for it."""

from __future__ import annotations

import os
from pathlib import Path

from .log import die
from .paths import SETTINGS_PATH


def system_timezone() -> str:
    tz = os.environ.get("TZ")
    if tz:
        return tz
    localtime = Path("/etc/localtime")
    if localtime.is_symlink():
        target = os.path.realpath(localtime)
        marker = "/zoneinfo/"
        if marker in target:
            return target.split(marker, 1)[1]
    tzfile = Path("/etc/timezone")
    if tzfile.exists():
        name = tzfile.read_text().strip()
        if name:
            return name
    die("could not determine the system time zone")


def _parse_iso6709(coords: str) -> tuple[float, float]:
    """Split zone.tab's +DDMM+DDDMM / +DDMMSS+DDDMMSS into degrees."""
    split = max(coords.rfind("+"), coords.rfind("-"))
    if split <= 0:
        raise ValueError(f"malformed coordinates: {coords!r}")
    lat_s, lon_s = coords[:split], coords[split:]

    def to_degrees(text: str, deg_digits: int) -> float:
        sign = -1.0 if text[0] == "-" else 1.0
        digits = text[1:]
        deg = int(digits[:deg_digits])
        minutes = int(digits[deg_digits:deg_digits + 2])
        seconds = int(digits[deg_digits + 2:deg_digits + 4] or 0)
        return sign * (deg + minutes / 60 + seconds / 3600)

    return to_degrees(lat_s, 2), to_degrees(lon_s, 3)


def location_from_timezone(tz_name: str) -> tuple[float, float]:
    tables = ("/usr/share/zoneinfo/zone1970.tab", "/usr/share/zoneinfo/zone.tab")
    for table in tables:
        path = Path(table)
        if not path.exists():
            continue
        for line in path.read_text().splitlines():
            if not line or line.startswith("#"):
                continue
            fields = line.split("\t")
            if len(fields) < 3:
                continue
            # zone1970.tab lists several zone names per row, comma-separated.
            if tz_name in fields[2].split(","):
                return _parse_iso6709(fields[1])
    die(
        f"time zone {tz_name!r} is not in tzdata's zone tables; "
        f"set latitude/longitude in {SETTINGS_PATH}"
    )


def resolve_location(settings: dict, tz_name: str) -> tuple[float, float, str]:
    lat, lon = settings["latitude"], settings["longitude"]
    if lat is not None and lon is not None:
        return float(lat), float(lon), "config"
    if (lat is None) != (lon is None):
        die("set both latitude and longitude, or neither")
    lat, lon = location_from_timezone(tz_name)
    return lat, lon, f"time zone ({tz_name})"
