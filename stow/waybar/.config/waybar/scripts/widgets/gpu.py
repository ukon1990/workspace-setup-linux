import csv

from .common import classes, perf_text, push_history, run, use_compact_perf_text


def number(value):
    try:
        return float(value)
    except ValueError:
        return None


def gpu_module(state):
    result = run(
        [
            "nvidia-smi",
            "--query-gpu=name,utilization.gpu,memory.used,memory.total,temperature.gpu,power.draw,power.limit",
            "--format=csv,noheader,nounits",
        ]
    )
    compact = use_compact_perf_text(state)
    rows = list(csv.reader(result.stdout.splitlines())) if result.returncode == 0 else []
    rows = [list(map(str.strip, row)) for row in rows if len(row) == 7]
    if not rows:
        history = push_history(state, "gpu_history", 0)
        return {
            "text": perf_text("󰢮", "n/a", history, compact),
            "tooltip": "GPU metrics unavailable right now",
            "class": classes("metric", "muted", "compact" if compact else None),
        }
    lines = []
    for name, util, used, total, temp, power, limit in rows:
        if lines:
            lines.append("")
        lines.append(name)
        for label, raw, unit in [
            ("GPU usage", util, "%"),
            ("Temperature", temp, " °C"),
            ("Power draw", power, " W"),
            ("Power limit", limit, " W"),
        ]:
            value = number(raw)
            lines.append(
                f"{label}: {value:g}{unit}" if value is not None else f"{label}: Unavailable"
            )
        mem_used, mem_total = number(used), number(total)
        lines.append(
            f"VRAM: {mem_used:g} / {mem_total:g} MiB ({mem_used / mem_total * 100:.1f}%)"
            if mem_used is not None and mem_total and mem_total > 0
            else "VRAM: Unavailable"
        )
    usage = number(rows[0][1])
    history = push_history(state, "gpu_history", usage or 0)
    return {
        "text": perf_text("󰢮", f"{usage:.0f}%" if usage is not None else "n/a", history, compact),
        "tooltip": "\n".join(lines),
        "class": classes("metric", "compact" if compact else None),
    }
