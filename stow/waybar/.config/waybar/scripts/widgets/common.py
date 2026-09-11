"""Shared rendering, monitor detection and bounded metric commands."""

import json
import os
import subprocess
import time

SPARKS = "▁▂▃▄▅▆▇█"
HISTORY_LIMIT = 18
MONITOR_CACHE_TTL = 2.0
PERF_PRIMARY_MONITOR = os.environ.get("MAIN_MONITOR", "DP-1")
PERF_FULL_WIDTH = 5120


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
    try:
        return subprocess.run(command, capture_output=True, text=True, check=False, timeout=3)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return subprocess.CompletedProcess(command, 1, "", str(exc))


def monitor_widths(state):
    cached = state.get("monitor_widths")
    now = time.time()
    if isinstance(cached, dict) and (now - cached.get("time", 0.0)) < MONITOR_CACHE_TTL:
        widths = cached.get("widths")
        if isinstance(widths, dict):
            return widths

    widths = {}
    result = run(["hyprctl", "monitors", "-j"])
    if result.returncode == 0 and result.stdout.strip():
        try:
            for monitor in json.loads(result.stdout):
                name = monitor.get("name")
                width = monitor.get("width")
                if name and width:
                    widths[str(name)] = int(width)
        except Exception:
            widths = {}

    state["monitor_widths"] = {"time": now, "widths": widths}
    return widths


def use_compact_perf_text(state):
    width = monitor_widths(state).get(PERF_PRIMARY_MONITOR)
    return width is not None and width < PERF_FULL_WIDTH


def perf_text(icon, primary, history, compact=False):
    if compact:
        return f"{icon}  {primary}"
    return f"{icon} {primary} {sparkline(history)}"


def classes(*names):
    return [name for name in names if name]
