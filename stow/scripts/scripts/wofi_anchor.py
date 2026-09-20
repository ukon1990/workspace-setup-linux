#!/usr/bin/env python3
"""Shared behavior for click-triggered wofi dropdowns."""

from __future__ import annotations

import json
import subprocess
import time
from dataclasses import dataclass
from typing import Any

MAP_ATTEMPTS = 20
MAP_RETRY_SECONDS = 0.025


@dataclass(frozen=True)
class DropdownAnchor:
    x: int
    y: int
    area_x: int
    area_y: int
    area_width: int
    area_height: int


def clamp_to_area(
    x: int,
    y: int,
    width: int,
    height: int,
    area_x: int,
    area_y: int,
    area_width: int,
    area_height: int,
) -> tuple[int, int, int]:
    """Clamp a menu's top-left position (and height) to fit within an area."""
    width = min(width, area_width)
    height = min(height, area_height)
    x = min(max(x, area_x), area_x + area_width - width)
    y = min(max(y, area_y), area_y + area_height - height)
    return x, y, height


def _run_json(command: list[str]) -> Any:
    result = subprocess.run(command, capture_output=True, text=True, check=False, timeout=2)
    if result.returncode != 0:
        return None
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return None


def cursor_anchor() -> DropdownAnchor | None:
    """Capture the cursor and usable area of the monitor containing it."""
    try:
        cursor = _run_json(["hyprctl", "-j", "cursorpos"])
        monitors = _run_json(["hyprctl", "-j", "monitors"])
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    if not isinstance(cursor, dict) or not isinstance(monitors, list):
        return None
    try:
        x, y = int(cursor["x"]), int(cursor["y"])
        monitor = None
        for item in monitors:
            scale = float(item.get("scale", 1))
            if scale <= 0:
                continue
            monitor_x, monitor_y = int(item["x"]), int(item["y"])
            monitor_width = round(int(item["width"]) / scale)
            monitor_height = round(int(item["height"]) / scale)
            if (
                monitor_x <= x < monitor_x + monitor_width
                and monitor_y <= y < monitor_y + monitor_height
            ):
                monitor = item
                break
        if monitor is None:
            return None
        scale = float(monitor.get("scale", 1))
        if scale <= 0:
            return None
        left, top, right, bottom = (int(value) for value in monitor["reserved"])
        monitor_width = round(int(monitor["width"]) / scale)
        monitor_height = round(int(monitor["height"]) / scale)
        area_x = int(monitor["x"]) + left
        area_y = int(monitor["y"]) + top
        area_width = monitor_width - left - right
        area_height = monitor_height - top - bottom
    except (KeyError, TypeError, ValueError):
        return None
    if area_width <= 0 or area_height <= 0:
        return None
    return DropdownAnchor(x, y, area_x, area_y, area_width, area_height)


def dropdown_position(
    anchor: DropdownAnchor, width: int, height: int
) -> tuple[int, int]:
    """Center a dropdown below its click and keep it in the monitor work area."""
    x, y, _ = clamp_to_area(
        anchor.x - width // 2,
        anchor.area_y,
        width,
        height,
        anchor.area_x,
        anchor.area_y,
        anchor.area_width,
        anchor.area_height,
    )
    return x, y


def wofi_search_args() -> list[str]:
    """Return search behavior shared by all repository wofi menus."""
    return ["--insensitive"]


def wofi_menu_args(width: int, height: int) -> list[str]:
    """Return CLI arguments for a click-triggered normal-window dropdown."""
    return [
        *wofi_search_args(),
        "--normal-window",
        "--width",
        str(width),
        "--height",
        str(height),
        "--define",
        "close_on_focus_loss=true",
    ]


def _mapped_client(pid: int) -> dict[str, Any] | None:
    for attempt in range(MAP_ATTEMPTS):
        try:
            clients = _run_json(["hyprctl", "-j", "clients"])
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return None
        if isinstance(clients, list):
            client = next((item for item in clients if item.get("pid") == pid), None)
            if client is not None:
                return client
        if attempt + 1 < MAP_ATTEMPTS:
            time.sleep(MAP_RETRY_SECONDS)
    return None


def _position_window(pid: int, anchor: DropdownAnchor) -> None:
    client = _mapped_client(pid)
    if client is None:
        return
    try:
        width, height = (int(value) for value in client["size"])
    except (KeyError, TypeError, ValueError):
        return
    x, y = dropdown_position(anchor, width, height)
    expression = (
        f"hl.dsp.window.move({{ x = {x}, y = {y}, window = 'pid:{pid}' }})"
    )
    try:
        subprocess.run(
            ["hyprctl", "dispatch", expression],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=2,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass


def run_wofi_menu(
    command: list[str],
    *,
    input_text: str | None = None,
    timeout: float = 30,
    anchor: DropdownAnchor | None = None,
) -> str:
    """Run and position a wofi dropdown, returning the chosen line."""
    normal_window = "--normal-window" in command
    if normal_window and anchor is None:
        anchor = cursor_anchor()
    try:
        process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    except FileNotFoundError:
        return ""

    if process.stdin is not None:
        try:
            process.stdin.write(input_text or "")
            process.stdin.close()
        except BrokenPipeError:
            pass
        process.stdin = None

    if normal_window and anchor is not None:
        _position_window(process.pid, anchor)

    try:
        stdout, _ = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        process.kill()
        process.communicate()
        return ""
    return (stdout or "").strip()
