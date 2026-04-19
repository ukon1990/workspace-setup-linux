#!/usr/bin/env python3

import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path


STATE_PATH = Path.home() / ".config" / "waybar" / ".cache" / "status-widgets.json"
SPARKS = "▁▂▃▄▅▆▇█"
HISTORY_LIMIT = 18


def load_state():
    try:
        return json.loads(STATE_PATH.read_text())
    except Exception:
        return {}


def save_state(state):
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state))


def clamp(value, lower=0.0, upper=100.0):
    return max(lower, min(upper, value))


def push_history(state, key, value):
    history = state.get(key, [])
    history.append(round(float(value), 2))
    state[key] = history[-HISTORY_LIMIT:]
    return state[key]


def fixed_history(values):
    recent = values[-HISTORY_LIMIT:]
    if len(recent) < HISTORY_LIMIT:
        recent = [0.0] * (HISTORY_LIMIT - len(recent)) + recent
    return recent


def sparkline(values):
    return "".join(
        SPARKS[min(len(SPARKS) - 1, int(round(clamp(v) / 100 * (len(SPARKS) - 1))))]
        for v in fixed_history(values)
    )


def run(command):
    return subprocess.run(command, capture_output=True, text=True, check=False)


def default_route_iface():
    try:
        with open("/proc/net/route", "r", encoding="utf-8") as handle:
            next(handle)
            for line in handle:
                fields = line.split()
                if len(fields) > 2 and fields[1] == "00000000":
                    return fields[0]
    except Exception:
        return None
    return None


def human_rate(bytes_per_second):
    if bytes_per_second < 1024:
        return f"{bytes_per_second:.0f}B/s"
    if bytes_per_second < 1024 ** 2:
        return f"{bytes_per_second / 1024:.1f}K/s"
    if bytes_per_second < 1024 ** 3:
        return f"{bytes_per_second / 1024 ** 2:.1f}M/s"
    return f"{bytes_per_second / 1024 ** 3:.1f}G/s"


def compact_rate(bytes_per_second):
    if bytes_per_second < 1024 ** 2:
        return f"{bytes_per_second / 1024:4.0f}K"
    if bytes_per_second < 1024 ** 3:
        return f"{bytes_per_second / 1024 ** 2:4.1f}M"
    return f"{bytes_per_second / 1024 ** 3:4.1f}G"


def volume_bar(percent):
    filled = int(round(clamp(percent) / 100 * 8))
    return "▁▂▃▄▅▆▇█"[max(0, filled - 1)] if filled else "·"


def cpu_module(state):
    with open("/proc/stat", "r", encoding="utf-8") as handle:
        parts = handle.readline().split()[1:]
    values = [int(x) for x in parts]
    idle = values[3] + values[4]
    total = sum(values)
    now = time.time()

    prev = state.get("cpu_prev")
    usage = 0.0
    if prev:
        total_delta = total - prev["total"]
        idle_delta = idle - prev["idle"]
        if total_delta > 0:
            usage = (1 - idle_delta / total_delta) * 100

    state["cpu_prev"] = {"total": total, "idle": idle, "time": now}
    history = push_history(state, "cpu_history", usage)
    return {
        "text": f" {usage:4.0f}% {sparkline(history)}",
        "tooltip": f"CPU usage: {usage:.1f}%",
        "class": "metric",
    }


def memory_module(state):
    info = {}
    with open("/proc/meminfo", "r", encoding="utf-8") as handle:
        for line in handle:
            key, value = line.split(":", 1)
            info[key] = int(value.strip().split()[0])

    total = info.get("MemTotal", 1)
    available = info.get("MemAvailable", 0)
    used = total - available
    usage = used / total * 100
    history = push_history(state, "mem_history", usage)
    used_gib = used / 1024 / 1024
    total_gib = total / 1024 / 1024
    return {
        "text": f"󰍛 {usage:4.0f}% {sparkline(history)}",
        "tooltip": f"Memory: {used_gib:.1f} / {total_gib:.1f} GiB",
        "class": "metric",
    }


def network_module(state):
    iface = default_route_iface()
    if not iface:
        return {"text": "󰖪 off", "tooltip": "No active network interface", "class": "metric muted"}

    base = Path("/sys/class/net") / iface / "statistics"
    rx = int((base / "rx_bytes").read_text().strip())
    tx = int((base / "tx_bytes").read_text().strip())
    now = time.time()

    prev = state.get("net_prev")
    down_rate = 0.0
    up_rate = 0.0
    if prev and prev.get("iface") == iface:
        elapsed = max(now - prev["time"], 0.001)
        down_rate = max(0.0, (rx - prev["rx"]) / elapsed)
        up_rate = max(0.0, (tx - prev["tx"]) / elapsed)

    state["net_prev"] = {"iface": iface, "rx": rx, "tx": tx, "time": now}
    combined = down_rate + up_rate
    normalized = clamp((combined / (1024 * 1024 * 2)) * 100)
    history = push_history(state, "net_history", normalized)
    return {
        "text": f"󰖟 {compact_rate(combined)} {sparkline(history)}",
        "tooltip": f"{iface}\nDown: {human_rate(down_rate)}\nUp: {human_rate(up_rate)}",
        "class": "metric",
    }


