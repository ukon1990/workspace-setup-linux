import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path.home() / "scripts"))
import rofi_menu  # noqa: E402
import wofi_anchor  # noqa: E402

from .common import icon, run
from .tooltip import esc, header, hint, render, table

HYPRSUNSET_CONF = Path.home() / ".config" / "hypr" / "hyprsunset.conf"
HYPRSUNSET_MIN_K = 1000
HYPRSUNSET_MAX_K = 6500
HYPRSUNSET_STEP_K = 250
HYPRSUNSET_DEFAULT_K = 4500
HYPRSUNSET_DEFAULT_GAMMA = 0.9
HYPRSUNSET_SCHED_START = "# >>> widget:schedule"
HYPRSUNSET_SCHED_END = "# <<< widget:schedule"
MENU_WIDTH = 440


def hyprsunset_state(state):
    data = state.get("hyprsunset") or {}
    enabled = bool(data.get("enabled", False))
    temp = int(data.get("temperature", HYPRSUNSET_DEFAULT_K))
    temp = max(HYPRSUNSET_MIN_K, min(HYPRSUNSET_MAX_K, temp))
    state["hyprsunset"] = {"enabled": enabled, "temperature": temp}
    return state["hyprsunset"]


def _read_schedule():
    """Return (start_hhmm, end_hhmm, night_temp, night_gamma) from managed block."""
    defaults = ("21:00", "07:30", HYPRSUNSET_DEFAULT_K, HYPRSUNSET_DEFAULT_GAMMA)
    try:
        text = HYPRSUNSET_CONF.read_text()
    except FileNotFoundError:
        return defaults

    if HYPRSUNSET_SCHED_START not in text:
        return defaults

    start, end = defaults[0], defaults[1]
    night_temp = defaults[2]
    night_gamma = defaults[3]
    block = text.split(HYPRSUNSET_SCHED_START, 1)[1].split(HYPRSUNSET_SCHED_END, 1)[0]

    profiles = re.findall(r"profile\s*\{([^}]*)\}", block)
    for body in profiles:
        time_match = re.search(r"time\s*=\s*(\d{1,2}:\d{2})", body)
        if not time_match:
            continue
        time_val = time_match.group(1)
        if "identity" in body and "true" in body:
            end = time_val
        else:
            start = time_val
            temp_match = re.search(r"temperature\s*=\s*(\d+)", body)
            gamma_match = re.search(r"gamma\s*=\s*([\d.]+)", body)
            if temp_match:
                night_temp = int(temp_match.group(1))
            if gamma_match:
                night_gamma = float(gamma_match.group(1))

    return start, end, night_temp, night_gamma


def _write_schedule(start_hhmm, end_hhmm, night_temp, night_gamma):
    block_lines = [
        HYPRSUNSET_SCHED_START + " (managed by status_widgets.py hyprsunset-schedule)",
        "profile {",
        f"    time = {end_hhmm}",
        "    identity = true",
        "}",
        "",
        "profile {",
        f"    time = {start_hhmm}",
        f"    temperature = {int(night_temp)}",
        f"    gamma = {float(night_gamma):g}",
        "}",
        HYPRSUNSET_SCHED_END,
    ]
    block = "\n".join(block_lines) + "\n"

    try:
        existing = HYPRSUNSET_CONF.read_text()
    except FileNotFoundError:
        HYPRSUNSET_CONF.parent.mkdir(parents=True, exist_ok=True)
        HYPRSUNSET_CONF.write_text("max-gamma = 150\n\n" + block)
        return

    if HYPRSUNSET_SCHED_START in existing and HYPRSUNSET_SCHED_END in existing:
        before = existing.split(HYPRSUNSET_SCHED_START, 1)[0]
        after = existing.split(HYPRSUNSET_SCHED_END, 1)[1].lstrip("\n")
        new_text = before.rstrip() + "\n\n" + block + ("\n" + after if after else "")
    else:
        new_text = existing.rstrip() + "\n\n" + block

    HYPRSUNSET_CONF.write_text(new_text)


def _next_transition(now, start_hhmm, end_hhmm):
    """Return (label, hhmm) of the next schedule transition from `now`."""

    def _minutes(hhmm):
        h, m = hhmm.split(":")
        return int(h) * 60 + int(m)

    try:
        start_m = _minutes(start_hhmm)
        end_m = _minutes(end_hhmm)
    except Exception:
        return ("next", start_hhmm)

    cur_m = now.tm_hour * 60 + now.tm_min
    candidates = sorted(
        [("Night starts", start_m, start_hhmm), ("Night ends", end_m, end_hhmm)],
        key=lambda item: (item[1] - cur_m) % (24 * 60) or 24 * 60,
    )
    label, _, hhmm = candidates[0]
    return (label, hhmm)


