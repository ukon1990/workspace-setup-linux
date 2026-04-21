#!/usr/bin/env python3
import json
import re
import sys


def active_monitor(monitors, name):
    monitor = monitors.get(name)
    if not monitor or monitor.get("disabled"):
        return None
    return monitor


def parse_mode(mode):
    match = re.match(r"^(?P<width>\d+)x(?P<height>\d+)@(?P<refresh>[\d.]+)Hz$", mode)
    if not match:
        return None
    return {
        "text": mode,
        "width": int(match.group("width")),
        "height": int(match.group("height")),
        "refresh": float(match.group("refresh")),
    }


def best_mode(modes, width=None):
    candidates = [mode for mode in modes if width is None or mode["width"] == width]
    if not candidates:
        return None
    return max(candidates, key=lambda mode: (mode["height"], mode["width"], mode["refresh"]))


def choose_main_mode(monitor):
    modes = [parsed for parsed in (parse_mode(mode) for mode in monitor.get("availableModes", [])) if parsed]
    if not modes:
        return "preferred"

    current_width = int(monitor["width"])
    current_height = int(monitor["height"])
    native_mode = best_mode(modes)
    width_matched_mode = best_mode(modes, current_width)

    # Some Samsung ultrawide split/PIP states report reduced-width modes as
    # current/preferred even though the full native mode is available.
    # If the monitor is in a narrower mode than native, force native.
    if (
        current_width != native_mode["width"]
        and native_mode["width"] > current_width
        and native_mode["height"] >= current_height
    ):
        return native_mode["text"]

    # Keep an extra guard for odd reduced-height PIP states.
    if (
        width_matched_mode
        and width_matched_mode["height"] < native_mode["height"]
        and current_width >= 3840
        and native_mode["width"] > current_width
    ):
        return native_mode["text"]

    if width_matched_mode:
        return width_matched_mode["text"]

    return native_mode["text"]


def choose_secondary_mode(monitor):
    modes = [parsed for parsed in (parse_mode(mode) for mode in monitor.get("availableModes", [])) if parsed]
    if not modes:
        return "preferred"

    current_width = int(monitor["width"])
    current_mode = best_mode(modes, current_width)
    if current_mode:
        return current_mode["text"]
    return best_mode(modes)["text"]


def mode_dimensions(mode_text):
    parsed = parse_mode(mode_text)
    if not parsed:
        return None
    return parsed["width"], parsed["height"]


def main():
    main_name = sys.argv[1]
    secondary_name = sys.argv[2]
    monitors = {monitor["name"]: monitor for monitor in json.load(sys.stdin)}

    main_monitor = active_monitor(monitors, main_name)
    secondary_monitor = active_monitor(monitors, secondary_name)

    state_parts = []
    commands = []

    if main_monitor:
        main_refresh = float(main_monitor.get("refreshRate", 0.0))
        state_parts.append(
            "{}:{}x{}@{:.3f}".format(main_name, main_monitor["width"], main_monitor["height"], main_refresh)
        )
        main_mode = choose_main_mode(main_monitor)
        commands.append("{}, {}, 0x0, 1".format(main_name, main_mode))
        selected_dimensions = mode_dimensions(main_mode)
        if selected_dimensions:
            _, main_height = selected_dimensions
        else:
            # Fall back to current dimensions when mode string isn't parseable (e.g. "preferred").
            main_height = int(main_monitor["height"])
    else:
        main_height = 0

    if secondary_monitor:
        secondary_refresh = float(secondary_monitor.get("refreshRate", 0.0))
        state_parts.append(
            "{}:{}x{}@{:.3f}".format(
                secondary_name, secondary_monitor["width"], secondary_monitor["height"], secondary_refresh
            )
        )
        secondary_mode = choose_secondary_mode(secondary_monitor)
        commands.append(
            "{}, {}, 0x{}, 1".format(
                secondary_name, secondary_mode, main_height if main_height > 0 else 0
            )
        )

    print("STATE\t" + "|".join(state_parts))
    for command in commands:
        print("CMD\t" + command)


if __name__ == "__main__":
    main()