def root_device():
    root_source = None
    with open("/proc/self/mounts", "r", encoding="utf-8") as handle:
        for line in handle:
            source, target, *_rest = line.split()
            if target == "/":
                root_source = source
                break
    if not root_source:
        return None
    return os.path.basename(root_source)


def disk_module(state):
    usage = shutil.disk_usage("/")
    used_pct = usage.used / usage.total * 100
    device = root_device()
    bytes_per_second = 0.0
    if device:
        stat_path = Path("/sys/class/block") / device / "stat"
        if stat_path.exists():
            fields = stat_path.read_text().split()
            sectors = int(fields[2]) + int(fields[6])
            now = time.time()
            prev = state.get("disk_prev")
            if prev and prev.get("device") == device:
                elapsed = max(now - prev["time"], 0.001)
                bytes_per_second = max(0.0, ((sectors - prev["sectors"]) * 512) / elapsed)
            state["disk_prev"] = {"device": device, "sectors": sectors, "time": now}

    normalized = clamp((bytes_per_second / (1024 * 1024 * 200)) * 100)
    history = push_history(state, "disk_history", normalized)
    return {
        "text": f" {used_pct:4.0f}% {sparkline(history)}",
        "tooltip": f"Root usage: {used_pct:.1f}%\nI/O: {human_rate(bytes_per_second)}",
        "class": "metric",
    }


def gpu_module(state):
    command = [
        "nvidia-smi",
        "--query-gpu=utilization.gpu,memory.used,memory.total,temperature.gpu",
        "--format=csv,noheader,nounits",
    ]
    result = run(command)
    if result.returncode != 0 or not result.stdout.strip():
        history = push_history(state, "gpu_history", 0)
        return {
            "text": f"󰢮 n/a {sparkline(history)}",
            "tooltip": "GPU metrics unavailable right now",
            "class": "metric muted",
        }

    util, mem_used, mem_total, temp = [x.strip() for x in result.stdout.strip().split(",")]
    util_f = float(util)
    mem_pct = (float(mem_used) / max(float(mem_total), 1.0)) * 100
    history = push_history(state, "gpu_history", util_f)
    return {
        "text": f"󰢮 {util_f:4.0f}% {sparkline(history)}",
        "tooltip": f"GPU: {util_f:.0f}%\nVRAM: {mem_used}/{mem_total} MiB ({mem_pct:.0f}%)\nTemp: {temp} C",
        "class": "metric",
    }


def inspect_value(output, names):
    for name in names:
        match = re.search(rf"{re.escape(name)}\s*=\s*\"([^\"]+)\"", output)
        if match:
            return match.group(1)
    return None


def volume_module(_state):
    volume_result = run(["wpctl", "get-volume", "@DEFAULT_AUDIO_SINK@"])
    if volume_result.returncode != 0:
        return {
            "text": "󰖁 audio off",
            "tooltip": "Audio server unavailable",
            "class": "metric muted",
        }

    line = volume_result.stdout.strip()
    match = re.search(r"Volume:\s*([0-9.]+)", line)
    if not match:
        return {"text": "󰕾 --", "tooltip": "Could not read volume", "class": "metric"}

    volume = float(match.group(1)) * 100
    muted = "[MUTED]" in line

    inspect = run(["wpctl", "inspect", "@DEFAULT_AUDIO_SINK@"])
    description = "Default sink"
    if inspect.returncode == 0:
        description = (
            inspect_value(inspect.stdout, ["node.description", "node.nick", "device.description"])
            or description
        )

    if muted:
        icon = "󰝟"
        state_class = "metric muted"
    elif volume < 35:
        icon = "󰕿"
        state_class = "metric"
    elif volume < 70:
        icon = "󰖀"
        state_class = "metric"
    else:
        icon = "󰕾"
        state_class = "metric active"

    bar = volume_bar(volume)
    return {
        "text": f"{icon} {volume:3.0f}% {bar}",
        "tooltip": f"{description}\nVolume: {volume:.0f}%\nLeft click: open mixer\nRight click: mute\nScroll: adjust volume",
        "class": state_class,
    }


def _mmss(seconds: int) -> str:
    seconds = max(0, int(seconds))
    return f"{seconds // 60}:{seconds % 60:02d}"


_HIDDEN_MEDIA = {
    "text": "",
    "tooltip": "",
    "class": "media idle",
    "alt": "idle",
}


def _pick_active_player() -> str | None:
    """Prefer a Playing player over a Paused one over the first available."""
    listed = run(["playerctl", "-l"])
    if listed.returncode != 0:
        return None
    names = [line.strip() for line in listed.stdout.splitlines() if line.strip()]
    if not names:
        return None

    playing: list[str] = []
    paused: list[str] = []
    for name in names:
        status_res = run(["playerctl", "--player", name, "status"])
        if status_res.returncode != 0:
            continue
        status = status_res.stdout.strip().lower()
        if status == "playing":
            playing.append(name)
        elif status == "paused":
            paused.append(name)
    if playing:
        return playing[0]
    if paused:
        return paused[0]
    return names[0]


