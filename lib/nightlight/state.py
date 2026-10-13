"""What the user last chose: the mode, the manual temperature, and consent."""

from __future__ import annotations

import json

from .log import die
from .paths import CONSENT_PATH, MANUAL_TEMP_PATH, MODE_PATH, STATE_DIR
from .settings import MAX_KELVIN, MIN_KELVIN

MODES = ("auto", "on", "off")


def get_mode() -> str:
    """auto follows the ladder; on holds the manual temperature; off holds
    untinted."""
    try:
        mode = MODE_PATH.read_text().strip()
    except OSError:
        return "auto"
    return mode if mode in MODES else "auto"


def set_mode(mode: str) -> None:
    if mode not in MODES:
        die(f"mode must be one of {', '.join(MODES)} (got {mode!r})")
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    MODE_PATH.write_text(mode + "\n")


def manual_temp(settings: dict) -> int:
    """The temperature On holds. Starts out as night_temp and then follows
    whatever was last picked, without touching the schedule's own settings."""
    try:
        kelvin = int(MANUAL_TEMP_PATH.read_text().strip())
    except (OSError, ValueError):
        return settings["night_temp"]
    return kelvin if MIN_KELVIN <= kelvin <= MAX_KELVIN else settings["night_temp"]


def set_manual_temp(kelvin: int) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    MANUAL_TEMP_PATH.write_text(f"{kelvin}\n")


def clear_manual_temp() -> None:
    MANUAL_TEMP_PATH.unlink(missing_ok=True)


def resolve_temp(text: str, current: int) -> int:
    """An absolute "3400" or a relative "+100" / "-100" against `current`.
    Relative moves stop at the limits; an absolute value outside them is an
    error, because that is a typo rather than a nudge."""
    try:
        value = int(text)
    except ValueError:
        die(f"temperature must be Kelvin, or +N / -N (got {text!r})")
    if text[0] in "+-":
        return max(MIN_KELVIN, min(MAX_KELVIN, current + value))
    if not MIN_KELVIN <= value <= MAX_KELVIN:
        die(f"temperature must be between {MIN_KELVIN} and {MAX_KELVIN} K (got {value})")
    return value


def is_setup() -> bool:
    return CONSENT_PATH.exists()


def read_consent() -> dict:
    try:
        return json.loads(CONSENT_PATH.read_text())
    except (OSError, json.JSONDecodeError):
        return {}


def write_consent(record: dict) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    CONSENT_PATH.write_text(json.dumps(record, indent=2) + "\n")


def clear() -> None:
    for path in (CONSENT_PATH, MODE_PATH, MANUAL_TEMP_PATH):
        path.unlink(missing_ok=True)
