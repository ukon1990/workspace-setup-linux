"""Pango-markup building blocks shared by the bar tooltips.

Layout rule for every widget: label and headline first, meters only for
percentages, aligned facts, and click hints as one muted last line.
"""

import html
import re
from pathlib import Path

COLORS_FILE = Path.home() / ".config" / "waybar" / "colors.css"
MUTED = 'alpha="65%"'
METER_WIDTH = 16


def esc(value):
    return html.escape(str(value), quote=False)


def theme_color(name, default):
    """Read a color the theme manager generated for Waybar (hex values only)."""
    try:
        match = re.search(rf"@define-color {name} (#[0-9a-fA-F]{{6}});", COLORS_FILE.read_text())
    except OSError:
        match = None
    return match.group(1) if match else default


def header(label, title):
    return f'<span size="small" {MUTED}><b>{esc(label)}</b></span>  <b>{esc(title)}</b>'


def meter(percent, width=METER_WIDTH):
    filled = round(max(0.0, min(100.0, percent)) / 100 * width)
    color = theme_color("primary", "#5ea0e0")
    return (
        f'<span color="{color}">{"█" * filled}</span>'
        f'<span alpha="22%">{"█" * (width - filled)}</span>'
    )


def table(rows):
    """Aligned ``label  value`` lines; values may already contain markup."""
    width = max((len(label) for label, _ in rows), default=0)
    return [f"<tt><span {MUTED}>{esc(label):<{width}}</span>  {value}</tt>" for label, value in rows]


def ranking(title, unit, rows):
    """Aligned ``name  value`` lines under a muted section title."""
    width = max([len(name) for name, _ in rows] + [len(title)]) + 2
    lines = ["", f"<tt><span size='small' {MUTED}>{esc(title):<{width}}{esc(unit)}</span></tt>"]
    lines += [f"<tt>{esc(name):<{width}}{esc(value)}</tt>" for name, value in rows]
    return lines


def hint(text):
    return f'<span size="small" {MUTED}>{esc(text)}</span>'


def attention(text):
    return f'<span color="{theme_color("warn", "#e0a458")}">{esc(text)}</span>'


def render(lines):
    return {"tooltip": "\n".join(lines), "markup": True}
