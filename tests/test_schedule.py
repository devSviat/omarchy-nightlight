"""Tests for the parts that can be silently wrong: the solar math and the
shape of the generated ladder.

Run with:  python3 -m pytest tests/ -q      (or: python3 tests/test_schedule.py)
"""

import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "lib"))

from nightlight import conf, ladder, location, paths, solar, status  # noqa: E402
from nightlight import settings as cfg  # noqa: E402


def settings(**overrides):
    s = dict(cfg.DEFAULTS)
    s.update(overrides)
    return s


def minutes(when):
    return when.hour * 60 + when.minute


# ------------------------------------------------------------------- solar

# Reference sunrise/sunset, from published almanac times. The low-precision
# equation is good to a minute or two, so allow three.
SOLAR_CASES = [
    # (tz, lat, lon, date, sunrise, sunset)
    ("Australia/Brisbane", -27.4667, 153.0333, date(2026, 8, 21), "06:13", "17:30"),
    ("Australia/Brisbane", -27.4667, 153.0333, date(2026, 6, 21), "06:38", "17:02"),
    ("Australia/Brisbane", -27.4667, 153.0333, date(2026, 12, 21), "04:51", "18:43"),
    # Northern hemisphere, and a zone that observes DST.
    ("Europe/London", 51.5074, -0.1278, date(2026, 6, 21), "04:43", "21:21"),
    ("Europe/London", 51.5074, -0.1278, date(2026, 12, 21), "08:04", "15:53"),
    # Crossing the prime meridian the other way, and a large UTC offset.
    ("America/New_York", 40.7128, -74.0060, date(2026, 3, 21), "07:00", "19:12"),
]


def parse_hhmm(text):
    hh, mm = (int(p) for p in text.split(":"))
    return hh * 60 + mm


def test_solar_times_match_almanac():
    for tz_name, lat, lon, day, expect_rise, expect_set in SOLAR_CASES:
        tz = ZoneInfo(tz_name)
        rise, sets = solar.sun_times(day, lat, lon, tz)
        assert rise is not None and sets is not None, f"{tz_name} {day}: no events"
        assert rise.date() == day, f"{tz_name} {day}: sunrise landed on {rise.date()}"
        assert sets.date() == day, f"{tz_name} {day}: sunset landed on {sets.date()}"
        for label, got, expected in (("sunrise", rise, expect_rise),
                                     ("sunset", sets, expect_set)):
            delta = abs(minutes(got) - parse_hhmm(expected))
            assert delta <= 3, (
                f"{tz_name} {day} {label}: got {got:%H:%M}, expected ~{expected}")


def test_polar_day_and_night_report_no_events():
    tz = ZoneInfo("Europe/Oslo")
    # Tromso: the sun neither sets in midsummer nor rises at midwinter.
    for day in (date(2026, 6, 21), date(2026, 12, 21)):
        rise, sets = solar.sun_times(day, 69.65, 18.96, tz)
        assert rise is None and sets is None, f"{day}: expected no events"


def test_equator_days_are_near_twelve_hours():
    tz = ZoneInfo("Africa/Nairobi")
    rise, sets = solar.sun_times(date(2026, 3, 21), -1.2921, 36.8219, tz)
    length = minutes(sets) - minutes(rise)
    assert 705 <= length <= 735, f"day length {length} min is not near 12 h"


# ---------------------------------------------------------------- location


def test_iso6709_parsing_handles_both_widths():
    # +DDMM+DDDMM
    lat, lon = location._parse_iso6709("-2728+15302")
    assert abs(lat - -27.4667) < 0.001
    assert abs(lon - 153.0333) < 0.001
    # +DDMMSS+DDDMMSS
    lat, lon = location._parse_iso6709("+404251-0740023")
    assert abs(lat - 40.7142) < 0.001
    assert abs(lon - -74.0064) < 0.001


def test_location_comes_from_the_time_zone():
    lat, lon = location.location_from_timezone("Australia/Brisbane")
    assert -28 < lat < -27
    assert 152 < lon < 154


def test_zone_with_several_names_still_resolves():
    # zone1970.tab lists linked names comma-separated on one row.
    lat, lon = location.location_from_timezone("Europe/London")
    assert 51 < lat < 52


# ------------------------------------------------------------------ ladder


def build(day=date(2026, 8, 22), tz_name="Australia/Brisbane", **overrides):
    tz = ZoneInfo(tz_name)
    s = settings(**overrides)
    return ladder.build_schedule(s, day, -27.4667, 153.0333, tz), s


