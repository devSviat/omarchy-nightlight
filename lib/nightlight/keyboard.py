"""Keyboard backlight that warms with the screen.

Omarchy paints ASUS ROG keyboards in the theme's keyboard.rgb whenever a theme
is set. With keyboard_tint on, that colour is blended towards amber as the
screen warms: the theme colour as-is at 6500K, mostly amber by about 4000K.
"""

from __future__ import annotations

import fcntl
import json
import os
import re
import shlex
import shutil
import subprocess
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from . import state, status
from .apply import gather
from .log import die, info, warn
from .paths import (APP, CLI, KEYBOARD_LOCK_PATH, KEYBOARD_STATE_PATH, MARKER,
                    SETTINGS_PATH, THEME_HOOK_PATH, THEME_KEYBOARD_RGB)

UNTINTED_KELVIN = 6500
# Where the blend reaches pure amber. Past it only the amber itself deepens.
FULL_WARM_KELVIN = 3700
# The amber a temperature maps to, anchored at a few points and interpolated in
# mireds. Hotter than the black-body colour on purpose: keyboard LEDs render a
# real 4000K peach as near-white, and the point is to see the warmth.
AMBER = ((4000, (255, 154, 60)), (2500, (255, 106, 16)), (1000, (255, 60, 0)))

HEX = re.compile(r"^#?([0-9a-fA-F]{6})$")


def available() -> bool:
    return shutil.which("asusctl") is not None


def theme_color() -> str | None:
    try:
        match = HEX.match(THEME_KEYBOARD_RGB.read_text().strip())
    except OSError:
        return None
    return match.group(1).lower() if match else None


def _rgb(hex_: str) -> tuple:
    return tuple(int(hex_[i:i + 2], 16) for i in (0, 2, 4))


def _hex(rgb) -> str:
    return "".join(f"{round(max(0, min(255, c))):02x}" for c in rgb)


def _mix(a, b, weight: float) -> tuple:
    return tuple(x + (y - x) * weight for x, y in zip(a, b))


def _mired(kelvin: float) -> float:
    return 1e6 / kelvin


def amber(kelvin: int) -> tuple:
    if kelvin >= AMBER[0][0]:
        return AMBER[0][1]
    for (hot_k, hot), (cold_k, cold) in zip(AMBER, AMBER[1:]):
        if kelvin >= cold_k:
            span = _mired(cold_k) - _mired(hot_k)
            return _mix(hot, cold, (_mired(kelvin) - _mired(hot_k)) / span)
    return AMBER[-1][1]


def warm_weight(kelvin) -> float:
    """0 when untinted, 1 at FULL_WARM_KELVIN and below. Linear in mireds, the
    same scale the ramp is built on, so the keyboard keeps pace with it."""
    if kelvin is None or kelvin >= UNTINTED_KELVIN:
        return 0.0
    span = _mired(FULL_WARM_KELVIN) - _mired(UNTINTED_KELVIN)
    return min(1.0, (_mired(kelvin) - _mired(UNTINTED_KELVIN)) / span)


def tinted_color(theme: str, kelvin) -> str:
    weight = warm_weight(kelvin)
    if weight == 0.0:
        return theme
    return _hex(_mix(_rgb(theme), amber(kelvin), weight))


def screen_temperature(tonight, now: datetime):
    """What the screen is warmed to now, or None when untinted. The same rule
    the panel uses: day_temp may be numeric, so daytime is read off the clock."""
    mode = state.get_mode()
    if mode == "off":
        return None
    if mode == "on":
        return state.manual_temp(tonight.settings)
    if status.in_daytime(now, tonight.info):
        return None
    active, _ = status.active_and_next(tonight.steps, now)
    return active[1]


def _last_applied() -> dict:
    try:
        last = json.loads(KEYBOARD_STATE_PATH.read_text())
    except (OSError, json.JSONDecodeError):
        return {}
    return last if isinstance(last, dict) else {}


def _boot_id() -> str:
    try:
        return Path("/proc/sys/kernel/random/boot_id").read_text().strip()
    except OSError:
        return ""


def _painted(theme: str, color: str) -> dict:
    # The boot id makes a fresh boot repaint once: the cache outlives a reboot,
    # the colour on the keyboard may not.
    return {"theme": theme, "color": color, "boot": _boot_id()}


def _remember(theme: str, color: str) -> None:
    KEYBOARD_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    KEYBOARD_STATE_PATH.write_text(json.dumps(_painted(theme, color)) + "\n")


