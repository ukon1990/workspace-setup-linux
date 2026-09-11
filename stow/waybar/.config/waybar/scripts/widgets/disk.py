import os
import shutil
import time
from pathlib import Path

from .common import clamp, classes, perf_text, push_history, use_compact_perf_text
from .formatting import human_rate


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
    compact = use_compact_perf_text(state)
    return {
        "text": perf_text("", f"{used_pct:.0f}%", history, compact),
        "tooltip": f"Root usage: {used_pct:.1f}%\nI/O: {human_rate(bytes_per_second)}",
        "class": classes("metric", "compact" if compact else None),
    }
