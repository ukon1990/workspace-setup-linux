from pathlib import Path

from .common import classes, perf_text, push_history, use_compact_perf_text
from .formatting import human_bytes
from .processes import snapshot, top_memory
from .tooltip import header, meter, ranking, render, table


def memory_module(state):
    info = {}
    for line in Path("/proc/meminfo").read_text().splitlines():
        key, value = line.split(":", 1)
        info[key] = int(value.split()[0]) * 1024
    total = max(info.get("MemTotal", 0), 1)
    available = info.get("MemAvailable", 0)
    used = total - available
    percent = used / total * 100
    cache = max(0, info.get("Cached", 0) + info.get("SReclaimable", 0) - info.get("Shmem", 0))
    swap = info.get("SwapTotal", 0)
    lines = [
        header("MEMORY", f"{human_bytes(used)} / {human_bytes(total)}"),
        f"<tt>{meter(percent)}  <b>{percent:.1f}%</b></tt>",
        *table(
            [
                ("Available", human_bytes(available)),
                ("Cache", human_bytes(cache)),
                ("Swap", f"{human_bytes(swap - info.get('SwapFree', 0))} / {human_bytes(swap)}"),
            ]
        ),
        *ranking(
            "TOP PROCESSES",
            "resident",
            [(name, f"{human_bytes(rss):>10}") for rss, _pid, name in top_memory(snapshot())],
        ),
    ]
    history = push_history(state, "mem_history", percent)
    compact = use_compact_perf_text(state)
    return {
        "text": perf_text("RAM", f"{percent:.0f}%", history, compact),
        **render(lines),
        "class": classes("metric", "compact" if compact else None),
    }
