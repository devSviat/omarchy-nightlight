"""Sunrise, sunset and the twilights for a date and a place."""

from __future__ import annotations

import math
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

# NOAA's low-precision sunrise equation. Good to a minute or two, which is far
# below the granularity anything here cares about.

_J2000 = 2451545.0
_OBLIQUITY = math.radians(23.4397)
# Solar altitudes, in degrees. Sunset is the refraction-corrected disc; the
# twilights are the standard definitions. Civil dusk is roughly when you would
# want a lamp on indoors; by nautical dusk it is properly dark outside.
DUSK_ALTITUDES = {
    "sunset": -0.833,
    "civil_dusk": -6.0,
    "nautical_dusk": -12.0,
    "astronomical_dusk": -18.0,
}
# The same altitudes on the way up. Civil dawn is when it is light enough to
# see outside; by then a warm screen reads as yellow rather than cosy.
DAWN_ALTITUDES = {
    "civil_dawn": -6.0,
    "nautical_dawn": -12.0,
    "astronomical_dawn": -18.0,
}
_HORIZON = math.radians(DUSK_ALTITUDES["sunset"])


def _julian_from_ordinal(day: date) -> float:
    """Julian date at 12:00 UTC on the given calendar date."""
    return day.toordinal() + 1721425.0


def _julian_to_datetime(jd: float, tz: ZoneInfo) -> datetime:
    unix = (jd - 2440587.5) * 86400.0
    return datetime.fromtimestamp(unix, tz=timezone.utc).astimezone(tz)


def _solar_events(n: int, lat: float, lon: float,
                  altitude_deg: float = DUSK_ALTITUDES["sunset"]) -> tuple[float, float] | None:
    """Return (julian_rise, julian_set) for solar cycle n at the given solar
    altitude, or None if the sun never reaches it that day."""
    lw = -lon  # the equation wants west-positive longitude
    j_star = n + 0.0009 + lw / 360.0
    mean_anomaly = math.radians((357.5291 + 0.98560028 * j_star) % 360.0)
    center = (
        1.9148 * math.sin(mean_anomaly)
        + 0.0200 * math.sin(2 * mean_anomaly)
        + 0.0003 * math.sin(3 * mean_anomaly)
    )
    ecliptic_lon = math.radians(
        (math.degrees(mean_anomaly) + center + 180.0 + 102.9372) % 360.0
    )
    transit = (
        _J2000
        + j_star
        + 0.0053 * math.sin(mean_anomaly)
        - 0.0069 * math.sin(2 * ecliptic_lon)
    )
    declination = math.asin(math.sin(ecliptic_lon) * math.sin(_OBLIQUITY))
    phi = math.radians(lat)
    numerator = (math.sin(math.radians(altitude_deg))
                 - math.sin(phi) * math.sin(declination))
    denominator = math.cos(phi) * math.cos(declination)
    if denominator == 0:
        return None
    cos_hour_angle = numerator / denominator
    if not -1.0 <= cos_hour_angle <= 1.0:
        return None  # polar day or polar night
    hour_angle = math.degrees(math.acos(cos_hour_angle))
    return transit - hour_angle / 360.0, transit + hour_angle / 360.0


def sun_times(day: date, lat: float, lon: float, tz: ZoneInfo,
              altitude_deg: float = DUSK_ALTITUDES["sunset"]):
    """Local (rise, set) for the given local date at the given solar altitude,
    or (None, None) if the sun never reaches it. The default is sunrise and
    sunset; pass a twilight altitude for dawn and dusk."""
    n0 = round(_julian_from_ordinal(day) - _J2000 - 0.0009 + lon / 360.0)
    # The cycle number can land a day either side; nudge until the transit
    # falls on the date we were asked about.
    for n in (n0, n0 - 1, n0 + 1, n0 - 2, n0 + 2):
        events = _solar_events(n, lat, lon, altitude_deg)
        if events is None:
            return None, None
        rise, sets = (_julian_to_datetime(jd, tz) for jd in events)
        midpoint = _julian_to_datetime((events[0] + events[1]) / 2, tz)
        if midpoint.date() == day:
            return rise, sets
    return None, None


def fallback_time(day: date, hhmm: str, tz: ZoneInfo) -> datetime:
    hh, mm = (int(part) for part in hhmm.split(":"))
    return datetime(day.year, day.month, day.day, hh, mm, tzinfo=tz)