def media_module(_state):
    if not shutil.which("playerctl"):
        return {
            "text": "",
            "tooltip": "playerctl is not installed",
            "class": "media muted",
            "alt": "missing",
        }

    player = _pick_active_player()
    if not player:
        return _HIDDEN_MEDIA

    player_args = ["--player", player]

    sep = "\x1f"
    fmt = sep.join([
        "{{status}}",
        "{{playerName}}",
        "{{artist}}",
        "{{title}}",
        "{{album}}",
        "{{mpris:length}}",
    ])
    result = run(["playerctl", *player_args, "metadata", "--format", fmt])
    if result.returncode != 0 or not result.stdout.strip():
        return _HIDDEN_MEDIA

    parts = result.stdout.strip().split(sep)
    while len(parts) < 6:
        parts.append("")
    status, player_name, artist, title, album, length_raw = (p.strip() for p in parts)

    try:
        length = int(length_raw) // 1_000_000 if length_raw else 0
    except (ValueError, TypeError):
        length = 0

    position = 0
    pos_res = run(["playerctl", *player_args, "position"])
    if pos_res.returncode == 0 and pos_res.stdout.strip():
        try:
            position = int(float(pos_res.stdout.strip()))
        except ValueError:
            position = 0

    status_lower = status.lower()
    if status_lower == "playing":
        icon = ""
        state_class = "playing"
    elif status_lower == "paused":
        icon = ""
        state_class = "paused"
    else:
        return _HIDDEN_MEDIA

    if artist and title:
        display = f"{artist} — {title}"
    elif title:
        display = title
    elif player_name:
        display = player_name
    else:
        display = "Unknown"

    max_len = 48
    if len(display) > max_len:
        display = display[: max_len - 1].rstrip() + "…"

    if length > 0:
        position = max(0, min(position, length))
        percent = (position / length) * 100
        time_str = f"{_mmss(position)} / {_mmss(length)}"
    else:
        percent = 0.0
        time_str = _mmss(position) if position > 0 else ""

    text_parts = [icon, display]
    if time_str:
        text_parts.append(time_str)
    text = "  ".join(p for p in text_parts if p)

    bar_width = 22
    filled = int(round(percent / 100 * bar_width))
    bar = "━" * filled + "─" * (bar_width - filled)

    tooltip_lines = []
    if title:
        tooltip_lines.append(f"Title:  {title}")
    if artist:
        tooltip_lines.append(f"Artist: {artist}")
    if album:
        tooltip_lines.append(f"Album:  {album}")
    if player_name:
        tooltip_lines.append(f"Player: {player_name}")
    tooltip_lines.append(f"Status: {status or 'Unknown'}")
    if length > 0:
        remaining = max(0, length - position)
        tooltip_lines.append("")
        tooltip_lines.append(bar)
        tooltip_lines.append(
            f"{_mmss(position)} / {_mmss(length)}   -{_mmss(remaining)}   ({percent:.0f}%)"
        )
    tooltip_lines.append("")
    tooltip_lines.append("Left click: play/pause")
    tooltip_lines.append("Right click: next track")
    tooltip_lines.append("Middle click: previous track")
    tooltip_lines.append("Scroll: seek ±5s")
    tooltip = "\n".join(tooltip_lines)

    return {
        "text": text,
        "tooltip": tooltip,
        "class": f"media {state_class}",
        "alt": state_class,
    }


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


MODULES = {
    "cpu": cpu_module,
    "memory": memory_module,
    "network": network_module,
    "disk": disk_module,
    "gpu": gpu_module,
    "volume": volume_module,
    "media": media_module,
    "hyprsunset": hyprsunset_module,
}


ACTIONS = {
    "hyprsunset-toggle": hyprsunset_toggle,
    "hyprsunset-adjust": hyprsunset_adjust,
    "hyprsunset-reset": hyprsunset_reset,
    "hyprsunset-menu": hyprsunset_menu,
    "hyprsunset-schedule": hyprsunset_schedule,
}


def main():
    if len(sys.argv) < 2 or (sys.argv[1] not in MODULES and sys.argv[1] not in ACTIONS):
        usage = (
            "Usage: status_widgets.py ["
            + "|".join(list(MODULES) + list(ACTIONS))
            + "]"
        )
        print(json.dumps({"text": "widget?", "tooltip": usage}))
        raise SystemExit(1)

    state = load_state()
    command = sys.argv[1]
    if command in MODULES:
        payload = MODULES[command](state)
        save_state(state)
        print(json.dumps(payload))
    else:
        ACTIONS[command](state, sys.argv[2:])
        save_state(state)


if __name__ == "__main__":
    main()
