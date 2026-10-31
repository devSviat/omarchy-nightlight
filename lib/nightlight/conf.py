"""hyprsunset.conf, as text."""

from __future__ import annotations

from .paths import APP, HYPRSUNSET_CONF, MARKER, SETTINGS_PATH


def is_ours() -> bool:
    return HYPRSUNSET_CONF.exists() and MARKER in HYPRSUNSET_CONF.read_text()


def render_hold(tz_name: str, temperature) -> str:
    """One profile around the clock: untinted (None) or a fixed temperature.
    This is what Off and On write in place of the ladder."""
    if temperature is None:
        note = f"# Off. Run `{APP} auto` to put the ramp back."
        value = "    identity = true"
    else:
        note = f"# On, held at {temperature}K. Run `{APP} auto` to put the ramp back."
        value = f"    temperature = {temperature}"
    return "\n".join([
        MARKER,
        note,
        f"# Settings live in {SETTINGS_PATH}",
        "#",
        f"# time zone : {tz_name}",
        "",
        "profile {",
        "    time = 00:00",
        value,
        "}",
        "",
    ])


def render_ladder(steps, settings, info, lat, lon, source, tz_name) -> str:
    lines = [
        MARKER,
        f"# Do not edit; run `{APP} apply` to rebuild.",
        f"# Settings live in {SETTINGS_PATH}",
        "#",
        f"# time zone : {tz_name}",
        f"# location  : {lat:.4f}, {lon:.4f}  (from {source})",
        f"# ramp from : {info['anchor_name'].replace('_', ' ')} at "
        f"{info['anchor'].strftime('%H:%M')}",
        f"# sunset    : {info['sunset'].strftime('%H:%M')}"
        f"   sunrise: {info['sunrise'].strftime('%H:%M')}"
        + ("   (estimated: the sun did not set)" if info["degenerate"] else ""),
        f"# ramp      : {settings['evening_temp']}K -> {settings['night_temp']}K"
        f" by {info['ramp_end'].strftime('%H:%M')}"
        f" ({int((info['ramp_end'] - info['ramp_start']).total_seconds() // 60)} min,"
        f" curve {settings['ramp_curve_power']})",
    ]
    if info.get("morning_anchor_name"):
        lines.append(
            f"# morning   : {settings['night_temp']}K -> {settings['evening_temp']}K"
            f" from {info['morning_start'].strftime('%H:%M')}"
            f" ({info['morning_anchor_name'].replace('_', ' ')}"
            f" {info['morning_anchor'].strftime('%H:%M')}), day at"
            f" {info['day_start'].strftime('%H:%M')}")
    lines.append("")
    # hyprsunset treats the profile list as a 24h cycle and wraps past the last
    # entry, so plain chronological order by clock time is what it wants.
    for when, temp in sorted(steps, key=lambda item: item[0].strftime("%H:%M")):
        lines.append("profile {")
        lines.append(f"    time = {when.strftime('%H:%M')}")
        if temp is None:
            lines.append("    identity = true")
        else:
            lines.append(f"    temperature = {temp}")
        lines.append("}")
        lines.append("")
    return "\n".join(lines)