@contextmanager
def _exclusive():
    """One keyboard change at a time. Without it a per-minute sync that read
    keyboard_tint just before `keyboard off` flipped it would repaint amber
    after the theme colour went back, and nothing would ever undo that."""
    KEYBOARD_LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(KEYBOARD_LOCK_PATH, "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield


def _paint(color: str) -> bool:
    try:
        result = subprocess.run(["asusctl", "aura", "effect", "static", "-c", color],
                                capture_output=True, text=True, timeout=10)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False
    if result.returncode != 0:
        warn(f"asusctl could not set the keyboard colour: {result.stderr.strip()}")
    return result.returncode == 0


def sync(*, force: bool = False) -> int:
    with _exclusive():
        return _sync(force=force)


def _sync(*, force: bool) -> int:
    """Bring the keyboard in line with the screen. Called every minute by the
    panel, so it talks to asusctl only when the colour actually changes.

    `force` repaints even if nothing changed here: after a theme switch Omarchy
    has just painted the plain theme colour over ours."""
    if not state.is_setup() or not available():
        return 0
    theme = theme_color()
    if theme is None:
        return 0
    tonight = gather()
    if not tonight.settings["keyboard_tint"]:
        restore()
        return 0
    color = tinted_color(theme, screen_temperature(tonight, datetime.now(tonight.tz)))
    if not force and _last_applied() == _painted(theme, color):
        return 0
    if _paint(color):
        _remember(theme, color)
    return 0


def restore() -> None:
    """Put the theme colour back if this left the keyboard tinted. The record
    stays until that works, so a later sync can try again."""
    last = _last_applied()
    if not last:
        return
    theme = theme_color()
    if theme is None or not available():
        return
    if last.get("color") == theme or _paint(theme):
        KEYBOARD_STATE_PATH.unlink(missing_ok=True)


def _write_setting(enabled: bool) -> None:
    """Flip keyboard_tint in the user's config, leaving every other key as it is."""
    try:
        current = json.loads(SETTINGS_PATH.read_text()) if SETTINGS_PATH.exists() else {}
    except json.JSONDecodeError as exc:
        die(f"{SETTINGS_PATH}: {exc}")
    if not isinstance(current, dict):
        die(f"{SETTINGS_PATH}: expected a JSON object")
    current["keyboard_tint"] = enabled
    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    # Replaced in one step, so an interrupted write cannot leave a truncated
    # config that every later run refuses to load.
    staged = SETTINGS_PATH.with_name(SETTINGS_PATH.name + ".tmp")
    staged.write_text(json.dumps(current, indent=2) + "\n")
    os.replace(staged, SETTINGS_PATH.resolve())


def _hook_is_ours() -> bool:
    try:
        return MARKER in THEME_HOOK_PATH.read_text()
    except OSError:
        return False


def _install_hook() -> None:
    if THEME_HOOK_PATH.exists() and not _hook_is_ours():
        warn(f"left {THEME_HOOK_PATH} alone: it is not ours. The keyboard is re-tinted "
             "within a minute of a theme change instead.")
        return
    THEME_HOOK_PATH.parent.mkdir(parents=True, exist_ok=True)
    THEME_HOOK_PATH.write_text(
        "#!/bin/bash\n"
        f"{MARKER}: written by `{APP} keyboard on`, removed by `{APP} keyboard off`.\n"
        "# Omarchy paints the plain theme colour on a theme change; tint it again.\n"
        f"exec {shlex.quote(str(CLI))} keyboard sync --force\n")
    THEME_HOOK_PATH.chmod(0o755)


def _remove_hook() -> None:
    if _hook_is_ours():
        THEME_HOOK_PATH.unlink()


def set_enabled(enabled: bool) -> int:
    if not state.is_setup():
        die(f"not set up yet. Run `{APP} setup` first.")
    if enabled and not available():
        die("keyboard tint needs asusctl, which is not installed")
    with _exclusive():
        _write_setting(enabled)
        if enabled:
            _install_hook()
        else:
            _remove_hook()
        _sync(force=enabled)
    info("keyboard follows the tint" if enabled else "keyboard keeps the theme colour")
    return 0


def remove() -> None:
    """For teardown: hand the keyboard back and drop the hook."""
    with _exclusive():
        restore()
    _remove_hook()
    KEYBOARD_LOCK_PATH.unlink(missing_ok=True)
