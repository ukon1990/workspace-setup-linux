import csv

from .common import classes, perf_text, push_history, run, use_compact_perf_text
from .tooltip import header, meter, render, table


def number(value):
    try:
        return float(value)
    except ValueError:
        return None


def shown(raw, unit):
    value = number(raw)
    return f"{value:g}{unit}" if value is not None else "Unavailable"


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
            "text": perf_text("GPU", "n/a", history, compact),
            "tooltip": "GPU metrics unavailable right now",
            "class": classes("metric", "muted", "compact" if compact else None),
        }
    lines = []
    for name, util, used, total, temp, power, limit in rows:
        if lines:
            lines.append("")
        load, mem_used, mem_total = number(util), number(used), number(total)
        facts = [("Load", f"{meter(load)}  <b>{load:g}%</b>" if load is not None else "Unavailable")]
        if mem_used is not None and mem_total:
            vram = mem_used / mem_total * 100
            facts += [("VRAM", f"{meter(vram)}  {vram:.1f}%"), ("", f"{mem_used:g} / {mem_total:g} MiB")]
        else:
            facts.append(("VRAM", "Unavailable"))
        facts += [("Temp", shown(temp, " °C")), ("Power", f"{shown(power, '')} / {shown(limit, ' W')}")]
        lines += [header("GPU", name), *table(facts)]
    usage = number(rows[0][1])
    history = push_history(state, "gpu_history", usage or 0)
    return {
        "text": perf_text("GPU", f"{usage:.0f}%" if usage is not None else "n/a", history, compact),
        **render(lines),
        "class": classes("metric", "compact" if compact else None),
    }
