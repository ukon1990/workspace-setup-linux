"""Race-tolerant /proc snapshots, without reading process command lines."""

import os
from pathlib import Path

PROC = Path("/proc")


def snapshot():
    result = {}
    for directory in PROC.iterdir():
        if not directory.name.isdigit():
            continue
        try:
            raw = (directory / "stat").read_text()
            end = raw.rindex(")")
            fields = raw[end + 2 :].split()
            result[directory.name] = {
                "name": raw[raw.index("(") + 1 : end].replace("\n", " "),
                "ticks": int(fields[11]) + int(fields[12]),
                "start": fields[19],
                "rss": max(0, int(fields[21])) * os.sysconf("SC_PAGE_SIZE"),
            }
        except (OSError, ValueError, IndexError):
            continue
    return result


def top_cpu(current, previous, elapsed):
    rows = []
    if elapsed <= 0:
        return rows
    ticks_per_second = os.sysconf("SC_CLK_TCK")
    for pid, data in current.items():
        old = previous.get(pid)
        if old and old["start"] == data["start"]:
            usage = max(0, data["ticks"] - old["ticks"]) / ticks_per_second / elapsed * 100
            rows.append((usage, pid, data["name"]))
    return sorted(rows, reverse=True)[:5]


def top_memory(current):
    return sorted(
        ((data["rss"], pid, data["name"]) for pid, data in current.items()), reverse=True
    )[:5]
