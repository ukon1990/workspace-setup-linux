#!/usr/bin/env python3
"""Shared rofi panels for the bar menus (audio, night light, theme, window size).

One shell for every menu: a header line, a list or a grid of cards, and a muted
hint line. Layouts live in ~/.config/rofi (menu.rasi, grid.rasi, prompt.rasi);
colors come from the theme manager's colors.rasi.
"""

from __future__ import annotations

import html
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

import wofi_anchor

ROFI_DIR = Path.home() / ".config" / "rofi"
CACHE_DIR = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "rofi-menu"
CANCEL = -1  # Choice.key values: CANCEL, 0 for Enter, n for the n-th custom key
BAR_GAP = 6
FALLBACK_COLORS = {
    "text": "#dde6f2",
    "muted": "#9aa6b7",
    "primary": "#5ea0e0",
    "primary-container": "#1e4c74",
    "on-primary": "#e7f2ff",
    "surface-high": "#1c2430",
}


@dataclass(frozen=True)
class Row:
    text: str  # Pango markup; "\n" starts a second line
    icon: str = ""  # icon name or image path


@dataclass(frozen=True)
class Choice:
    index: int | None
    key: int


def esc(value: object) -> str:
    return html.escape(str(value), quote=False)


def colors() -> dict[str, str]:
    """Theme colors as #rrggbb (alpha dropped), read from the generated colors.rasi."""
    found = dict(FALLBACK_COLORS)
    try:
        text = (ROFI_DIR / "colors.rasi").read_text()
    except OSError:
        return found
    for name, value in re.findall(r"^\s*([\w-]+):\s*(#[0-9a-fA-F]{6})[0-9a-fA-F]{0,2};", text, re.M):
        found[name] = value
    return found


def label(text: str) -> str:
    """Small muted caption that starts a header line, e.g. ``label("VOLUME")``."""
    return f"<span size='small' alpha='65%'><b>{esc(text)}</b></span>"


def chips(names: tuple[str, ...], active: int) -> str:
    """Mode chips for a header line; the active one is filled."""
    palette = colors()
    parts = []
    for index, name in enumerate(names):
        if index == active:
            parts.append(
                f"<span background='{palette['primary-container']}' "
                f"foreground='{palette['on-primary']}'> {esc(name)} </span>"
            )
        else:
            parts.append(f"<span alpha='65%'> {esc(name)} </span>")
    return " ".join(parts)


def hints(*pairs: tuple[str, str]) -> str:
    return "     ".join(f"<b>{esc(key)}</b> {esc(action)}" for key, action in pairs)


def svg_icon(name: str, body: str, size: int = 128) -> str:
    """Write a generated SVG icon to the cache and return its path."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = CACHE_DIR / f"{name}.svg"
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" '
        f'viewBox="0 0 {size} {size}">{body}</svg>'
    )
    try:
        current = path.read_text()
    except OSError:
        current = None
    if current != svg:
        path.write_text(svg)
    return str(path)


def _position(anchor: wofi_anchor.DropdownAnchor | None, width: int) -> str:
    """Theme override that opens the panel under the bar at the click.

    Without an anchor the layout's own centred position stays.
    """
    if anchor is None:
        return ""
    x = min(max(anchor.x - width // 2, anchor.area_x), anchor.area_x + anchor.area_width - width)
    return (
        "window { location: north west; anchor: north west; "
        f"x-offset: {x - anchor.area_x}px; y-offset: {BAR_GAP}px; }}"
    )


def _theme_string(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _run(command: list[str], input_text: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, input=input_text, capture_output=True, text=True, check=False)


def pick(
    rows: list[Row],
    *,
    header: str = "",
    hint: str = "",
    selected: int = 0,
    width: int = 480,
    columns: int = 1,
    icon_size: int = 0,
    row_lines: int = 1,
    custom_keys: tuple[str, ...] = (),
    anchor: wofi_anchor.DropdownAnchor | None = None,
) -> Choice:
    """Show a list (``columns=1``) or a grid of cards and return the choice."""
    overrides = [
        f"window {{ width: {width}px; }}",
        f"listview {{ columns: {columns}; lines: {-(-len(rows) // columns)}; }}",
        f'textbox-hints {{ content: "{_theme_string(hint)}"; }}',
    ]
    if icon_size:
        overrides.append(f"element-icon {{ size: {icon_size}px; }}")
    overrides.append(_position(anchor, width))
    command = [
        "rofi", "-dmenu", "-i", "-markup-rows", "-no-custom", "-format", "i",
        "-theme", str(ROFI_DIR / ("grid.rasi" if columns > 1 else "menu.rasi")),
        "-theme-str", " ".join(overrides),
        "-selected-row", str(selected),
        "-eh", str(row_lines),
        *(["-show-icons"] if icon_size else []),
        *(["-mesg", header] if header else []),
        # dmenu has no modes; free Ctrl+Tab so menus can use it to flip theirs.
        "-kb-mode-next", "", "-kb-mode-previous", "",
    ]  # fmt: skip
    for number, key in enumerate(custom_keys, start=1):
        command += [f"-kb-custom-{number}", key]
    lines = [
        row.text.replace("\n", "&#10;") + (f"\0icon\x1f{row.icon}" if row.icon else "")
        for row in rows
    ]
    result = _run(command, "\n".join(lines))
    output = result.stdout.strip()
    index = int(output) if output.lstrip("-").isdigit() and int(output) >= 0 else None
    if result.returncode == 0:
        return Choice(index, 0)
    if 10 <= result.returncode < 10 + len(custom_keys):
        return Choice(index, result.returncode - 9)
    return Choice(None, CANCEL)


def ask(prompt: str, value: str, *, header: str = "", hint: str = "", width: int = 480) -> str | None:
    """Ask for one typed value, pre-filled with ``value``. None when cancelled."""
    command = [
        "rofi", "-dmenu", "-format", "s", "-p", prompt, "-filter", value,
        "-theme", str(ROFI_DIR / "prompt.rasi"),
        "-theme-str", f'window {{ width: {width}px; }} textbox-hints {{ content: "{_theme_string(hint)}"; }}',
        *(["-mesg", header] if header else []),
    ]  # fmt: skip
    result = _run(command, "")
    return result.stdout.strip() if result.returncode == 0 else None
