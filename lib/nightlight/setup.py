"""Consent, activation, and undoing all of it."""

from __future__ import annotations

import subprocess
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from . import conf, hyprsunset, state
from .apply import apply
from .location import system_timezone
from .log import die, info, warn
from .paths import (APP, BIN_LINK, CLI, CONFIG_DIR, HOOK_PATH, HYPRSUNSET_CONF,
                    HYPRSUNSET_UNIT, LEGACY_SETTINGS_PATH, PRE_BACKUP, REPO,
                    SETTINGS_PATH, UNIT_DIR, UNITS)
from .settings import write_default_settings

TIMER = f"{APP}.timer"


def _systemctl(*args: str) -> None:
    subprocess.run(["systemctl", "--user", *args], capture_output=True)


def _install(source: Path, target: Path) -> bool:
    """Copy a unit or hook into place with this checkout's CLI path filled in,
    so it works wherever the plugin was cloned and without anything on PATH."""
    if not source.exists():
        warn(f"missing {source}, skipping")
        return False
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(source.read_text().replace("@CLI@", str(CLI)))
    return True


def _link_is_ours() -> bool:
    return BIN_LINK.is_symlink() and BIN_LINK.resolve() == CLI.resolve()


def autostart_launches_hyprsunset() -> bool:
    path = CONFIG_DIR / "hypr" / "autostart.lua"
    if not path.exists():
        return False
    for line in path.read_text().splitlines():
        stripped = line.strip()
        if stripped.startswith("--"):
            continue
        if "launch_on_start" in stripped and "hyprsunset" in stripped:
            return True
    return False


def disclosure() -> str:
    """Exactly what setup will change, given the state of this machine."""
    if not HYPRSUNSET_CONF.exists():
        conf_note = "Created. You do not currently have one."
    elif conf.is_ours():
        conf_note = "Rewritten. It is already a generated schedule."
    else:
        conf_note = (f"Replaced with a generated schedule. Your current file is copied to\n"
                     f"      {PRE_BACKUP.name}, and `{APP} teardown` puts it back.")

    if SETTINGS_PATH.exists():
        settings_note = "Left alone. You already have one."
    elif LEGACY_SETTINGS_PATH.exists():
        settings_note = f"Created as a copy of {LEGACY_SETTINGS_PATH}."
    else:
        settings_note = "Created with defaults."

    if _link_is_ours():
        link_note = "Already in place."
    elif BIN_LINK.exists() or BIN_LINK.is_symlink():
        link_note = "Skipped: something else already has that name."
    else:
        link_note = f"A symlink, so `{APP}` works from a terminal."

    lines = [
        "Night Light setup",
        "",
        "This changes the following, and nothing else:",
        "",
        f"  {HYPRSUNSET_CONF}",
        f"      {conf_note}",
        "",
        f"  systemctl --user enable --now {HYPRSUNSET_UNIT}",
        "      hyprsunset starts from the unit its own package ships, rather than from",
        "      autostart.lua. Applying a rebuilt schedule means restarting hyprsunset,",
        "      and a uwsm transient scope does not survive a restart driven from a",
        "      systemd timer.",
    ]
    if autostart_launches_hyprsunset():
        lines += [
            "      NOTE: your autostart.lua already launches hyprsunset. Two launch paths",
            "      race for its socket, so remove that line after setup.",
        ]
    lines += [
        "",
        f"  {UNIT_DIR}/{APP}.{{service,timer}}",
        "      A timer that rebuilds the schedule through the day, because sunset moves.",
        "",
        f"  {HOOK_PATH}",
        "      Rebuilds the schedule when the desktop starts.",
        "",
        f"  {SETTINGS_PATH}",
        f"      {settings_note}",
        "",
        f"  {BIN_LINK}",
        f"      {link_note}",
        "",
        "Nothing under /usr/share/omarchy is touched, and nothing reaches the network.",
        "",
        f"Undo all of it with:  {CLI} teardown",
    ]
    return "\n".join(lines)


