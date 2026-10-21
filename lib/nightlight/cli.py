"""Sunset-tracked night light for Omarchy.

hyprsunset only understands wall-clock profiles, so this generates a ladder of
them: a ramp that starts at local dusk and warms the screen in steps through
the evening, holds overnight, and returns to an untinted display at sunrise.
The ladder is regenerated daily because sunset moves.

Location comes from the system time zone by default -- tzdata's zone1970.tab
carries a representative lat/long for every zone -- so changing the time zone
moves the schedule with it. Override it in the config file if you want the
exact coordinates for where you actually are.

Writes ~/.config/hypr/hyprsunset.conf, which is Omarchy's documented extension
point for this. Nothing under /usr/share/omarchy is touched.
"""

from __future__ import annotations

import argparse
import json
from datetime import date, datetime

from . import keyboard, setup as setup_, state, status
from .apply import apply, gather
from .log import info
from .paths import APP


def cmd_apply(args) -> int:
    return apply(force=args.force)


def cmd_status(args) -> int:
    tonight = gather()
    payload = status.status_payload(tonight, datetime.now(tonight.tz))
    if args.json:
        print(json.dumps(payload))
    else:
        status.print_status(tonight, payload)
    return 0


def cmd_show(args) -> int:
    tonight = gather(date.fromisoformat(args.date) if args.date else None)
    facts = tonight.info
    if args.json:
        print(json.dumps(status.ladder_payload(tonight, datetime.now(tonight.tz))))
        return 0
    print(f"# {tonight.day}  {tonight.tz_name}  {tonight.lat:.4f},{tonight.lon:.4f} "
          f"(from {tonight.source})")
    print(f"# sunset {facts['sunset'].strftime('%H:%M')}, "
          f"sunrise {facts['sunrise'].strftime('%H:%M')}"
          + ("  [estimated]" if facts["degenerate"] else ""))
    for when, temp in tonight.steps:
        print(f"{when.strftime('%a %H:%M')}   {'day' if temp is None else f'{temp}K'}")
    return 0


def _switch(mode: str) -> int:
    previous = state.get_mode()
    state.set_mode(mode)
    return apply(live=previous != "auto")


def cmd_mode(args) -> int:
    kelvin = getattr(args, "kelvin", None)
    if kelvin is not None:
        settings = gather().settings
        state.set_manual_temp(state.resolve_temp(kelvin, state.manual_temp(settings)))
    return _switch(args.mode)


def cmd_toggle(args) -> int:
    return _switch("auto" if state.get_mode() == "off" else "off")


def cmd_temp(args) -> int:
    settings = gather().settings
    current = state.manual_temp(settings)
    if args.kelvin is None:
        print(current)
        return 0
    if args.kelvin == "reset":
        state.clear_manual_temp()
        kelvin = settings["night_temp"]
    else:
        kelvin = state.resolve_temp(args.kelvin, current)
        state.set_manual_temp(kelvin)
    if state.get_mode() == "on":
        return apply(live=True)
    info(f"On will hold {kelvin}K")
    return 0


def cmd_keyboard(args) -> int:
    if args.action == "sync":
        return keyboard.sync(force=args.force)
    if args.action in ("on", "off"):
        return keyboard.set_enabled(args.action == "on")
    enabled = gather().settings["keyboard_tint"]
    print("on" if enabled else "off")
    return 0


def cmd_setup(args) -> int:
    if args.print_only:
        print(setup_.disclosure())
        return 0
    code = setup_.setup(yes=args.yes, force=args.force)
    if code == 0:
        print()
        cmd_status(argparse.Namespace(json=False))
    return code


def cmd_teardown(args) -> int:
    return setup_.teardown(force=args.force)


def main() -> int:
    parser = argparse.ArgumentParser(
        prog=APP, description="Sunset-tracked night light for Omarchy.")
    sub = parser.add_subparsers(dest="command")

    status_ = sub.add_parser("status", help="what is on screen now, and what is next")
    status_.add_argument("--json", action="store_true")
    status_.set_defaults(func=cmd_status)

    show = sub.add_parser("show", help="print tonight's ladder without writing")
    show.add_argument("--date", help="a different date, YYYY-MM-DD")
    show.add_argument("--json", action="store_true")
    show.set_defaults(func=cmd_show)

    auto = sub.add_parser("auto", help="follow the sunset ramp")
    auto.set_defaults(func=cmd_mode, mode="auto")

    on = sub.add_parser("on", help="hold a temperature until `auto`")
    on.add_argument("kelvin", nargs="?", help="hold this instead: Kelvin, or +N / -N")
    on.set_defaults(func=cmd_mode, mode="on")

    off = sub.add_parser("off", help="hold untinted until `auto`")
    off.set_defaults(func=cmd_mode, mode="off")

    toggle = sub.add_parser("toggle", help="off if tinting, back to auto if off")
    toggle.set_defaults(func=cmd_toggle)

    temp = sub.add_parser("temp", help="the temperature `on` holds; print it, or set it")
    temp.add_argument("kelvin", nargs="?",
                      help="Kelvin, +N / -N, or `reset` to go back to night_temp")
    temp.set_defaults(func=cmd_temp)

    kbd = sub.add_parser("keyboard",
                         help="warm the ASUS keyboard backlight with the screen")
    kbd.add_argument("action", nargs="?", choices=("on", "off", "sync"),
                     help="on / off to choose; sync to repaint now. Prints the choice without one")
    kbd.add_argument("--force", action="store_true",
                     help="with sync: repaint even if the colour has not changed")
    kbd.set_defaults(func=cmd_keyboard)

    apply_ = sub.add_parser("apply", help="recompute tonight and load it (the timer does this)")
    apply_.add_argument("--force", action="store_true",
                        help="restart hyprsunset even if nothing changed")
    apply_.set_defaults(func=cmd_apply)

    setup = sub.add_parser(
        "setup", help="show what would change, then activate once you agree")
    setup.add_argument("--yes", action="store_true",
                       help="accept the listed changes without prompting")
    setup.add_argument("--print", dest="print_only", action="store_true",
                       help="print what would change and exit, changing nothing")
    setup.add_argument("--force", action="store_true", help="re-run even if set up")
    setup.set_defaults(func=cmd_setup)

    teardown = sub.add_parser("teardown", help="undo everything setup did")
    teardown.add_argument("--force", action="store_true",
                          help="run even if no consent record is present")
    teardown.set_defaults(func=cmd_teardown)

    args = parser.parse_args()
    if not getattr(args, "func", None):
        parser.print_help()
        return 1
    return args.func(args)
