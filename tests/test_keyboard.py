"""Tests for the keyboard tint: the colour it picks, and that it only talks to
asusctl when it has something to say.

Run with:  python3 tests/test_keyboard.py
"""

import json
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_schedule import CLI, run_cli, sandbox  # noqa: E402

from nightlight import keyboard  # noqa: E402

THEME = "8fb4de"


def channels(hex_):
    return tuple(int(hex_[i:i + 2], 16) for i in (0, 2, 4))


# ------------------------------------------------------------------ colour


def test_untinted_screen_keeps_the_theme_colour():
    for kelvin in (None, 6500, 9000):
        assert keyboard.tinted_color(THEME, kelvin) == THEME, kelvin


def test_warmer_screen_means_a_warmer_keyboard():
    previous = channels(THEME)
    for kelvin in range(6400, 999, -100):
        r, g, b = channels(keyboard.tinted_color(THEME, kelvin))
        assert r >= previous[0] and b <= previous[2], kelvin
        previous = (r, g, b)


def test_4000k_is_clearly_warm_whatever_the_theme():
    for theme in (THEME, "0000ff", "00ff00", "ffffff"):
        r, g, b = channels(keyboard.tinted_color(theme, 4000))
        assert r > g > b and r - b > 100, (theme, r, g, b)


def test_below_full_warm_only_the_amber_deepens():
    assert keyboard.tinted_color(THEME, 3700) == keyboard.tinted_color("0000ff", 3700)
    assert channels(keyboard.tinted_color(THEME, 1000)) == keyboard.AMBER[-1][1]


# --------------------------------------------------------------------- cli


ASUSD_STUB = """#!/bin/bash
root="@ROOT@"
echo "$*" >> "$root/asusctl.log"
case "$1 $2" in
  "leds get")
    level=$(cat "$root/hardware.level")
    echo "Current keyboard led brightness: ${level^}"
    ;;
  "leds set")
    echo "$3" > "$root/hardware.level"
    echo "$3" > "$root/stored.level"
    ;;
  "aura effect")
    if [[ $(cat "$root/stored.level") == off ]]; then
      echo med > "$root/stored.level"
    fi
    cp "$root/stored.level" "$root/hardware.level"
    ;;
esac
"""


def keyboard_sandbox():
    """A set-up sandbox with a theme colour, held On at 4000K, and an asusctl
    that logs its calls and keeps brightness the way asusd does: its own stored
    level, re-applied by every effect, apart from the level in the hardware."""
    root = sandbox()
    theme_file = root / "state" / "omarchy" / "current" / "theme" / "keyboard.rgb"
    theme_file.parent.mkdir(parents=True)
    theme_file.write_text(f"#{THEME}\n")
    log = root / "asusctl.log"
    log.write_text("")
    asusctl = root / "bin" / "asusctl"
    asusctl.write_text(ASUSD_STUB.replace("@ROOT@", str(root)))
    asusctl.chmod(0o755)
    (root / "hardware.level").write_text("med\n")
    (root / "stored.level").write_text("med\n")
    assert run_cli(root, "setup", "--yes").returncode == 0
    assert run_cli(root, "on", "4000").returncode == 0
    return root, log


def painted(log):
    lines = [line.split()[-1] for line in log.read_text().splitlines()
             if line.startswith("aura effect")]
    log.write_text("")
    return lines


def press_brightness_key(root, level):
    """The Fn keys go through brightnessctl: the hardware moves, asusd is not told."""
    (root / "hardware.level").write_text(f"{level}\n")


def hardware_level(root):
    return (root / "hardware.level").read_text().strip()


def stored_level(root):
    return (root / "stored.level").read_text().strip()


def omarchy_paints_the_theme(root):
    subprocess.run([str(root / "bin" / "asusctl"), "aura", "effect", "static", "-c", THEME],
                   check=True)


def hook_of(root):
    return root / "cfg" / "omarchy" / "hooks" / "theme-set.d" / "nightlight.sh"


