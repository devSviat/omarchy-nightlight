"""What is scheduled right now, for people and for the panel."""

from __future__ import annotations

from datetime import datetime

from . import conf, hyprsunset, state
from .apply import Tonight
from .log import warn
from .paths import APP


def _minutes(when) -> int:
    return when.hour * 60 + when.minute


def in_daytime(now: datetime, info) -> bool:
    """True between the return to day and the next evening ramp, on the same
    HH:MM cycle hyprsunset follows. A numeric day_temp makes the day profile
    a temperature too, so "not tinted" cannot be read off the value alone."""
    now_m, day_m, ramp_m = _minutes(now), _minutes(info["day_start"]), _minutes(info["ramp_start"])
    if day_m <= ramp_m:
        return day_m <= now_m < ramp_m
    return now_m >= day_m or now_m < ramp_m


def active_and_next(steps, now: datetime):
    """Walk the cycle to find which profile is live and which comes next."""
    by_clock = sorted(steps, key=lambda item: item[0].strftime("%H:%M"))
    active, upcoming = by_clock[-1], by_clock[0]
    for step in by_clock:
        if _minutes(step[0]) <= _minutes(now):
            active = step
        else:
            upcoming = step
            break
    return active, upcoming


def ladder_payload(tonight: Tonight, now: datetime) -> dict:
    info, settings = tonight.info, tonight.settings
    active, _ = active_and_next(tonight.steps, now)
    active_key = active[0].strftime("%H:%M")
    return {
        "date": tonight.day.isoformat(),
        "timezone": tonight.tz_name,
        "sunset": info["sunset"].strftime("%H:%M"),
        "sunrise": info["sunrise"].strftime("%H:%M"),
        "estimated": info["degenerate"],
        "mode": state.get_mode(),
        # Phase boundaries, so a UI can describe tonight without re-deriving
        # them from the steps.
        "anchor_name": info["anchor_name"],
        "ramp_start": info["ramp_start"].strftime("%H:%M"),
        "ramp_end": info["ramp_end"].strftime("%H:%M"),
        "morning_start": (info["morning_start"].strftime("%H:%M")
                          if info.get("morning_anchor_name") else None),
        "day_start": info["day_start"].strftime("%H:%M"),
        "evening_temp": settings["evening_temp"],
        "night_temp": settings["night_temp"],
        "day_temp": settings["day_temp"],
        "steps": [
            {
                "time": when.strftime("%H:%M"),
                "day": when.strftime("%a"),
                "temperature": temp,
                "current": when.strftime("%H:%M") == active_key,
            }
            for when, temp in tonight.steps
        ],
    }


def status_payload(tonight: Tonight, now: datetime) -> dict:
    info, settings = tonight.info, tonight.settings
    active, upcoming = active_and_next(tonight.steps, now)
    return {
        "timezone": tonight.tz_name,
        "latitude": round(tonight.lat, 4),
        "longitude": round(tonight.lon, 4),
        "location_source": tonight.source,
        "sunset": info["sunset"].strftime("%H:%M"),
        "sunrise": info["sunrise"].strftime("%H:%M"),
        "estimated": info["degenerate"],
        "running": hyprsunset.running(),
        "scheduled_temperature": active[1],
        "scheduled_since": active[0].strftime("%H:%M"),
        "next_temperature": upcoming[1],
        "next_at": upcoming[0].strftime("%H:%M"),
        "actual_temperature": hyprsunset.current_temperature(),
        "day_temp": settings["day_temp"],
        "evening_temp": settings["evening_temp"],
        "night_temp": settings["night_temp"],
        "manual_temp": state.manual_temp(settings),
        "generated": conf.is_ours(),
        "mode": state.get_mode(),
        "daytime": in_daytime(now, info),
        "setup": state.is_setup(),
        "ladder": ladder_payload(tonight, now),
    }


def print_status(tonight: Tonight, payload: dict) -> None:
    def label(temp):
        return "off (untinted)" if temp is None else f"{temp}K"

    scheduled = f"{label(payload['scheduled_temperature'])} since {payload['scheduled_since']}"
    if not payload["setup"]:
        print("state       NOT SET UP -- nothing has been changed on this machine.")
        print(f"            Run `{APP} setup` to see what it would change.")
        print()
    print(f"time zone   {tonight.tz_name}")
    print(f"location    {tonight.lat:.4f}, {tonight.lon:.4f}  (from {tonight.source})")
    print(f"sun         rises {payload['sunrise']}, sets {payload['sunset']}"
          + ("  [estimated]" if payload["estimated"] else ""))
    print(f"hyprsunset  {'running' if payload['running'] else 'not running'}"
          + (f", currently {payload['actual_temperature']}K"
             if payload["actual_temperature"] else ""))
    if payload["mode"] == "off":
        print(f"state       OFF -- untinted until `{APP} auto`")
        print(f"would be    {scheduled}")
    elif payload["mode"] == "on":
        print(f"state       ON -- held at {payload['manual_temp']}K until `{APP} auto`")
        print(f"would be    {scheduled}")
    else:
        print(f"scheduled   {scheduled}")
        print(f"next        {label(payload['next_temperature'])} at {payload['next_at']}")
    if payload["setup"] and not payload["generated"]:
        warn(f"hyprsunset.conf is not the generated one; run `{APP} apply`")