def _parse_hhmm(value):
    value = (value or "").strip()
    match = re.match(r"^(\d{1,2}):(\d{2})$", value)
    if not match:
        return None
    hh = int(match.group(1))
    mm = int(match.group(2))
    if not (0 <= hh < 24 and 0 <= mm < 60):
        return None
    return f"{hh:02d}:{mm:02d}"


def hyprsunset_module(state):
    data = hyprsunset_state(state)
    start, end, night_temp, night_gamma = _read_schedule()

    if data["enabled"]:
        glyph = "󰖙"
        text = f"{icon(glyph)} {data['temperature']}K"
        klass = "active"
    else:
        glyph = "󰖚"
        text = f"{icon(glyph)} off"
        klass = "muted"

    try:
        now = time.localtime()
    except Exception:
        now = None

    rows = [("Schedule", f"{start} \u2192 {end} · {night_temp} K, \u03b3 {night_gamma:g}")]
    if now is not None:
        label, hhmm = _next_transition(now, start, end)
        rows.append(("Next", f"{esc(label)} at {hhmm}"))
    tooltip_lines = [
        header("NIGHT LIGHT", f"On · {data['temperature']} K" if data["enabled"] else "Off"),
        *table(rows),
        "",
        hint("Click toggle · Right-click presets · Middle-click reset · Scroll \u00b1250 K"),
    ]

    return {
        "text": text,
        **render(tooltip_lines),
        "class": klass,
        "alt": "active" if data["enabled"] else "muted",
    }


def _hyprctl(*args):
    return run(["hyprctl", "hyprsunset", *args])


def hyprsunset_toggle(state, _argv):
    data = hyprsunset_state(state)
    if data["enabled"]:
        _hyprctl("identity")
        data["enabled"] = False
    else:
        temp = data["temperature"] or HYPRSUNSET_DEFAULT_K
        _hyprctl("temperature", str(temp))
        data["enabled"] = True
        data["temperature"] = temp
    state["hyprsunset"] = data


def hyprsunset_adjust(state, argv):
    data = hyprsunset_state(state)
    delta = 0
    if argv:
        try:
            delta = int(argv[0])
        except ValueError:
            delta = 0
    if delta == 0:
        return
    new_temp = max(HYPRSUNSET_MIN_K, min(HYPRSUNSET_MAX_K, data["temperature"] + delta))
    _hyprctl("temperature", str(new_temp))
    data["enabled"] = True
    data["temperature"] = new_temp
    state["hyprsunset"] = data


def hyprsunset_reset(state, _argv):
    _hyprctl("reset")
    data = hyprsunset_state(state)
    data["enabled"] = False
    state["hyprsunset"] = data


def _apply_preset(state, choice):
    data = hyprsunset_state(state)
    normalized = (choice or "").strip().lower().rstrip("k").strip()
    if normalized in ("off", "identity", ""):
        _hyprctl("identity")
        data["enabled"] = False
    else:
        try:
            temp = int(normalized)
        except ValueError:
            return
        temp = max(HYPRSUNSET_MIN_K, min(HYPRSUNSET_MAX_K, temp))
        _hyprctl("temperature", str(temp))
        data["enabled"] = True
        data["temperature"] = temp
    state["hyprsunset"] = data


# Preset temperatures with the tint each gives the screen (for the menu chips).
PRESETS = (
    (2500, "#ffa148"),
    (3500, "#ffc489"),
    (4500, "#ffdbba"),
    (5500, "#ffecdf"),
    (6500, "#fff9fd"),
)
SCHEDULE_FIELDS = (
    ("Night starts", "24-hour HH:MM"),
    ("Night ends", "24-hour HH:MM"),
    ("Night temperature", f"{HYPRSUNSET_MIN_K}\u2013{HYPRSUNSET_MAX_K} K"),
    ("Brightness (gamma)", "0.1\u20132.0"),
)


