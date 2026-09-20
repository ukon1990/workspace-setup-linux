#!/usr/bin/env python3
"""Shared helper for wofi dropdown menus opened from waybar/theme click handlers.

Waybar/theme click handlers (e.g. `custom/window-size`, `custom/theme`)
open a wofi dmenu as a "dropdown" from a button. Earlier versions of this
module anchored wofi's *layer-shell* popup to the mouse cursor via
`--xoffset`/`--yoffset`, and tried to make it close on an outside click
via wofi's `close_on_focus_loss` option. That never actually worked:
wofi's layer-shell surfaces always request *exclusive* keyboard
interactivity (not configurable), and Hyprland has a known limitation
(hyprwm/Hyprland#8293) where it will not transfer focus away from an
exclusive layer surface no matter where you click - so `close_on_focus_loss`
never had anything to react to.

The only working fix is to stop using wofi's layer-shell mode for these
menus: `wofi_menu_args()` below always requests `--normal-window`, which
makes wofi a regular window subject to Hyprland's normal focus handling,
so `close_on_focus_loss` genuinely fires when the user clicks elsewhere.

Trade-off: a normal (xdg-toplevel) window can't position itself in
Wayland - `--xoffset`/`--yoffset` have no effect - so cursor-relative
positioning now lives in a Hyprland `windowrule` (see
`stow/hypr/.config/hypr/_hyprland.conf`, matching `class:^(wofi)$`) using
Hyprland's own `move = cursor_x... cursor_y...` support, instead of in
this module.

Any script opening a click-triggered wofi menu should build its command
with `wofi_menu_args()` and launch it via `run_wofi_menu()`, so this
fix - and any future tuning of it - lives in exactly one place.
"""

from __future__ import annotations

import subprocess


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
    height = min(height, area_height)
    x = min(max(x, area_x), area_x + area_width - width)
    y = min(max(y, area_y), area_y + area_height - height)
    return x, y, height


def wofi_menu_args(width: int, height: int) -> list[str]:
    """Return wofi CLI args for a click-triggered dropdown menu.

    Runs wofi as a normal window (not a layer-shell popup) so
    `close_on_focus_loss` actually closes it when the user clicks
    elsewhere - see the module docstring for why. Positioning near the
    cursor is handled by a Hyprland windowrule, not by this function.
    """
    return [
        "--normal-window",
        "--width",
        str(width),
        "--height",
        str(height),
        "--define",
        "close_on_focus_loss=true",
    ]


def run_wofi_menu(command: list[str], *, input_text: str | None = None, timeout: float = 30) -> str:
    """Run a wofi dropdown, returning the chosen line (or "" if none was chosen)."""
    try:
        result = subprocess.run(
            command,
            input=input_text,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return ""
    return (result.stdout or "").strip()
