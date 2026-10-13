"""Talking to the running hyprsunset, and restarting it."""

from __future__ import annotations

import subprocess
import time

from .log import warn
from .paths import HYPRSUNSET_UNIT as UNIT

HOLD_TIME = "00:00"


def running() -> bool:
    return subprocess.run(["pgrep", "-x", "hyprsunset"],
                          capture_output=True).returncode == 0


def unit_active() -> bool:
    out = subprocess.run(["systemctl", "--user", "is-active", UNIT],
                         capture_output=True, text=True)
    return out.stdout.strip() == "active"


def unit_enabled() -> bool:
    out = subprocess.run(["systemctl", "--user", "is-enabled", UNIT],
                         capture_output=True, text=True)
    return out.stdout.strip() == "enabled"


def _ipc(*args: str) -> str | None:
    try:
        out = subprocess.run(["hyprctl", "hyprsunset", *args],
                             capture_output=True, text=True, timeout=3)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    return out.stdout.strip() if out.returncode == 0 else None


def current_temperature() -> int | None:
    reply = _ipc("temperature")
    return int(reply) if reply and reply.isdigit() else None


def loaded_profile() -> dict | None:
    """The profile hyprsunset is currently on, out of the ones it read at
    startup: {"time": "HH:MM", "temperature": Kelvin, or None for identity}.
    That can lag behind the file on disk, which it never re-reads."""
    reply = _ipc("profile")
    if not reply:
        return None
    fields = {}
    for line in reply.splitlines():
        key, sep, value = line.partition(":")
        if sep:
            fields[key.strip().lower()] = value.strip()
    try:
        identity = fields["identity"] == "true"
        return {"time": fields["time"],
                "temperature": None if identity else int(fields["temperature"])}
    except (KeyError, ValueError):
        return None


def set_live(temperature) -> bool:
    """Change what is on screen now, without a restart. It lasts until
    hyprsunset next switches profile, so the config has to agree with it."""
    if temperature is None:
        reply = _ipc("identity", "true")
    else:
        reply = _ipc("temperature", str(temperature))
    return reply is not None and "invalid" not in reply.lower()


def clear_stray() -> None:
    """Stop a hyprsunset running outside the unit (by hand, or through uwsm
    from `omarchy toggle nightlight`). It holds the compositor's CTM protocol,
    so the unit's own copy exits with "A CTM manager is already running" and
    systemd soon refuses to start it at all."""
    if unit_active() or not running():
        return
    subprocess.run(["pkill", "-x", "hyprsunset"], capture_output=True)
    for _ in range(25):
        if not running():
            break
        time.sleep(0.2)


def restart() -> bool:
    """Reload the config. hyprsunset reads it only at startup.

    This deliberately does not go through omarchy-restart-hyprsunset. That
    relaunches via uwsm, which asks the user manager for a transient scope --
    and a scope created from inside a systemd service does not outlive the
    service that created it. Run from the timer, hyprsunset comes up, answers
    on its socket, and is then killed the moment the oneshot exits. The unit
    that the hyprsunset package ships has no such problem, so drive that.
    """
    if unit_active():
        subprocess.run(["systemctl", "--user", "restart", UNIT], capture_output=True)
    elif running():
        # Started by hand or by `omarchy toggle nightlight`, so it is outside
        # systemd's control. Clear it and let the unit take ownership; the unit
        # may already have hit its start limit against that copy.
        clear_stray()
        subprocess.run(["systemctl", "--user", "reset-failed", UNIT], capture_output=True)
        subprocess.run(["systemctl", "--user", "start", UNIT], capture_output=True)
    else:
        return False  # nothing to reload; the new schedule applies at next login

    if _wait():
        return True
    warn("hyprsunset did not come back after the restart")
    return False


def _wait(timeout: float = 10.0) -> bool:
    """Poll until the relaunched hyprsunset is up and answering on its socket."""
    deadline = time.monotonic() + timeout
    seen = False
    while time.monotonic() < deadline:
        if running():
            seen = True
            # Answering IPC means it is past startup, so the scope handoff is done.
            if current_temperature() is not None:
                return True
        time.sleep(0.2)
    return seen
