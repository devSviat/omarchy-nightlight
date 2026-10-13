"""Make hyprsunset agree with the chosen mode: write its config, then get the
running process onto it."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from zoneinfo import ZoneInfo

from . import conf, hyprsunset, state
from .ladder import build_schedule
from .location import resolve_location, system_timezone
from .log import die, info
from .paths import APP, HYPRSUNSET_CONF, MARKER
from .settings import load_settings


@dataclass
class Tonight:
    settings: dict
    tz_name: str
    tz: ZoneInfo
    lat: float
    lon: float
    source: str
    day: date
    steps: list
    info: dict


def gather(day: date | None = None) -> Tonight:
    settings = load_settings()
    tz_name = system_timezone()
    tz = ZoneInfo(tz_name)
    lat, lon, source = resolve_location(settings, tz_name)
    today = day or datetime.now(tz).date()
    steps, info_ = build_schedule(settings, today, lat, lon, tz)
    return Tonight(settings, tz_name, tz, lat, lon, source, today, steps, info_)


def apply(*, force: bool = False, accept: bool = False, live: bool = False) -> int:
    """`live` asks for a hold to be changed in place rather than by restarting
    hyprsunset, which blanks the tint for a moment. Only a hold can be: a
    loaded ladder would overrule the change at its next rung."""
    # The only thing in here that writes to the user's config, so this is where
    # consent is enforced. `setup` passes accept once the user has agreed.
    if not state.is_setup() and not accept:
        die("not set up yet, so nothing has been changed.\n"
            f"       Run `{APP} setup` to see what it would change and agree to it.")
    tonight = gather()
    mode = state.get_mode()
    held = state.manual_temp(tonight.settings) if mode == "on" else None
    if mode == "auto":
        body = conf.render_ladder(tonight.steps, tonight.settings, tonight.info,
                                  tonight.lat, tonight.lon, tonight.source, tonight.tz_name)
    else:
        body = conf.render_hold(tonight.tz_name, held)

    existing = HYPRSUNSET_CONF.read_text() if HYPRSUNSET_CONF.exists() else None
    # setup has already saved the user's own file by the time it calls this.
    if existing is not None and MARKER not in existing and not accept:
        backup = HYPRSUNSET_CONF.with_suffix(
            f".conf.bak.{datetime.now(tonight.tz).strftime('%Y%m%d%H%M%S')}")
        backup.write_text(existing)
        info(f"backed up your existing hyprsunset.conf to {backup.name}")

    changed = existing != body
    if changed:
        HYPRSUNSET_CONF.parent.mkdir(parents=True, exist_ok=True)
        HYPRSUNSET_CONF.write_text(body)

    if mode == "auto":
        if not (changed or force):
            info("schedule unchanged")
            return 0
        restarted = hyprsunset.restart()
        facts = tonight.info
        info(f"wrote {len(tonight.steps)} profiles for {tonight.day} "
             f"(sunset {facts['sunset'].strftime('%H:%M')}, "
             f"day returns {facts['day_start'].strftime('%H:%M')})"
             + ("; hyprsunset restarted" if restarted else ""))
        return 0

    # Coming off a ladder always takes a restart, whatever hyprsunset reports:
    # a ladder can have a rung at midnight that looks just like a hold.
    was_ladder = existing is not None and existing.count("profile {") > 1
    restarted = _hold(held, live=live, force=force or was_ladder)
    what = "off: the display stays untinted" if held is None else f"on: held at {held}K"
    info(what + ("; hyprsunset restarted" if restarted else ""))
    return 0


def _hold(temperature, *, live: bool, force: bool) -> bool:
    """Get the running hyprsunset onto a hold. True if that took a restart."""
    loaded = hyprsunset.loaded_profile()
    is_hold = loaded is not None and loaded["time"] == hyprsunset.HOLD_TIME
    current = is_hold and loaded["temperature"] == temperature
    if not force and (current or (live and is_hold)):
        # A live change leaves hyprsunset holding the old value in memory, and
        # it re-applies that at midnight. The timer's pass late in the evening
        # comes back through here without `live` and restarts it.
        if hyprsunset.set_live(temperature):
            return False
    return hyprsunset.restart()