def test_ladder_ramps_down_to_the_night_temperature():
    (steps, info), s = build()
    temps = [t for _, t in steps if t is not None]
    assert temps[0] == s["evening_temp"]
    assert temps[-1] == s["night_temp"]
    assert temps == sorted(temps, reverse=True), "ramp must never warm back up"


def test_ladder_starts_at_dusk_not_sunset():
    # Sunset is still daylight. Anything visible then reads as the filter
    # firing too early, which is the whole reason for the anchor.
    (steps, info), s = build()
    assert steps[0][0] == info["ramp_start"]
    assert info["anchor_name"] == "civil_dusk"
    assert info["ramp_start"] == info["anchor"]  # default offset is zero
    gap = (info["anchor"] - info["sunset"]).total_seconds() / 60
    assert 15 <= gap <= 45, f"civil dusk should trail sunset, got {gap} min"
    assert steps[-1][1] is None, "last profile should be the untinted day"
    assert steps[-1][0] == info["day_start"]


def test_anchor_choice_moves_the_start_later():
    starts = {}
    for anchor in ("sunset", "civil_dusk", "nautical_dusk", "astronomical_dusk"):
        (_, info), _ = build(ramp_anchor=anchor)
        starts[anchor] = info["ramp_start"]
    ordered = [starts["sunset"], starts["civil_dusk"],
               starts["nautical_dusk"], starts["astronomical_dusk"]]
    assert ordered == sorted(ordered), f"anchors out of order: {starts}"


def test_ramp_begins_at_the_daytime_value_so_there_is_no_step():
    # The original bug: the first rung was 5000K, so sunset brought a visible
    # jump from untinted straight to orange.
    (steps, _), s = build()
    assert steps[0][1] == s["evening_temp"] == 6500
    # a jump of more than ~10 mireds at the start is perceptible
    jump = 1e6 / steps[0][1] - 1e6 / 6500
    assert abs(jump) < 10


def test_curve_holds_near_the_daytime_value_early():
    # Half an hour in, nothing should have visibly happened yet.
    (steps, info), s = build()
    thirty_min = info["ramp_start"] + timedelta(minutes=30)
    early = [temp for when, temp in steps
             if temp is not None and when <= thirty_min][-1]
    assert early >= 6300, f"too warm too early: {early}K"
    # and by the end it must still reach the floor
    assert [t for _, t in steps if t is not None][-1] == s["night_temp"]


def test_curve_is_monotonic_for_any_power():
    for power in (1.0, 1.5, 2.0, 3.0):
        (steps, _), _ = build(ramp_curve_power=power)
        temps = [t for _, t in steps if t is not None]
        assert temps == sorted(temps, reverse=True), f"power {power} not monotonic"


def test_unreachable_twilight_falls_back_to_sunset():
    # Reykjavik in June: the sun never gets 18 degrees down.
    tz = ZoneInfo("Atlantic/Reykjavik")
    _, info = ladder.build_schedule(settings(ramp_anchor="astronomical_dusk"),
                                date(2026, 6, 21), 64.1466, -21.9426, tz)
    assert info["anchor_name"] == "sunset"


def test_bad_anchor_and_curve_are_rejected():
    for bad in (dict(ramp_anchor="dinnertime"), dict(ramp_curve_power=0),
                dict(ramp_curve_power=50)):
        try:
            cfg.validate(settings(**bad))
        except SystemExit:
            continue
        raise AssertionError(f"validate accepted {bad}")


def test_no_duplicate_clock_times():
    # hyprsunset keys profiles on HH:MM, so a collision silently drops a step.
    for step_minutes in (1, 5, 20, 60):
        (steps, _), _ = build(step_minutes=step_minutes, ramp_minutes=300)
        keys = [when.strftime("%H:%M") for when, _ in steps]
        assert len(keys) == len(set(keys)), f"duplicate times at step={step_minutes}"


def test_ramp_never_runs_past_the_morning_profile():
    # A ramp longer than the night must be clamped, or the ladder would emit a
    # warm profile after the untinted one and hold the tint through the day.
    (steps, info), _ = build(ramp_minutes=2000, full_tint_by=None)
    assert info["ramp_end"] < info["day_start"]
    for when, temp in steps:
        if temp is None:
            continue
        assert when < info["day_start"]


def test_sorted_by_clock_the_cycle_stays_consistent():
    # The rendered file is sorted by HH:MM and hyprsunset wraps past the last
    # entry. Sorting must not reorder the ramp relative to the day profile.
    (steps, _), _ = build()
    by_clock = sorted(steps, key=lambda item: item[0].strftime("%H:%M"))
    temps = [t for _, t in by_clock]
    day_index = temps.index(None)
    after_day = [t for t in temps[day_index + 1:] if t is not None]
    assert after_day == sorted(after_day, reverse=True)


