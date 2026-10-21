"""The user's settings: defaults, loading and validation."""

from __future__ import annotations

import json

from .log import die, warn
from .paths import LEGACY_SETTINGS_PATH, SETTINGS_PATH
from .solar import DAWN_ALTITUDES, DUSK_ALTITUDES

# hyprsunset rejects anything outside this range.
MIN_KELVIN = 1000
MAX_KELVIN = 20000

DEFAULTS = {
    # null => derive from the system time zone via tzdata's zone1970.tab
    "latitude": None,
    "longitude": None,
    # Kelvin at the start of the evening ramp, and at its deepest point.
    # The start defaults to the daytime value so the ramp begins from no tint
    # rather than stepping straight to a visible one.
    "evening_temp": 6500,
    "night_temp": 3000,
    # null => untinted (hyprsunset identity matrix) during the day.
    "day_temp": None,
    # Where the evening ramp is anchored: "sunset", "civil_dusk",
    # "nautical_dusk" or "astronomical_dusk". Sunset is still daylight; civil
    # dusk is about when you reach for a lamp.
    "ramp_anchor": "civil_dusk",
    # The clock time by which the screen should be fully warm. The ramp runs
    # from the anchor to here, so its length follows the season instead of
    # being fixed: dusk moves by well over an hour across the year, and a fixed
    # duration would land full tint near midnight in summer. Set it to null to
    # use ramp_minutes instead.
    "full_tint_by": "21:00",
    # Ramp geometry, in minutes.
    "ramp_start_offset_min": 0,   # relative to the anchor; negative starts earlier
    "ramp_minutes": 300,          # only used when full_tint_by is null
    "min_ramp_minutes": 45,       # floor, for when dusk falls close to the target
    "step_minutes": 20,           # granularity of the ladder
    # Shape of the ramp. 1.0 is a straight line in mireds; higher values hold
    # near the daytime value for longer and do most of the warming later, so
    # nothing is noticeable while there is still light outside.
    "ramp_curve_power": 2.0,
    "morning_offset_min": 0,      # relative to sunrise; when day returns
    # Where the morning ramp back to daylight starts: "civil_dawn",
    # "nautical_dawn" or "astronomical_dawn". null returns to day in a single
    # step at sunrise. The ramp runs from the anchor to sunrise (plus
    # morning_offset_min), holds warm while it is still dark and does most of
    # its brightening close to sunrise, mirroring the evening.
    "morning_anchor": None,
    # Used only when the sun does not rise or set (high latitudes).
    "fallback_sunset": "18:00",
    "fallback_sunrise": "06:00",
    # Round emitted temperatures to this multiple, to keep the file readable.
    "round_to_kelvin": 50,
    # Warm the ASUS keyboard backlight along with the screen. Needs asusctl.
    "keyboard_tint": False,
}



def load_settings() -> dict:
    settings = dict(DEFAULTS)
    if SETTINGS_PATH.exists():
        try:
            user = json.loads(SETTINGS_PATH.read_text())
        except json.JSONDecodeError as exc:
            die(f"{SETTINGS_PATH}: {exc}")
        unknown = set(user) - set(DEFAULTS)
        if unknown:
            warn(f"ignoring unknown setting(s): {', '.join(sorted(unknown))}")
        settings.update({k: v for k, v in user.items() if k in DEFAULTS})
    validate(settings)
    return settings


def validate(s: dict) -> None:
    for key in ("evening_temp", "night_temp"):
        if not (MIN_KELVIN <= s[key] <= MAX_KELVIN):
            die(f"{key} must be between 1000 and 20000 K (got {s[key]})")
    if s["day_temp"] is not None and not (MIN_KELVIN <= s["day_temp"] <= MAX_KELVIN):
        die(f"day_temp must be between 1000 and 20000 K (got {s['day_temp']})")
    if s["ramp_minutes"] < 1:
        die("ramp_minutes must be at least 1")
    if not (1 <= s["step_minutes"] <= s["ramp_minutes"]):
        die("step_minutes must be between 1 and ramp_minutes")
    if s["round_to_kelvin"] < 1:
        die("round_to_kelvin must be at least 1")
    if s["ramp_anchor"] not in DUSK_ALTITUDES:
        die(f"ramp_anchor must be one of {', '.join(DUSK_ALTITUDES)} "
            f"(got {s['ramp_anchor']!r})")
    if s["morning_anchor"] is not None and s["morning_anchor"] not in DAWN_ALTITUDES:
        die(f"morning_anchor must be null or one of {', '.join(DAWN_ALTITUDES)} "
            f"(got {s['morning_anchor']!r})")
    if not (0.1 <= s["ramp_curve_power"] <= 10):
        die(f"ramp_curve_power must be between 0.1 and 10 "
            f"(got {s['ramp_curve_power']})")
    if s["full_tint_by"] is not None:
        try:
            hh, mm = (int(part) for part in s["full_tint_by"].split(":"))
            assert 0 <= hh < 24 and 0 <= mm < 60
        except (ValueError, AssertionError, AttributeError):
            die(f"full_tint_by must be HH:MM or null (got {s['full_tint_by']!r})")
    if not isinstance(s["keyboard_tint"], bool):
        die(f"keyboard_tint must be true or false (got {s['keyboard_tint']!r})")
    if s["min_ramp_minutes"] < 1:
        die("min_ramp_minutes must be at least 1")
    for key in ("fallback_sunset", "fallback_sunrise"):
        try:
            hh, mm = (int(part) for part in s[key].split(":"))
            assert 0 <= hh < 24 and 0 <= mm < 60
        except (ValueError, AssertionError):
            die(f"{key} must be HH:MM (got {s[key]!r})")



def write_default_settings() -> str | None:
    """Put a starting config in place unless there is one. Returns what it
    did -- "created" or "adopted" -- or None if it left an existing file alone."""
    if SETTINGS_PATH.exists():
        return None
    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    if LEGACY_SETTINGS_PATH.exists():
        SETTINGS_PATH.write_text(LEGACY_SETTINGS_PATH.read_text())
        return "adopted"
    SETTINGS_PATH.write_text(json.dumps(DEFAULTS, indent=2) + "\n")
    return "created"
