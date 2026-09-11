import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from .common import run

HYPRSUNSET_CONF = Path.home() / ".config" / "hypr" / "hyprsunset.conf"
HYPRSUNSET_MIN_K = 1000
HYPRSUNSET_MAX_K = 6500
HYPRSUNSET_STEP_K = 250
HYPRSUNSET_DEFAULT_K = 4500
HYPRSUNSET_DEFAULT_GAMMA = 0.9
HYPRSUNSET_SCHED_START = "# >>> widget:schedule"
HYPRSUNSET_SCHED_END = "# <<< widget:schedule"


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
        icon = "󰖙"
        text = f"{icon} {data['temperature']}K"
        klass = "active"
    else:
        icon = "󰖚"
        text = f"{icon} off"
        klass = "muted"

    try:
        now = time.localtime()
    except Exception:
        now = None

    tooltip_lines = []
    if data["enabled"]:
        tooltip_lines.append(f"Sunset: on ({data['temperature']} K)")
    else:
        tooltip_lines.append("Sunset: off (identity)")

    tooltip_lines.append(f"Schedule: {start} \u2192 {end}  ({night_temp} K, \u03b3 {night_gamma:g})")
    if now is not None:
        label, hhmm = _next_transition(now, start, end)
        tooltip_lines.append(f"Next: {label} at {hhmm}")

    tooltip_lines.append("")
    tooltip_lines.append("Left click: toggle on/off")
    tooltip_lines.append("Right click: preset menu / edit schedule")
    tooltip_lines.append("Middle click: reset to current profile")
    tooltip_lines.append("Scroll: warmer \u2195 cooler (\u00b1250 K)")

    return {
        "text": text,
        "tooltip": "\n".join(tooltip_lines),
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


def hyprsunset_menu(state, _argv):
    if not shutil.which("wofi"):
        return
    entries = [
        "2500K",
        "3500K",
        "4500K",
        "5500K",
        "6500K",
        "off",
        "Edit schedule\u2026",
    ]
    result = subprocess.run(
        ["wofi", "--dmenu", "--prompt", "Sunset"],
        input="\n".join(entries),
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return
    choice = result.stdout.strip()
    if not choice:
        return
    if choice.startswith("Edit schedule"):
        hyprsunset_schedule(state, [])
        return
    _apply_preset(state, choice)


def hyprsunset_schedule(state, _argv):
    start, end, night_temp, night_gamma = _read_schedule()

    if not shutil.which("yad"):
        sys.stderr.write(
            "status_widgets.py hyprsunset-schedule: `yad` not installed. "
            "Run: sudo pacman -S yad\n"
        )
        return

    fields = [
        "--field=Night starts (HH:MM)",
        "--field=Night ends (HH:MM)",
        "--field=Night temperature (K):NUM",
        "--field=Night gamma (0.1..2.0):NUM",
    ]
    values = [
        start,
        end,
        f"{int(night_temp)}!{HYPRSUNSET_MIN_K}..{HYPRSUNSET_MAX_K}!{HYPRSUNSET_STEP_K}",
        f"{float(night_gamma):g}!0.1..2.0!0.05",
    ]
    result = subprocess.run(
        [
            "yad",
            "--form",
            "--title=Hyprsunset Schedule",
            "--center",
            "--width=360",
            "--separator=|",
            *fields,
            *values,
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return

    parts = result.stdout.rstrip("\n").split("|")
    if len(parts) < 4:
        return

    new_start = _parse_hhmm(parts[0]) or start
    new_end = _parse_hhmm(parts[1]) or end
    try:
        new_temp = int(float(parts[2]))
    except ValueError:
        new_temp = night_temp
    try:
        new_gamma = float(parts[3])
    except ValueError:
        new_gamma = night_gamma

    new_temp = max(HYPRSUNSET_MIN_K, min(HYPRSUNSET_MAX_K, new_temp))
    new_gamma = max(0.1, min(2.0, new_gamma))

    _write_schedule(new_start, new_end, new_temp, new_gamma)

    subprocess.run(["pkill", "-x", "hyprsunset"], check=False)
    subprocess.Popen(
        ["hyprsunset"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