def test_interpolation_is_even_in_mireds():
    # Even steps in mired space are what make the ramp read as smooth. Disable
    # the 50 K output rounding first, or quantisation noise swamps the check,
    # and flatten the curve, which deliberately makes the steps uneven in time.
    (steps, _), _ = build(step_minutes=60, ramp_minutes=300, round_to_kelvin=1,
                          ramp_curve_power=1.0, full_tint_by=None)
    mireds = [1e6 / t for _, t in steps if t is not None]
    gaps = [b - a for a, b in zip(mireds, mireds[1:])]
    assert max(gaps) - min(gaps) < 0.5, f"mired steps are uneven: {gaps}"


def test_rounding_stays_within_half_a_quantum():
    (rounded, _), s = build(step_minutes=60, ramp_minutes=300, full_tint_by=None)
    (exact, _), _ = build(step_minutes=60, ramp_minutes=300, round_to_kelvin=1,
                          full_tint_by=None)
    for (_, got), (_, want) in zip(rounded, exact):
        if got is None or want is None:
            continue
        assert abs(got - want) <= s["round_to_kelvin"] / 2 + 1


def test_ramp_ends_at_the_target_clock_time():
    (steps, info), s = build()
    assert info["ramp_end"].strftime("%H:%M") == s["full_tint_by"] == "21:00"
    warm = [(w, temp) for w, temp in steps if temp is not None]
    assert warm[-1][1] == s["night_temp"]
    assert warm[-1][0].strftime("%H:%M") == "21:00"


def test_ramp_length_follows_the_season():
    # The point of a clock target: dusk moves by over an hour across the year
    # here, so a fixed duration would land full tint near midnight in summer.
    lengths = {}
    for day in (date(2026, 6, 21), date(2026, 12, 21)):
        (_, info), _ = build(day=day)
        lengths[day] = (info["ramp_end"] - info["ramp_start"]).total_seconds() / 60
        assert info["ramp_end"].strftime("%H:%M") == "21:00", day
    midwinter, midsummer = lengths[date(2026, 6, 21)], lengths[date(2026, 12, 21)]
    assert midwinter > midsummer + 60, (
        f"ramp should stretch in winter: {midwinter} vs {midsummer} min")


def test_null_target_falls_back_to_a_fixed_duration():
    (_, info), _ = build(full_tint_by=None, ramp_minutes=120)
    length = (info["ramp_end"] - info["ramp_start"]).total_seconds() / 60
    assert length == 120


def test_an_early_hours_target_means_the_next_day():
    (_, info), _ = build(full_tint_by="01:00")
    assert info["ramp_end"].strftime("%H:%M") == "01:00"
    assert info["ramp_end"] > info["ramp_start"]
    assert info["ramp_end"].date() == info["ramp_start"].date() + timedelta(days=1)


def test_a_target_already_past_at_dusk_keeps_a_short_ramp():
    # Asking to be fully warm at 17:00 when it gets dark at 17:54 is impossible;
    # it must not invert the ramp or produce a zero-length one.
    (steps, info), s = build(full_tint_by="17:00")
    length = (info["ramp_end"] - info["ramp_start"]).total_seconds() / 60
    assert length == s["min_ramp_minutes"]
    assert info["ramp_end"] > info["ramp_start"]
    temps = [temp for _, temp in steps if temp is not None]
    assert temps == sorted(temps, reverse=True)


def test_target_is_validated():
    for bad in (dict(full_tint_by="25:00"), dict(full_tint_by="nine"),
                dict(min_ramp_minutes=0)):
        try:
            cfg.validate(settings(**bad))
        except SystemExit:
            continue
        raise AssertionError(f"validate accepted {bad}")


def test_degenerate_location_falls_back_and_is_flagged():
    tz = ZoneInfo("Europe/Oslo")
    (steps, info) = ladder.build_schedule(settings(), date(2026, 6, 21), 69.65, 18.96, tz)
    assert info["degenerate"] is True
    assert info["sunset"].strftime("%H:%M") == cfg.DEFAULTS["fallback_sunset"]
    assert len(steps) > 1


def test_day_temp_emits_a_temperature_not_identity():
    (steps, _), _ = build(day_temp=6500)
    assert steps[-1][1] == 6500


# ------------------------------------------------------------------ render


