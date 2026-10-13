"""Tonight's ladder: the evening ramp, the overnight hold and the way back."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from .log import warn
from .solar import DAWN_ALTITUDES, DUSK_ALTITUDES, fallback_time, sun_times


def _mired(kelvin: float) -> float:
    return 1_000_000.0 / kelvin


def build_schedule(settings: dict, day: date, lat: float, lon: float, tz: ZoneInfo):
    """Return (steps, info). steps is [(datetime, temperature_or_None)] in
    chronological order across tonight; None means an untinted day profile."""
    _, sunset = sun_times(day, lat, lon, tz)
    tomorrow = day + timedelta(days=1)
    sunrise_next, _ = sun_times(tomorrow, lat, lon, tz)

    # The ramp hangs off dusk, not sunset: at sunset it is still light out, and
    # anything visible then reads as the filter firing too early.
    anchor_name = settings["ramp_anchor"]
    _, anchor = sun_times(day, lat, lon, tz, DUSK_ALTITUDES[anchor_name])
    if anchor is None:
        # Somewhere the sun never gets that far below the horizon. Fall back to
        # sunset rather than skipping the evening entirely.
        anchor, anchor_name = sunset, "sunset"

    degenerate = sunset is None or sunrise_next is None
    if sunset is None:
        sunset = fallback_time(day, settings["fallback_sunset"], tz)
    if anchor is None:
        anchor = sunset
    if sunrise_next is None:
        sunrise_next = fallback_time(tomorrow, settings["fallback_sunrise"], tz)

    ramp_start = anchor + timedelta(minutes=settings["ramp_start_offset_min"])
    day_start = sunrise_next + timedelta(minutes=settings["morning_offset_min"])

    step = timedelta(minutes=settings["step_minutes"])
    ramp = _ramp_length(settings, ramp_start, tz)

    # Never let the ramp run into the morning profile.
    latest_end = day_start - step
    if ramp_start >= latest_end:
        warn("night is shorter than one ramp step; emitting a single night profile")
        steps = [(ramp_start, settings["night_temp"])]
        morning, morning_info = _morning_ramp(
            settings, tomorrow, lat, lon, tz, sunrise_next, day_start, ramp_start, step)
        return _finish(steps + morning, day_start, settings), {
            "sunset": sunset, "sunrise": sunrise_next, "degenerate": degenerate,
            "ramp_start": ramp_start, "ramp_end": ramp_start, "day_start": day_start,
            "anchor": anchor, "anchor_name": anchor_name, **morning_info,
        }
    ramp_end = min(ramp_start + ramp, latest_end)

    total = (ramp_end - ramp_start).total_seconds()
    count = max(1, int(round(total / step.total_seconds())))
    m_start, m_end = _mired(settings["evening_temp"]), _mired(settings["night_temp"])
    quantum = settings["round_to_kelvin"]

    power = settings["ramp_curve_power"]
    steps = []
    for i in range(count + 1):
        # Interpolate in mireds, because even steps there read as even steps to
        # the eye. The power curve then biases the movement towards the later
        # part of the evening, so the first hour is barely perceptible.
        fraction = (i / count) ** power
        kelvin = 1_000_000.0 / (m_start + fraction * (m_end - m_start))
        steps.append((ramp_start + i * (ramp_end - ramp_start) / count,
                      int(round(kelvin / quantum) * quantum)))

    morning, morning_info = _morning_ramp(
        settings, tomorrow, lat, lon, tz, sunrise_next, day_start, ramp_end, step)

    return _finish(steps + morning, day_start, settings), {
        "sunset": sunset, "sunrise": sunrise_next, "degenerate": degenerate,
        "ramp_start": ramp_start, "ramp_end": ramp_end, "day_start": day_start,
        "anchor": anchor, "anchor_name": anchor_name, **morning_info,
    }


def _morning_ramp(settings, tomorrow: date, lat: float, lon: float, tz: ZoneInfo,
                  sunrise_next: datetime, day_start: datetime, ramp_end: datetime,
                  step: timedelta):
    """The way back up: steps from the night floor towards the daytime value,
    ending where the untinted day profile takes over. Returns (steps, info).

    It mirrors the evening: anchored to a twilight rather than to sunrise,
    interpolated in mireds, and on the same curve -- which here means holding
    the warm value while it is still dark and doing most of the brightening in
    the last stretch before sunrise. Nothing here steps either: the first rung
    is the floor already on screen, and the day profile takes over from the last.
    """
    name = settings["morning_anchor"]
    info = {"morning_anchor": None, "morning_anchor_name": None,
            "morning_start": day_start}
    if name is None:
        return [], info

    dawn, _ = sun_times(tomorrow, lat, lon, tz, DAWN_ALTITUDES[name])
    if dawn is None:
        # The sun never gets that far below the horizon tonight; lean on the
        # minimum length instead so the morning still has a ramp.
        dawn, name = sunrise_next, "sunrise"

    minimum = timedelta(minutes=settings["min_ramp_minutes"])
    start = min(dawn, day_start - minimum)
    # Never run into the evening ramp; it owns the clock up to ramp_end.
    start = max(start, ramp_end + step)
    info.update({"morning_anchor": dawn, "morning_anchor_name": name,
                 "morning_start": start})
    if start >= day_start - step:
        warn("no room for a morning ramp between the evening floor and sunrise")
        return [], info

    total = (day_start - start).total_seconds()
    count = max(1, int(round(total / step.total_seconds())))
    m_start, m_end = _mired(settings["night_temp"]), _mired(settings["evening_temp"])
    quantum = settings["round_to_kelvin"]
    power = settings["ramp_curve_power"]
    steps = []
    for i in range(count):
        fraction = (i / count) ** power
        kelvin = 1_000_000.0 / (m_start + fraction * (m_end - m_start))
        steps.append((start + i * (day_start - start) / count,
                      int(round(kelvin / quantum) * quantum)))
    return steps, info


def _ramp_length(settings, ramp_start: datetime, tz: ZoneInfo) -> timedelta:
    """How long the ramp runs for.

    With full_tint_by set, the ramp ends at that clock time, so its length
    tracks the season: it stretches through winter when dusk is early and
    compresses in summer when dusk is late, always reaching the floor at the
    same hour. That is usually what someone means by "warm by nine" -- the hour
    is about their evening, not about the sun.
    """
    target = settings["full_tint_by"]
    minimum = timedelta(minutes=settings["min_ramp_minutes"])
    if target is None:
        return timedelta(minutes=settings["ramp_minutes"])

    hh, mm = (int(part) for part in target.split(":"))
    end = ramp_start.replace(hour=hh, minute=mm, second=0, microsecond=0)
    if end <= ramp_start:
        # An early-hours target means tomorrow; anything else is a target that
        # has already passed by the time it gets dark, so keep a short ramp
        # rather than inverting it.
        if hh < 12:
            end += timedelta(days=1)
        else:
            return minimum
    return max(end - ramp_start, minimum)


def _finish(steps, day_start, settings):
    """Append the morning profile and collapse anything that repeats."""
    steps = list(steps) + [(day_start, settings["day_temp"])]
    collapsed = []
    for when, temp in steps:
        key = when.strftime("%H:%M")
        if collapsed and collapsed[-1][0].strftime("%H:%M") == key:
            collapsed[-1] = (when, temp)  # later entry wins on a collision
            continue
        if collapsed and collapsed[-1][1] == temp:
            continue  # same temperature as the previous step, so it is a no-op
        collapsed.append((when, temp))
    return collapsed
