import os
import time
from pathlib import Path

from .common import clamp, classes, perf_text, push_history, use_compact_perf_text
from .processes import snapshot, top_cpu


def temperature():
    for hwmon in Path("/sys/class/hwmon").glob("hwmon*"):
        try:
            if (hwmon / "name").read_text().strip() not in ("k10temp", "coretemp", "zenpower"):
                continue
            sensors = sorted(hwmon.glob("temp*_input"))
            for sensor in sensors:
                label = sensor.with_name(sensor.name.replace("_input", "_label"))
                if label.exists() and label.read_text().strip() in ("Tctl", "Package id 0"):
                    return f"{float(sensor.read_text()) / 1000:.1f} °C"
            if sensors:
                return f"{float(sensors[0].read_text()) / 1000:.1f} °C"
        except (OSError, ValueError):
            continue
    return "Unavailable"


def cpu_module(state):
    values = [int(v) for v in Path("/proc/stat").read_text().splitlines()[0].split()[1:]]
    total, idle = sum(values[:8]), values[3] + values[4]
    previous = state.get("cpu_prev")
    usage = 0.0
    if previous and total > previous["total"]:
        usage = clamp((1 - (idle - previous["idle"]) / (total - previous["total"])) * 100)
    state["cpu_prev"] = {"total": total, "idle": idle}
    history = push_history(state, "cpu_history", usage)
    records = []
    for block in Path("/proc/cpuinfo").read_text().strip().split("\n\n"):
        records.append(dict(line.split(":", 1) for line in block.splitlines() if ":" in line))
    records = [{k.strip(): v.strip() for k, v in record.items()} for record in records]
    model = next((r["model name"] for r in records if "model name" in r), "Unknown CPU")
    cores = {(r.get("physical id", "0"), r["core id"]) for r in records if "core id" in r}
    lines = [
        model,
        f"CPU usage: {usage:.1f}%" if previous else "CPU usage: Collecting…",
        f"Cores / threads: {len(cores) if cores else 'Unknown'} / {len(records)}",
        "Load (1 / 5 / 15 min): " + " / ".join(f"{v:.2f}" for v in os.getloadavg()),
        f"Temperature: {temperature()}",
        "",
        "Top CPU processes (100% = one logical CPU):",
    ]
    now = time.monotonic()
    current = snapshot()
    old = state.get("process_sample")
    if old and now > old["time"]:
        rows = top_cpu(current, old["processes"], now - old["time"])
        lines.extend(f"{name} [{pid}]: {value:.1f}%" for value, pid, name in rows)
        if not rows:
            lines.append("Collecting…")
    else:
        lines.append("Collecting…")
    state["process_sample"] = {"time": now, "processes": current}
    compact = use_compact_perf_text(state)
    return {
        "text": perf_text("", f"{usage:.0f}%", history, compact),
        "tooltip": "\n".join(lines),
        "class": classes("metric", "compact" if compact else None),
    }