def _menu_rows():
    stroke = rofi_menu.colors()["muted"]
    line = f'fill="none" stroke="{stroke}" stroke-width="4" stroke-linecap="round"'
    rows = [
        rofi_menu.Row(
            f"<b>{kelvin}</b>",
            rofi_menu.svg_icon(f"night-{kelvin}", f'<circle cx="32" cy="32" r="24" fill="{tint}"/>', 64),
        )
        for kelvin, tint in PRESETS
    ]
    extras = (
        ("Off", "off", f'<circle cx="32" cy="32" r="22" {line} stroke-dasharray="7 7"/>'),
        (
            "Schedule",
            "schedule",
            f'<circle cx="32" cy="32" r="22" {line}/><path d="M32 18v14l9 6" {line}/>',
        ),
        (
            "Auto",
            "follow",
            f'<path d="M46 22a18 18 0 1 0 4 14" {line}/><path d="M48 10v13H35" {line}/>',
        ),
    )
    rows += [rofi_menu.Row(name, rofi_menu.svg_icon(f"night-{key}", body, 64)) for name, key, body in extras]
    return rows


def hyprsunset_menu(state, _argv):
    """Right-click panel: pick a tint, turn it off, edit or return to the schedule."""
    if not shutil.which("rofi"):
        return
    data = hyprsunset_state(state)
    start, end, night_temp, _gamma = _read_schedule()
    kelvins = [kelvin for kelvin, _ in PRESETS]
    status = f"On \u00b7 {data['temperature']} K" if data["enabled"] else "Off"
    selected = kelvins.index(data["temperature"]) if data["enabled"] and data["temperature"] in kelvins else len(kelvins)
    choice = rofi_menu.pick(
        _menu_rows(),
        header=(
            f"{rofi_menu.label('NIGHT LIGHT')}  <b>{status}</b>"
            f"      <span alpha='65%'>Night {start} \u2192 {end}</span>"
        ),
        hint=rofi_menu.hints(("arrows", "select"), ("Enter", "apply"), ("Esc", "close")),
        selected=selected,
        width=MENU_WIDTH,
        columns=4,
        icon_size=44,
        anchor=wofi_anchor.cursor_anchor(),
    )
    if choice.index is None:
        return
    if choice.index < len(kelvins):
        _apply_preset(state, f"{kelvins[choice.index]}K")
    elif choice.index == len(kelvins):
        _apply_preset(state, "off")
    elif choice.index == len(kelvins) + 1:
        hyprsunset_schedule(state, [])
    else:
        hyprsunset_reset(state, [])


def _parse_schedule_field(index, text):
    """Validate one typed schedule value; None when it is out of range."""
    if index < 2:
        return _parse_hhmm(text)
    try:
        number = float(text.lower().rstrip("k").strip())
    except ValueError:
        return None
    if index == 2:
        return int(number) if HYPRSUNSET_MIN_K <= number <= HYPRSUNSET_MAX_K else None
    return number if 0.1 <= number <= 2.0 else None


def hyprsunset_schedule(state, _argv):
    """Edit the night schedule in the panel: pick a field, type a value, Enter saves."""
    values = list(_read_schedule())
    saved = list(values)
    selected = 0
    title = f"{rofi_menu.label('NIGHT LIGHT')}  <b>Schedule</b>"
    while True:
        shown = [values[0], values[1], f"{values[2]} K", f"{values[3]:g}"]
        choice = rofi_menu.pick(
            [
                rofi_menu.Row(f"{name}   <span alpha='70%'><tt>{value}</tt></span>")
                for (name, _), value in zip(SCHEDULE_FIELDS, shown)
            ],
            header=f"{title}      <span alpha='65%'>Applies every day</span>",
            hint=rofi_menu.hints(("Enter", "edit"), ("Esc", "done")),
            selected=selected,
            width=MENU_WIDTH,
        )
        if choice.index is None:
            break
        selected = choice.index
        name, allowed = SCHEDULE_FIELDS[selected]
        hint = f"{allowed}  \u00b7  Enter saves  \u00b7  Esc back"
        while (text := rofi_menu.ask(name, f"{values[selected]:g}" if selected == 3 else str(values[selected]), header=title, hint=hint, width=MENU_WIDTH)) is not None:
            value = _parse_schedule_field(selected, text)
            if value is not None:
                values[selected] = value
                break
            hint = f"Not valid. Allowed: {allowed}"

    if values == saved:
        return
    _write_schedule(*values)
    subprocess.run(["pkill", "-x", "hyprsunset"], check=False)
    subprocess.Popen(
        ["hyprsunset"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