def test_rendered_profiles_are_sorted_and_well_formed():
    (steps, info), s = build()
    text = conf.render_ladder(steps, s, info, -27.4667, 153.0333, "test", "Australia/Brisbane")
    assert text.startswith(paths.MARKER)
    times, bodies = [], []
    block = None
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("profile"):
            block = {}
        elif line == "}" and block is not None:
            bodies.append(block)
            block = None
        elif block is not None and "=" in line:
            key, value = (p.strip() for p in line.split("=", 1))
            block[key] = value
            if key == "time":
                times.append(value)
    assert times == sorted(times), "hyprsunset needs profiles in clock order"
    assert len(bodies) == len(steps)
    for body in bodies:
        assert "time" in body
        assert ("temperature" in body) ^ ("identity" in body)


def test_paused_conf_is_identity_only():
    text = conf.render_hold("Australia/Brisbane", None)
    assert text.count("profile {") == 1
    assert "identity = true" in text
    assert "temperature" not in text


# ---------------------------------------------------------------- settings


def test_validate_rejects_nonsense():
    for bad in (dict(evening_temp=50), dict(night_temp=99999),
                dict(ramp_minutes=0), dict(step_minutes=0),
                dict(fallback_sunset="25:00"), dict(round_to_kelvin=0)):
        try:
            cfg.validate(settings(**bad))
        except SystemExit:
            continue
        raise AssertionError(f"validate accepted {bad}")


def test_validate_accepts_the_defaults():
    cfg.validate(settings())


# ----------------------------------------------------------------- consent

# The guarantee: until the user has agreed, this writes nothing to their
# configuration. These drive the real script in a throwaway XDG root.

import os
import shutil
import subprocess
import tempfile

CLI = str(REPO / "bin" / "nightlight")


def sandbox():
    """A throwaway config/state root with a hand-written hyprsunset.conf in it."""
    root = Path(tempfile.mkdtemp(prefix="nightlight-test-"))
    (root / "cfg" / "hypr").mkdir(parents=True)
    (root / "state").mkdir()
    bin_dir = root / "bin"
    bin_dir.mkdir()
    # Stub the things that would touch the real session.
    for name in ("systemctl", "omarchy-refresh-config", "pgrep", "hyprctl"):
        stub = bin_dir / name
        stub.write_text("#!/bin/bash\nexit 0\n" if name != "pgrep"
                        else "#!/bin/bash\nexit 1\n")
        stub.chmod(0o755)
    conf = root / "cfg" / "hypr" / "hyprsunset.conf"
    conf.write_text("# MINE\nprofile {\n    time = 07:00\n    identity = true\n}\n")
    return root


def run_cli(root, *args, stdin=""):
    env = dict(os.environ)
    env["XDG_CONFIG_HOME"] = str(root / "cfg")
    env["XDG_STATE_HOME"] = str(root / "state")
    env["HOME"] = str(root)
    env["PATH"] = f"{root / 'bin'}:{env['PATH']}"
    env["TZ"] = "Australia/Brisbane"
    return subprocess.run([CLI, *args], capture_output=True, text=True,
                          input=stdin, env=env, timeout=60)


def test_apply_refuses_before_consent():
    root = sandbox()
    conf = root / "cfg" / "hypr" / "hyprsunset.conf"
    before = conf.read_text()
    result = run_cli(root, "apply")
    assert result.returncode != 0, "apply must refuse before setup"
    assert "setup" in result.stderr.lower()
    assert conf.read_text() == before, "the user's config was modified anyway"


def test_setup_without_a_tty_refuses_unless_yes():
    root = sandbox()
    conf = root / "cfg" / "hypr" / "hyprsunset.conf"
    before = conf.read_text()
    result = run_cli(root, "setup")
    assert result.returncode != 0
    assert conf.read_text() == before
    assert not (root / "state" / "nightlight" / "consent.json").exists()


def test_setup_print_changes_nothing():
    root = sandbox()
    conf = root / "cfg" / "hypr" / "hyprsunset.conf"
    before = conf.read_text()
    result = run_cli(root, "setup", "--print")
    assert result.returncode == 0
    assert "hyprsunset.conf" in result.stdout
    assert conf.read_text() == before
    assert not (root / "state" / "nightlight" / "consent.json").exists()
    # and nothing was installed
    assert not (root / "cfg" / "systemd").exists()


def test_status_works_before_consent_and_writes_nothing():
    root = sandbox()
    conf = root / "cfg" / "hypr" / "hyprsunset.conf"
    before = conf.read_text()
    result = run_cli(root, "status", "--json")
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["setup"] is False
    assert conf.read_text() == before
    assert not (root / "cfg" / "nightlight").exists()