def test_keyboard_is_left_alone_until_asked():
    root, log = keyboard_sandbox()
    try:
        assert run_cli(root, "keyboard", "sync").returncode == 0
        assert painted(log) == []
        assert run_cli(root, "keyboard").stdout.strip() == "off"
        assert not hook_of(root).exists()
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_on_paints_once_and_installs_the_theme_hook():
    root, log = keyboard_sandbox()
    try:
        assert run_cli(root, "keyboard", "on").returncode == 0
        warm = keyboard.tinted_color(THEME, 4000)
        assert painted(log) == [warm]
        assert f"{CLI} keyboard sync --force" in hook_of(root).read_text()

        settings = json.loads((root / "cfg" / "nightlight" / "config.json").read_text())
        assert settings["keyboard_tint"] is True and settings["night_temp"] == 3000
        assert json.loads(run_cli(root, "status", "--json").stdout)["keyboard_tint"] is True

        # The per-minute sync stays quiet while nothing changes...
        assert run_cli(root, "keyboard", "sync").returncode == 0
        assert painted(log) == []
        # ...repaints when the screen moves, and when a theme change forces it.
        assert run_cli(root, "temp", "3000").returncode == 0
        assert run_cli(root, "keyboard", "sync").returncode == 0
        assert painted(log) == [keyboard.tinted_color(THEME, 3000)]
        assert run_cli(root, "keyboard", "sync", "--force").returncode == 0
        assert len(painted(log)) == 1
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_a_new_theme_is_tinted_from_its_own_colour():
    root, log = keyboard_sandbox()
    try:
        assert run_cli(root, "keyboard", "on").returncode == 0
        painted(log)
        theme_file = root / "state" / "omarchy" / "current" / "theme" / "keyboard.rgb"
        theme_file.write_text("#00ff00\n")
        assert run_cli(root, "keyboard", "sync").returncode == 0
        assert painted(log) == [keyboard.tinted_color("00ff00", 4000)]
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_off_and_teardown_hand_the_theme_colour_back():
    root, log = keyboard_sandbox()
    try:
        assert run_cli(root, "keyboard", "on").returncode == 0
        assert run_cli(root, "off").returncode == 0
        assert run_cli(root, "keyboard", "sync").returncode == 0
        assert painted(log)[-1] == THEME, "an untinted screen means the theme colour"

        assert run_cli(root, "on").returncode == 0
        assert run_cli(root, "keyboard", "sync").returncode == 0
        painted(log)
        assert run_cli(root, "keyboard", "off").returncode == 0
        assert painted(log) == [THEME]
        assert not hook_of(root).exists()

        assert run_cli(root, "keyboard", "on").returncode == 0
        painted(log)
        assert run_cli(root, "teardown").returncode == 0
        assert painted(log) == [THEME]
        assert not hook_of(root).exists()
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_a_failed_hand_back_is_retried_by_the_next_sync():
    root, log = keyboard_sandbox()
    try:
        assert run_cli(root, "keyboard", "on").returncode == 0
        asusctl = root / "bin" / "asusctl"
        working = asusctl.read_text()
        asusctl.write_text("#!/bin/bash\nexit 1\n")
        assert run_cli(root, "keyboard", "off").returncode == 0
        painted(log)
        asusctl.write_text(working)
        assert run_cli(root, "keyboard", "sync").returncode == 0
        assert painted(log) == [THEME]
        assert run_cli(root, "keyboard", "sync").returncode == 0
        assert painted(log) == []
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_a_new_colour_keeps_the_level_set_with_the_keys():
    root, log = keyboard_sandbox()
    try:
        assert run_cli(root, "keyboard", "on").returncode == 0
        painted(log)
        press_brightness_key(root, "low")
        assert run_cli(root, "temp", "3000").returncode == 0
        assert run_cli(root, "keyboard", "sync").returncode == 0
        assert painted(log) == [keyboard.tinted_color(THEME, 3000)]
        assert hardware_level(root) == "low"
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_each_sync_tells_asusd_once_about_a_new_level():
    root, log = keyboard_sandbox()
    try:
        assert run_cli(root, "keyboard", "on").returncode == 0
        press_brightness_key(root, "high")
        log.write_text("")
        assert run_cli(root, "keyboard", "sync").returncode == 0
        assert stored_level(root) == "high"
        assert "leds set high" in log.read_text() and painted(log) == []
        assert run_cli(root, "keyboard", "sync").returncode == 0
        assert "leds set" not in log.read_text()
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_a_theme_change_keeps_a_level_already_passed_to_asusd():
    root, log = keyboard_sandbox()
    try:
        assert run_cli(root, "keyboard", "on").returncode == 0
        press_brightness_key(root, "low")
        assert run_cli(root, "keyboard", "sync").returncode == 0
        omarchy_paints_the_theme(root)
        assert run_cli(root, "keyboard", "sync", "--force").returncode == 0
        assert hardware_level(root) == "low"
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_a_dark_keyboard_is_not_painted_until_it_is_lit_again():
    root, log = keyboard_sandbox()
    try:
        assert run_cli(root, "keyboard", "on").returncode == 0
        press_brightness_key(root, "off")
        assert run_cli(root, "keyboard", "sync").returncode == 0
        painted(log)
        assert run_cli(root, "temp", "3000").returncode == 0
        assert run_cli(root, "keyboard", "sync").returncode == 0
        assert painted(log) == [] and hardware_level(root) == "off"

        press_brightness_key(root, "low")
        assert run_cli(root, "keyboard", "sync").returncode == 0
        assert painted(log) == [keyboard.tinted_color(THEME, 3000)]
        assert hardware_level(root) == "low"
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_a_theme_change_leaves_a_dark_keyboard_dark_and_retints_it_later():
    root, log = keyboard_sandbox()
    try:
        assert run_cli(root, "keyboard", "on").returncode == 0
        press_brightness_key(root, "off")
        assert run_cli(root, "keyboard", "sync").returncode == 0
        omarchy_paints_the_theme(root)
        assert hardware_level(root) == "med", "the stub should light it, as asusd does"
        painted(log)
        assert run_cli(root, "keyboard", "sync", "--force").returncode == 0
        assert painted(log) == [] and hardware_level(root) == "off"

        press_brightness_key(root, "low")
        assert run_cli(root, "keyboard", "sync").returncode == 0
        assert painted(log) == [keyboard.tinted_color(THEME, 4000)]
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_a_forced_sync_keeps_a_keyboard_lit_by_hand_since_the_last_sync():
    root, log = keyboard_sandbox()
    try:
        assert run_cli(root, "keyboard", "on").returncode == 0
        press_brightness_key(root, "off")
        assert run_cli(root, "keyboard", "sync").returncode == 0
        press_brightness_key(root, "low")
        assert run_cli(root, "keyboard", "sync", "--force").returncode == 0
        assert hardware_level(root) == "low"
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_handing_the_colour_back_leaves_a_dark_keyboard_dark():
    root, log = keyboard_sandbox()
    try:
        assert run_cli(root, "keyboard", "on").returncode == 0
        press_brightness_key(root, "off")
        assert run_cli(root, "keyboard", "sync").returncode == 0
        painted(log)
        assert run_cli(root, "keyboard", "off").returncode == 0
        assert painted(log) == [THEME] and hardware_level(root) == "off"
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_an_unreadable_level_does_not_stop_the_tint():
    root, log = keyboard_sandbox()
    try:
        asusctl = root / "bin" / "asusctl"
        asusctl.write_text(f'#!/bin/bash\necho "$*" >> "{log}"\n')
        assert run_cli(root, "keyboard", "on").returncode == 0
        assert painted(log) == [keyboard.tinted_color(THEME, 4000)]
        assert run_cli(root, "keyboard", "sync").returncode == 0
        assert "leds set" not in log.read_text() and painted(log) == []
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_someone_elses_theme_hook_is_left_alone():
    root, log = keyboard_sandbox()
    try:
        theirs = hook_of(root)
        theirs.parent.mkdir(parents=True)
        theirs.write_text("#!/bin/bash\necho mine\n")
        assert run_cli(root, "keyboard", "on").returncode == 0
        assert run_cli(root, "keyboard", "off").returncode == 0
        assert run_cli(root, "teardown").returncode == 0
        assert theirs.read_text() == "#!/bin/bash\necho mine\n"
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_without_asusctl_on_refuses_and_sync_does_nothing():
    root, log = keyboard_sandbox()
    try:
        (root / "bin" / "asusctl").unlink()
        # PATH holds only the stubs, so the machine's own asusctl, if it has
        # one, cannot be found and repaint the real keyboard.
        (root / "bin" / "python3").symlink_to(sys.executable)
        bare = str(root / "bin")
        result = run_cli(root, "keyboard", "on", path=bare)
        assert result.returncode != 0 and "asusctl" in result.stderr
        assert run_cli(root, "keyboard", "sync", path=bare).returncode == 0
        assert painted(log) == []
        status_ = json.loads(run_cli(root, "status", "--json", path=bare).stdout)
        assert status_["keyboard_available"] is False and status_["keyboard_tint"] is False
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