def setup(*, yes: bool, force: bool) -> int:
    """Disclose every change, get consent, then activate. Nothing before this
    point writes to the user's configuration."""
    if state.is_setup() and not force:
        print(f"Already set up. `{APP} teardown` undoes it, `--force` re-runs it.")
        return 0

    print(disclosure())
    print()

    if not yes:
        if not sys.stdin.isatty():
            die("setup needs a terminal to ask for consent; pass --yes to accept "
                "the changes listed above")
        try:
            reply = input('Type "yes" to make these changes: ').strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            reply = ""
        if reply not in ("yes", "y"):
            print("Nothing was changed.")
            return 1

    record = {
        "version": 1,
        "accepted_at": datetime.now(ZoneInfo(system_timezone())).isoformat(),
        "backed_up_conf": None,
        "hyprsunset_unit_was_enabled": hyprsunset.unit_enabled(),
        "units": [],
        "hook": None,
        "bin_link": None,
    }

    # Never clobber an edited config.
    outcome = write_default_settings()
    if outcome == "adopted":
        info(f"copied your settings from {LEGACY_SETTINGS_PATH}")
    elif outcome == "created":
        info(f"wrote {SETTINGS_PATH}")

    if HYPRSUNSET_CONF.exists() and not conf.is_ours():
        PRE_BACKUP.write_text(HYPRSUNSET_CONF.read_text())
        record["backed_up_conf"] = str(PRE_BACKUP)
        info(f"saved your hyprsunset.conf to {PRE_BACKUP.name}")

    for name in UNITS:
        if _install(REPO / "systemd" / name, UNIT_DIR / name):
            record["units"].append(name)
    _systemctl("daemon-reload")
    _systemctl("enable", "--now", TIMER)

    # hyprsunset from its own unit. A copy already running outside it would
    # hold the CTM protocol and crash-loop the unit into its start limit.
    hyprsunset.clear_stray()
    _systemctl("reset-failed", HYPRSUNSET_UNIT)
    _systemctl("enable", "--now", HYPRSUNSET_UNIT)

    if _install(REPO / "hooks" / f"{APP}.sh", HOOK_PATH):
        HOOK_PATH.chmod(0o755)
        record["hook"] = str(HOOK_PATH)

    if not (BIN_LINK.exists() or BIN_LINK.is_symlink()):
        BIN_LINK.parent.mkdir(parents=True, exist_ok=True)
        BIN_LINK.symlink_to(CLI)
    if _link_is_ours():
        record["bin_link"] = str(BIN_LINK)

    state.write_consent(record)
    return apply(force=True, accept=True)


def teardown(*, force: bool) -> int:
    """Undo everything setup did, including putting the old config back."""
    if not state.is_setup() and not force:
        print("Not set up, so there is nothing to undo.")
        return 0

    record = state.read_consent()

    _systemctl("disable", "--now", TIMER)
    for name in record.get("units") or UNITS:
        (UNIT_DIR / name).unlink(missing_ok=True)
    _systemctl("daemon-reload")

    Path(record.get("hook") or HOOK_PATH).unlink(missing_ok=True)

    if _link_is_ours():
        BIN_LINK.unlink()

    # Put the user's own hyprsunset.conf back, or fall back to Omarchy's default
    # rather than leaving a generated schedule behind with nothing driving it.
    backup = record.get("backed_up_conf")
    if backup and Path(backup).exists():
        HYPRSUNSET_CONF.write_text(Path(backup).read_text())
        Path(backup).unlink(missing_ok=True)
        info("restored your original hyprsunset.conf")
    elif conf.is_ours():
        restored = subprocess.run(
            ["omarchy-refresh-config", "hypr/hyprsunset.conf"], capture_output=True)
        if restored.returncode == 0:
            info("restored Omarchy's default hyprsunset.conf")
        else:
            warn("could not restore hyprsunset.conf; run "
                 "`omarchy refresh config hypr/hyprsunset.conf`")

    # Only give hyprsunset's launch back if we were the ones who took it over.
    if not record.get("hyprsunset_unit_was_enabled", False):
        _systemctl("disable", HYPRSUNSET_UNIT)

    state.clear()
    _systemctl("restart", HYPRSUNSET_UNIT)

    print("Undone. Your settings in", SETTINGS_PATH, "were left alone;")
    print("delete", SETTINGS_PATH.parent, "if you want those gone too.")
    return 0