def test_setup_then_teardown_restores_the_original_config():
    root = sandbox()
    conf = root / "cfg" / "hypr" / "hyprsunset.conf"
    original = conf.read_text()

    result = run_cli(root, "setup", "--yes")
    assert result.returncode == 0, result.stderr
    assert paths.MARKER in conf.read_text(), "setup did not write the schedule"
    assert (root / "state" / "nightlight" / "consent.json").exists()
    assert (root / "cfg" / "systemd" / "user" / "nightlight.timer").exists()

    result = run_cli(root, "teardown")
    assert result.returncode == 0, result.stderr
    assert conf.read_text() == original, "teardown did not restore the original file"
    assert not (root / "cfg" / "systemd" / "user" / "nightlight.timer").exists()
    assert not (root / "state" / "nightlight" / "consent.json").exists()
    # consent is re-armed
    assert run_cli(root, "apply").returncode != 0


def test_setup_does_not_clobber_an_existing_settings_file():
    root = sandbox()
    settings = root / "cfg" / "nightlight" / "config.json"
    settings.parent.mkdir(parents=True)
    settings.write_text(json.dumps({"night_temp": 2200}) + "\n")
    assert run_cli(root, "setup", "--yes").returncode == 0
    assert json.loads(settings.read_text())["night_temp"] == 2200


# ----------------------------------------------------------------- morning


def test_morning_ramp_is_off_by_default():
    # Backwards compatible: with no morning anchor the day returns in a single
    # step at sunrise, as before.
    (steps, info), _ = build()
    assert info["morning_anchor_name"] is None
    assert steps[-1][1] is None
    assert steps[-2][0] == info["ramp_end"]


def test_morning_ramp_runs_from_dawn_to_sunrise():
    (steps, info), s = build(morning_anchor="civil_dawn")
    assert info["morning_anchor_name"] == "civil_dawn"
    # Everything after the evening floor and before the day profile is the
    # morning ramp.
    floor_index = max(i for i, (_, t) in enumerate(steps) if t == s["night_temp"])
    morning = steps[floor_index + 1:]
    assert morning[-1][1] is None and morning[-1][0] == info["day_start"]
    temps = [t for _, t in morning if t is not None]
    assert temps, "a morning ramp should emit steps before the day profile"
    assert temps == sorted(temps), "the morning must only ever cool towards daylight"
    assert temps[-1] <= s["evening_temp"]
    # It starts at civil dawn, which leads sunrise by well under an hour. The
    # very first rung is the floor already on screen, so it collapses away and
    # the first emitted step sits one rung in (rungs are spaced to fit the
    # window, so a rung can be up to half a step longer than step_minutes).
    step = timedelta(minutes=s["step_minutes"])
    assert info["morning_start"] <= morning[0][0] <= info["morning_start"] + step * 1.5
    gap = (info["sunrise"] - info["morning_anchor"]).total_seconds() / 60
    assert 15 <= gap <= 60, f"civil dawn should lead sunrise, got {gap} min"
    assert info["morning_start"] <= info["morning_anchor"]
    assert info["morning_start"] > info["ramp_end"]


