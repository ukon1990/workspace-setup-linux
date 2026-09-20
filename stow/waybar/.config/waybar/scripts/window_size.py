#!/usr/bin/env python3
"""Resize the focused Hyprland window from a Waybar dropdown."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path.home() / "scripts"))
import wofi_anchor  # noqa: E402

FRACTION_CHOICES = (
    ("1/4", Fraction(1, 4)),
    ("2/4", Fraction(2, 4)),
    ("3/4", Fraction(3, 4)),
    ("1/3", Fraction(1, 3)),
    ("2/3", Fraction(2, 3)),
    ("1/2", Fraction(1, 2)),
)
MENU_WIDTH = 320
MENU_HEIGHT = 520


class WindowSizeError(RuntimeError):
    """A user-facing sizing failure."""


@dataclass(frozen=True)
class Geometry:
    x: int
    y: int
    width: int
    height: int


@dataclass(frozen=True)
class SizeOption:
    label: str
    fraction: Fraction
    floating: bool


OPTIONS = tuple(
    SizeOption(f"{mode} · {label}", fraction, floating)
    for mode, floating in (("Tiled", False), ("Float", True))
    for label, fraction in FRACTION_CHOICES
)
OPTIONS_BY_LABEL = {option.label: option for option in OPTIONS}


def run(command: list[str], *, input_text: str | None = None) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            command,
            input=input_text,
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
    except FileNotFoundError as exc:
        raise WindowSizeError(f"{command[0]} is not installed") from exc
    except subprocess.TimeoutExpired as exc:
        raise WindowSizeError(f"{command[0]} timed out") from exc


def run_json(command: list[str]) -> Any:
    result = run(command)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip() or f"exit {result.returncode}"
        raise WindowSizeError(f"{' '.join(command)} failed: {detail}")
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise WindowSizeError(f"{' '.join(command)} returned invalid JSON") from exc


def active_window_and_monitor() -> tuple[dict[str, Any], dict[str, Any]]:
    window = run_json(["hyprctl", "-j", "activewindow"])
    if not isinstance(window, dict) or not window.get("address"):
        raise WindowSizeError("No focused window")

    monitors = run_json(["hyprctl", "-j", "monitors"])
    if not isinstance(monitors, list):
        raise WindowSizeError("Hyprland returned an invalid monitor list")

    monitor = next((item for item in monitors if item.get("id") == window.get("monitor")), None)
    if monitor is None:
        raise WindowSizeError(
            f"Monitor {window.get('monitor')} for the focused window was not found"
        )
    return window, monitor


def work_area(monitor: dict[str, Any]) -> Geometry:
    try:
        monitor_x = int(monitor["x"])
        monitor_y = int(monitor["y"])
        monitor_width = int(monitor["width"])
        monitor_height = int(monitor["height"])
        left, top, right, bottom = (int(value) for value in monitor["reserved"])
    except (KeyError, TypeError, ValueError) as exc:
        raise WindowSizeError("Hyprland returned incomplete monitor geometry") from exc

    area = Geometry(
        x=monitor_x + left,
        y=monitor_y + top,
        width=monitor_width - left - right,
        height=monitor_height - top - bottom,
    )
    if area.width <= 0 or area.height <= 0:
        raise WindowSizeError("The focused monitor has no usable work area")
    return area


def fraction_width(monitor: dict[str, Any], fraction: Fraction) -> int:
    area = work_area(monitor)
    return area.width * fraction.numerator // fraction.denominator


def calculate_floating_geometry(
    window: dict[str, Any], monitor: dict[str, Any], fraction: Fraction
) -> Geometry:
    try:
        window_x, window_y = (int(value) for value in window["at"])
    except (KeyError, TypeError, ValueError) as exc:
        raise WindowSizeError("Hyprland returned incomplete window geometry") from exc

    area = work_area(monitor)
    width = fraction_width(monitor, fraction)
    x = min(max(window_x, area.x), area.x + area.width - width)
    y = min(max(window_y, area.y), area.y)
    return Geometry(x=x, y=y, width=width, height=area.height)


def menu_command(mode: str, window: dict[str, Any], monitor: dict[str, Any]) -> list[str]:
    command = [
        "wofi",
        "--dmenu",
        "--prompt",
        "Window size",
        "--width",
        str(MENU_WIDTH),
        "--lines",
        str(len(OPTIONS)),
        "--no-custom-entry",
        "--hide-scroll",
        "--dynamic-lines",
    ]
    if mode == "overlay":
        command.extend(wofi_anchor.wofi_search_args())
        try:
            window_x, window_y = (int(value) for value in window["at"])
            window_width, window_height = (int(value) for value in window["size"])
        except (KeyError, TypeError, ValueError) as exc:
            raise WindowSizeError("Hyprland returned incomplete window geometry") from exc
        area = work_area(monitor)
        x = window_x + (window_width - MENU_WIDTH) // 2
        y = window_y + (window_height - MENU_HEIGHT) // 2
        x, y, height = wofi_anchor.clamp_to_area(
            x, y, MENU_WIDTH, MENU_HEIGHT, area.x, area.y, area.width, area.height
        )
        try:
            monitor_name = str(monitor["name"])
            monitor_x, monitor_y = int(monitor["x"]), int(monitor["y"])
        except (KeyError, TypeError, ValueError) as exc:
            raise WindowSizeError("Hyprland returned incomplete monitor geometry") from exc
        command.extend(
            [
                "--monitor",
                monitor_name,
                "--location",
                "top_left",
                "--xoffset",
                str(x - monitor_x),
                "--yoffset",
                str(y - monitor_y),
                "--height",
                str(height),
                "--define",
                "close_on_focus_loss=true",
            ]
        )
    else:
        command.extend(wofi_anchor.wofi_menu_args(MENU_WIDTH, MENU_HEIGHT))
    return command


def choose_option(mode: str, window: dict[str, Any], monitor: dict[str, Any]) -> SizeOption | None:
    if not shutil.which("wofi"):
        raise WindowSizeError("wofi is not installed")
    choice = wofi_anchor.run_wofi_menu(
        menu_command(mode, window, monitor),
        input_text="\n".join(option.label for option in OPTIONS),
    )
    if not choice:
        return None
    try:
        return OPTIONS_BY_LABEL[choice]
    except KeyError as exc:
        raise WindowSizeError(f"Unknown window size selection: {choice}") from exc


def lua_selector(address: str) -> str:
    digits = address[2:] if address.startswith("0x") else ""
    if not digits or not all(char in "0123456789abcdefABCDEF" for char in digits):
        raise WindowSizeError("Hyprland returned an invalid window address")
    return f"address:{address}"


def dispatch(expression: str) -> None:
    result = run(["hyprctl", "dispatch", expression])
    if result.returncode != 0 or result.stdout.strip().lower() not in ("", "ok"):
        detail = (result.stderr or result.stdout).strip() or f"exit {result.returncode}"
        raise WindowSizeError(f"Hyprland window update failed: {detail}")


def window_by_address(address: str) -> dict[str, Any]:
    clients = run_json(["hyprctl", "-j", "clients"])
    if not isinstance(clients, list):
        raise WindowSizeError("Hyprland returned an invalid client list")
    window = next((item for item in clients if item.get("address") == address), None)
    if window is None:
        raise WindowSizeError("The selected window is no longer available")
    return window


def window_width(address: str) -> int:
    try:
        return int(window_by_address(address)["size"][0])
    except (KeyError, TypeError, ValueError) as exc:
        raise WindowSizeError("Hyprland returned incomplete window geometry") from exc


def resize_tiled(address: str, target_width: int) -> None:
    selector = lua_selector(address)
    current_width = window_width(address)
    if abs(target_width - current_width) <= 2:
        return

    probe = 20
    dispatch(
        f"hl.dsp.window.resize({{ x = {probe}, y = 0, relative = true, window = '{selector}' }})"
    )
    probed_width = window_width(address)
    width_change = probed_width - current_width
    if width_change == 0:
        probe = -probe
        dispatch(
            "hl.dsp.window.resize({ "
            f"x = {probe}, y = 0, relative = true, window = '{selector}'"
            " })"
        )
        probed_width = window_width(address)
        width_change = probed_width - current_width
    if width_change == 0:
        raise WindowSizeError("The current tiled split cannot be resized horizontally")

    direction = 1 if width_change * probe > 0 else -1
    for _ in range(3):
        error = target_width - probed_width
        if abs(error) <= 32:
            return
        dispatch(
            "hl.dsp.window.resize({ "
            f"x = {error * direction}, y = 0, relative = true, window = '{selector}'"
            " })"
        )
        next_width = window_width(address)
        if abs(target_width - next_width) >= abs(error) and next_width == probed_width:
            return
        probed_width = next_width


def apply_option(
    address: str, option: SizeOption, window: dict[str, Any], monitor: dict[str, Any]
) -> None:
    selector = lua_selector(address)
    action = "set" if option.floating else "unset"
    dispatch(f"hl.dsp.window.float({{ action = '{action}', window = '{selector}' }})")

    target_width = fraction_width(monitor, option.fraction)
    if not option.floating:
        resize_tiled(address, target_width)
        return

    geometry = calculate_floating_geometry(window, monitor, option.fraction)
    dispatch(
        (
            "hl.dsp.window.resize({ "
            f"x = {geometry.width}, y = {geometry.height}, window = '{selector}'"
            " })"
        )
    )
    dispatch(f"hl.dsp.window.move({{ x = {geometry.x}, y = {geometry.y}, window = '{selector}' }})")


def notify_error(message: str) -> None:
    print(f"window-size: {message}", file=sys.stderr)
    if shutil.which("notify-send"):
        subprocess.run(
            ["notify-send", "--urgency=critical", "Window size", message],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )


def resolve_option(
    argument: str | None, window: dict[str, Any], monitor: dict[str, Any]
) -> SizeOption | None:
    if argument is None or argument in ("menu", "overlay"):
        return choose_option(argument or "menu", window, monitor)
    floating = argument.startswith("float:")
    fraction_text = argument.removeprefix("float:")
    for label, fraction in FRACTION_CHOICES:
        if fraction_text == label:
            mode = "Float" if floating else "Tiled"
            return SizeOption(f"{mode} · {label}", fraction, floating)
    raise WindowSizeError(f"Unknown fraction: {argument}")


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) > 1:
        notify_error("Usage: window_size.py [menu|overlay|FRACTION|float:FRACTION]")
        return 2
    try:
        window, monitor = active_window_and_monitor()
        option = resolve_option(args[0] if args else None, window, monitor)
        if option is None:
            return 0
        apply_option(str(window["address"]), option, window, monitor)
    except WindowSizeError as exc:
        notify_error(str(exc))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
