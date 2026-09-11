#!/usr/bin/env python3
"""Network widget collector; publish only app names and byte counts from NetHogs."""

import json
import math
import os
import queue
import subprocess
import tempfile
import threading
import time
from pathlib import Path

OUTPUT = Path("/run/waybar-network/usage.json")
BOOT_ID = Path("/proc/sys/kernel/random/boot_id")


def parse_row(line):
    """Trace format: executable/PID/UID TAB sent bytes TAB received bytes."""
    try:
        identity, sent, received = line.rstrip().split("\t")
        program, pid, uid = identity.rsplit("/", 2)
        sent, received = float(sent), float(received)
        if not all(math.isfinite(v) and v >= 0 for v in (sent, received)):
            return None
        return (program, int(pid), int(uid)), (int(sent), int(received))
    except (ValueError, OverflowError):
        return None


class Accounting:
    def __init__(self, saved, boot_id, now):
        same_boot = saved.get("boot_id") == boot_id
        self.data = {
            "version": 1,
            "boot_id": boot_id,
            "started": saved["started"] if same_boot else now,
            "apps": saved.get("apps", {}) if same_boot else {},
            "interruptions": saved.get("interruptions", 0) + 1 if same_boot else 0,
        }
        self.reset_capture(now)

    def reset_capture(self, now):
        self.previous = {}
        self.last_sample = now
        for app in self.data["apps"].values():
            app["up_rate"] = app["down_rate"] = 0

    def update(self, rows, now):
        elapsed = max(now - self.last_sample, 0.001)
        self.last_sample = now
        for app in self.data["apps"].values():
            app["up_rate"] = app["down_rate"] = 0
        for identity, counters in rows.items():
            program, pid, uid = identity
            old = self.previous.get(identity, (0, 0))
            # NetHogs can reset a process's counters after garbage collection.
            delta = [
                new - prev if new >= prev else new for new, prev in zip(counters, old, strict=True)
            ]
            self.previous[identity] = counters
            name = Path(program).name if pid > 0 else "Unattributed traffic"
            name = "".join(c if c.isprintable() else " " for c in name)[:80]
            key = json.dumps([uid if pid > 0 else -1, name])
            app = self.data["apps"].setdefault(
                key,
                {
                    "name": name,
                    "uid": uid if pid > 0 else -1,
                    "sent": 0,
                    "received": 0,
                    "up_rate": 0,
                    "down_rate": 0,
                },
            )
            app["sent"] += delta[0]
            app["received"] += delta[1]
            app["up_rate"] += delta[0] / elapsed
            app["down_rate"] += delta[1] / elapsed


def default_interface():
    for family in ([], ["-6"]):
        result = subprocess.run(
            ["/usr/bin/ip", "-j", *family, "route", "show", "default"],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
        try:
            routes = [r for r in json.loads(result.stdout) if r.get("dev")]
            if routes:
                return min(routes, key=lambda r: r.get("metric", 0))["dev"]
        except (ValueError, TypeError):
            pass
    return None


def publish(data, interface, status):
    data.update(updated=time.time(), interface=interface, status=status)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".usage-", dir=OUTPUT.parent)
    try:
        with os.fdopen(fd, "w") as handle:
            json.dump(data, handle)
        os.chmod(temporary, 0o644)
        os.replace(temporary, OUTPUT)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def read_trace(pipe, events):
    try:
        for line in pipe:
            events.put(line)
    finally:
        events.put(None)


def capture(accounting, interface):
    # One interface avoids double-counting the same packets across VPN layers.
    command = ["/usr/bin/nethogs", "-t", "-C", "-v", "2", "-d", "2", interface]
    with subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        env={**os.environ, "LC_ALL": "C"},
    ) as process:
        events = queue.Queue()
        thread = threading.Thread(target=read_trace, args=(process.stdout, events), daemon=True)
        thread.start()
        rows, started = {}, False
        last_frame = last_route_check = time.monotonic()
        accounting.reset_capture(last_frame)
        publish(accounting.data, interface, "collecting")
        try:
            while True:
                now = time.monotonic()
                if now - last_route_check >= 5:
                    last_route_check = now
                    if default_interface() != interface:
                        return
                if now - last_frame > 15:
                    raise RuntimeError("NetHogs stopped producing samples")
                try:
                    line = events.get(timeout=1)
                except queue.Empty:
                    continue
                if line is None:
                    raise RuntimeError("NetHogs exited")
                if line.strip() == "Refreshing:":
                    now = time.monotonic()
                    if started:
                        accounting.update(rows, now)
                        publish(accounting.data, interface, "running")
                    rows, started, last_frame = {}, True, now
                elif started:
                    parsed = parse_row(line)
                    if parsed:
                        identity, counters = parsed
                        rows[identity] = counters
        finally:
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
            thread.join(timeout=1)


def main():
    try:
        saved = json.loads(OUTPUT.read_text())
    except (OSError, ValueError):
        saved = {}
    accounting = Accounting(saved, BOOT_ID.read_text().strip(), time.time())
    while True:
        interface = default_interface()
        if interface:
            capture(accounting, interface)
            accounting.data["interruptions"] += 1
        else:
            accounting.reset_capture(time.monotonic())
            publish(accounting.data, None, "offline")
            time.sleep(2)


if __name__ == "__main__":
    main()