def test_morning_ramp_holds_warm_early_and_brightens_near_sunrise():
    (steps, info), s = build(morning_anchor="civil_dawn", ramp_curve_power=2.0,
                             min_ramp_minutes=60, step_minutes=5)
    floor_index = max(i for i, (_, t) in enumerate(steps) if t == s["night_temp"])
    temps = [t for _, t in steps[floor_index + 1:] if t is not None]
    n = len(temps)
    assert n >= 6
    m = lambda k: 1e6 / k
    first_half = m(s["night_temp"]) - m(temps[n // 2 - 1])
    second_half = m(temps[n // 2 - 1]) - m(temps[-1])
    assert first_half < second_half, "most of the change should sit close to sunrise"


def test_morning_ramp_respects_the_minimum_length():
    (steps, info), s = build(morning_anchor="civil_dawn", min_ramp_minutes=90)
    length = (info["day_start"] - info["morning_start"]).total_seconds() / 60
    assert length >= 89


def test_morning_ramp_never_overlaps_the_evening():
    (steps, info), s = build(morning_anchor="astronomical_dawn", ramp_minutes=2000,
                             full_tint_by=None, min_ramp_minutes=3000)
    assert info["morning_start"] > info["ramp_end"]
    by_clock = sorted(steps, key=lambda item: item[0].strftime("%H:%M"))
    assert len({when.strftime("%H:%M") for when, _ in by_clock}) == len(by_clock)


def test_bad_morning_anchor_is_rejected():
    for bad in ("sunset", "dusk", "civil_dusk", ""):
        try:
            cfg.validate(settings(morning_anchor=bad))
        except SystemExit:
            continue
        raise AssertionError(f"validate accepted morning_anchor={bad!r}")


def test_rendered_conf_mentions_the_morning_ramp():
    (steps, info), s = build(morning_anchor="civil_dawn")
    text = conf.render_ladder(steps, s, info, -27.4667, 153.0333, "test", "Australia/Brisbane")
    assert "civil dawn" in text


# -------------------------------------------------------------------- modes


def test_held_conf_on_and_off():
    off = conf.render_hold("Australia/Brisbane", None)
    on = conf.render_hold("Australia/Brisbane", 4000)
    assert paths.MARKER in off and paths.MARKER in on
    assert "identity = true" in off and "temperature" not in off.split("profile")[1]
    assert "temperature = 4000" in on and "identity" not in on.split("profile")[1]
    assert conf.render_hold("Australia/Brisbane", None) == off


def test_on_off_auto_write_the_matching_conf():
    root = sandbox()
    try:
        assert run_cli(root, "setup", "--yes").returncode == 0
        conf = root / "cfg" / "hypr" / "hyprsunset.conf"
        assert conf.read_text().count("profile {") > 2

        assert run_cli(root, "on").returncode == 0
        text = conf.read_text()
        assert text.count("profile {") == 1 and "temperature = 3000" in text
        status = json.loads(run_cli(root, "status", "--json").stdout)
        assert status["mode"] == "on" and status["manual_temp"] == 3000

        assert run_cli(root, "off").returncode == 0
        text = conf.read_text()
        assert text.count("profile {") == 1 and "identity = true" in text
        status = json.loads(run_cli(root, "status", "--json").stdout)
        assert status["mode"] == "off"

        assert run_cli(root, "toggle").returncode == 0
        assert json.loads(run_cli(root, "status", "--json").stdout)["mode"] == "auto"
        assert run_cli(root, "toggle").returncode == 0
        assert json.loads(run_cli(root, "status", "--json").stdout)["mode"] == "off"

        assert run_cli(root, "auto").returncode == 0
        assert conf.read_text().count("profile {") > 2
        assert json.loads(run_cli(root, "status", "--json").stdout)["mode"] == "auto"
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_show_json_describes_the_phases():
    root = sandbox()
    try:
        out = run_cli(root, "show", "--json")
        assert out.returncode == 0, out.stderr
        data = json.loads(out.stdout)
        for key in ("mode", "ramp_start", "ramp_end", "day_start",
                    "evening_temp", "night_temp", "anchor_name"):
            assert key in data, key
        assert data["mode"] == "auto"
        assert data["morning_start"] is None
        assert data["ramp_start"] == data["steps"][0]["time"]

        cfg = root / "cfg" / "nightlight"
        cfg.mkdir(parents=True, exist_ok=True)
        (cfg / "config.json").write_text(json.dumps({"morning_anchor": "civil_dawn"}))
        data = json.loads(run_cli(root, "show", "--json").stdout)
        assert data["morning_start"] is not None
        assert data["morning_start"] < data["day_start"]
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_a_stray_hyprsunset_is_cleared_before_the_unit_starts():
    # A hyprsunset started outside the unit holds the CTM protocol; starting
    # the unit next to it crash-loops into systemd's start limit.
    root = sandbox()
    try:
        log, flag, bin_dir = root / "calls.log", root / "stray", root / "bin"
        flag.touch()
        (bin_dir / "pgrep").write_text(f'#!/bin/bash\n[ -e "{flag}" ]\n')
        (bin_dir / "pkill").write_text(f'#!/bin/bash\necho "pkill $*" >> "{log}"\nrm -f "{flag}"\n')
        (bin_dir / "systemctl").write_text(
            f'#!/bin/bash\necho "systemctl $*" >> "{log}"\n'
            'case "$2" in is-active) echo inactive; exit 3;; '
            'is-enabled) echo disabled; exit 1;; esac\nexit 0\n')
        for name in ("pgrep", "pkill", "systemctl"):
            (bin_dir / name).chmod(0o755)

        assert run_cli(root, "setup", "--yes").returncode == 0
        calls = log.read_text().splitlines()
        enable = calls.index("systemctl --user enable --now hyprsunset.service")
        assert calls.index("pkill -x hyprsunset") < enable
        assert calls.index("systemctl --user reset-failed hyprsunset.service") < enable

        # And a rebuild that finds a stray copy clears the start limit too.
        flag.touch()
        log.write_text("")
        assert run_cli(root, "apply", "--force").returncode == 0
        calls = log.read_text().splitlines()
        start = calls.index("systemctl --user start hyprsunset.service")
        assert calls.index("pkill -x hyprsunset") < start
        assert calls.index("systemctl --user reset-failed hyprsunset.service") < start
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_daytime_follows_the_clock_between_day_start_and_the_ramp():
    tz = ZoneInfo("Australia/Brisbane")
    (_, info), _ = build(day_temp=6000)
    at = lambda h, m: datetime(2026, 8, 22, h, m, tzinfo=tz)
    ds, rs = info["day_start"], info["ramp_start"]
    assert status.in_daytime(at(12, 0), info)
    assert status.in_daytime(at(ds.hour, ds.minute), info)
    assert not status.in_daytime(at(rs.hour, rs.minute), info)
    assert not status.in_daytime(at(22, 0), info)
    assert not status.in_daytime(at(3, 0), info)


def test_status_and_show_describe_a_tinted_day():
    root = sandbox()
    try:
        cfg = root / "cfg" / "nightlight"
        cfg.mkdir(parents=True, exist_ok=True)
        (cfg / "config.json").write_text(json.dumps({"day_temp": 6000}))
        status = json.loads(run_cli(root, "status", "--json").stdout)
        assert isinstance(status["daytime"], bool)
        assert json.loads(run_cli(root, "show", "--json").stdout)["day_temp"] == 6000
    finally:
        shutil.rmtree(root, ignore_errors=True)


# ------------------------------------------------------------ manual hold

# On holds a temperature of its own, picked from the panel. Changing it must
# not restart hyprsunset -- that blanks the tint for a moment -- so these run
# against a stand-in that answers the way a running hyprsunset does.


def fake_hyprsunset(root, time="00:00", temperature=3000, identity=False):
    """Make the sandbox look like hyprsunset is up under its unit, having read
    one profile at startup. Returns the log every call to it lands in."""
    log, bin_dir = root / "calls.log", root / "bin"
    log.write_text("")
    (root / "loaded").write_text(
        f"Time: {time}\nTemperature: {temperature}\nGamma: 1\n"
        f"Identity: {'true' if identity else 'false'}\n")
    (bin_dir / "pgrep").write_text("#!/bin/bash\nexit 0\n")
    (bin_dir / "systemctl").write_text(
        f'#!/bin/bash\necho "systemctl $*" >> "{log}"\n'
        'case "$2" in is-active) echo active;; is-enabled) echo enabled;; esac\nexit 0\n')
    (bin_dir / "hyprctl").write_text(
        f'#!/bin/bash\necho "hyprctl $*" >> "{log}"\n'
        f'case "$2 $3" in "profile ") cat "{root / "loaded"}";; '
        '"temperature ") echo 3000;; *) echo ok;; esac\n')
    for name in ("pgrep", "systemctl", "hyprctl"):
        (bin_dir / name).chmod(0o755)
    return log


def calls(log):
    lines = log.read_text().splitlines()
    log.write_text("")
    return lines


RESTART = "systemctl --user restart hyprsunset.service"


def conf_of(root):
    return (root / "cfg" / "hypr" / "hyprsunset.conf").read_text()


def test_on_takes_a_temperature_and_leaves_the_schedule_alone():
    root = sandbox()
    try:
        assert run_cli(root, "setup", "--yes").returncode == 0
        assert run_cli(root, "on", "3400").returncode == 0
        assert "temperature = 3400" in conf_of(root)
        status_ = json.loads(run_cli(root, "status", "--json").stdout)
        assert status_["manual_temp"] == 3400 and status_["night_temp"] == 3000
        settings_file = json.loads((root / "cfg" / "nightlight" / "config.json").read_text())
        assert settings_file["night_temp"] == 3000

        # It is remembered across a trip through the other modes.
        assert run_cli(root, "auto").returncode == 0
        assert run_cli(root, "on").returncode == 0
        assert "temperature = 3400" in conf_of(root)
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_temp_is_stored_but_not_applied_outside_on():
    root = sandbox()
    try:
        assert run_cli(root, "setup", "--yes").returncode == 0
        ladder_conf = conf_of(root)
        assert run_cli(root, "temp", "2800").returncode == 0
        assert conf_of(root) == ladder_conf
        assert run_cli(root, "temp").stdout.strip() == "2800"
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_temp_moves_relatively_stops_at_the_limits_and_resets():
    root = sandbox()
    try:
        assert run_cli(root, "setup", "--yes").returncode == 0
        assert run_cli(root, "temp", "+250").returncode == 0
        assert run_cli(root, "temp").stdout.strip() == "3250"
        assert run_cli(root, "temp", "-100").returncode == 0
        assert run_cli(root, "temp").stdout.strip() == "3150"
        assert run_cli(root, "temp", "-9000").returncode == 0
        assert run_cli(root, "temp").stdout.strip() == "1000"
        for bad in ("500", "99999", "warm"):
            assert run_cli(root, "temp", bad).returncode != 0, bad
        assert run_cli(root, "temp").stdout.strip() == "1000"
        assert run_cli(root, "temp", "reset").returncode == 0
        assert run_cli(root, "temp").stdout.strip() == "3000"
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_changing_a_hold_does_not_restart_hyprsunset():
    root = sandbox()
    try:
        assert run_cli(root, "setup", "--yes").returncode == 0
        assert run_cli(root, "on").returncode == 0
        log = fake_hyprsunset(root, temperature=3000)

        assert run_cli(root, "temp", "3500").returncode == 0
        seen = calls(log)
        assert "hyprctl hyprsunset temperature 3500" in seen
        assert RESTART not in seen
        assert "temperature = 3500" in conf_of(root), "the config must agree with the screen"

        assert run_cli(root, "off").returncode == 0
        seen = calls(log)
        assert "hyprctl hyprsunset identity true" in seen
        assert RESTART not in seen
        assert "identity = true" in conf_of(root)
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_leaving_auto_restarts_because_a_loaded_ladder_would_overrule_it():
    root = sandbox()
    try:
        assert run_cli(root, "setup", "--yes").returncode == 0
        log = fake_hyprsunset(root, time="18:45", temperature=6500)
        assert run_cli(root, "on").returncode == 0
        assert RESTART in calls(log)

        # Even a ladder that happens to have a rung at midnight.
        assert run_cli(root, "auto").returncode == 0
        log = fake_hyprsunset(root, time="00:00", temperature=3000)
        assert run_cli(root, "on").returncode == 0
        assert RESTART in calls(log)
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_the_timer_pass_reloads_a_hold_hyprsunset_only_has_live():
    # After a live change hyprsunset still has the old profile in memory and
    # would put it back at midnight. The plain `apply` the timer runs fixes it.
    root = sandbox()
    try:
        assert run_cli(root, "setup", "--yes").returncode == 0
        assert run_cli(root, "on", "3500").returncode == 0
        log = fake_hyprsunset(root, temperature=3000)
        assert run_cli(root, "apply").returncode == 0
        assert RESTART in calls(log)

        # Once it has the right one loaded, the pass leaves it running.
        log = fake_hyprsunset(root, temperature=3500)
        assert run_cli(root, "apply").returncode == 0
        assert RESTART not in calls(log)
    finally:
        shutil.rmtree(root, ignore_errors=True)


# ------------------------------------------------------------------- setup


def test_setup_points_the_units_at_this_checkout_and_links_the_cli():
    root = sandbox()
    try:
        assert run_cli(root, "setup", "--yes").returncode == 0
        service = (root / "cfg" / "systemd" / "user" / "nightlight.service").read_text()
        hook = (root / "cfg" / "omarchy" / "hooks" / "post-boot.d" / "nightlight.sh").read_text()
        assert f"ExecStart={CLI} apply" in service
        assert f'"{CLI}" apply' in hook and "@CLI@" not in service + hook
        link = root / ".local" / "bin" / "nightlight"
        assert link.is_symlink() and str(link.resolve()) == CLI

        assert run_cli(root, "teardown").returncode == 0
        assert not link.is_symlink()
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_setup_leaves_someone_elses_nightlight_command_alone():
    root = sandbox()
    try:
        theirs = root / ".local" / "bin" / "nightlight"
        theirs.parent.mkdir(parents=True)
        theirs.write_text("#!/bin/bash\n")
        assert run_cli(root, "setup", "--yes").returncode == 0
        assert run_cli(root, "teardown").returncode == 0
        assert theirs.read_text() == "#!/bin/bash\n"
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_setup_adopts_settings_from_nightlight_auto():
    root = sandbox()
    try:
        legacy = root / "cfg" / "nightlight-auto" / "config.json"
        legacy.parent.mkdir(parents=True)
        legacy.write_text(json.dumps({"night_temp": 4000}) + "\n")
        assert run_cli(root, "setup", "--yes").returncode == 0
        adopted = json.loads((root / "cfg" / "nightlight" / "config.json").read_text())
        assert adopted == {"night_temp": 4000}
        assert json.loads(run_cli(root, "status", "--json").stdout)["night_temp"] == 4000
    finally:
        shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    failures = 0
    for name, fn in sorted(globals().items()):
        if not name.startswith("test_") or not callable(fn):
            continue
        try:
            fn()
            print(f"ok   {name}")
        except Exception as exc:  # noqa: BLE001 - a test runner wants everything
            failures += 1
            print(f"FAIL {name}: {exc}")
    print(f"\n{failures} failure(s)")
    sys.exit(1 if failures else 0)
