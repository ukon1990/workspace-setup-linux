#!/usr/bin/env python3

import json
import os
import subprocess
import sys


SLOTS_PER_MONITOR = int(os.environ.get("WORKSPACE_SLOTS_PER_MONITOR", "5"))
PREFERRED_MONITORS = [
    os.environ.get("MAIN_MONITOR", "DP-1"),
    os.environ.get("SECONDARY_MONITOR", "HDMI-A-1"),
]


def run(*args):
    return subprocess.run(args, capture_output=True, text=True, check=False)


def hypr_json(*args):
    result = run("hyprctl", *args)
    if result.returncode != 0 or not result.stdout.strip():
        raise RuntimeError("hyprctl returned no data")
    return json.loads(result.stdout)


def ordered_monitors(monitors):
    by_name = {monitor["name"]: monitor for monitor in monitors if monitor.get("name")}
    ordered = []

    for name in PREFERRED_MONITORS:
        monitor = by_name.pop(name, None)
        if monitor:
            ordered.append(monitor)

    ordered.extend(sorted(by_name.values(), key=lambda monitor: monitor["name"]))
    return ordered


def focused_monitor(monitors):
    for monitor in monitors:
        if monitor.get("focused"):
            return monitor
    raise RuntimeError("no focused monitor found")


def workspace_id_for_slot(slot):
    monitors = hypr_json("monitors", "-j")
    focused = focused_monitor(monitors)
    ordered = ordered_monitors(monitors)
    monitor_names = [monitor["name"] for monitor in ordered]

    try:
        monitor_index = monitor_names.index(focused["name"])
    except ValueError as exc:
        raise RuntimeError("focused monitor missing from monitor list") from exc

    return focused["name"], monitor_index * SLOTS_PER_MONITOR + slot


def maybe_move_workspace(target_workspace, monitor_name):
    workspaces = hypr_json("workspaces", "-j")
    for workspace in workspaces:
        if int(workspace.get("id", -1)) != target_workspace:
            continue
        if workspace.get("monitor") == monitor_name:
            return
        run("hyprctl", "dispatch", "moveworkspacetomonitor", str(target_workspace), monitor_name)
        return


def main():
    if len(sys.argv) != 3 or sys.argv[1] not in {"switch", "move"}:
        print("Usage: workspace-slot.py [switch|move] <slot>", file=sys.stderr)
        raise SystemExit(1)

    try:
        slot = int(sys.argv[2])
    except ValueError:
        print("slot must be an integer", file=sys.stderr)
        raise SystemExit(1)

    if slot < 1 or slot > SLOTS_PER_MONITOR:
        print(f"slot must be between 1 and {SLOTS_PER_MONITOR}", file=sys.stderr)
        raise SystemExit(1)

    try:
        monitor_name, target_workspace = workspace_id_for_slot(slot)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1)

    if sys.argv[1] == "switch":
        maybe_move_workspace(target_workspace, monitor_name)
        run("hyprctl", "dispatch", "workspace", str(target_workspace))
    else:
        run("hyprctl", "dispatch", "movetoworkspace", str(target_workspace))


if __name__ == "__main__":
    main()
