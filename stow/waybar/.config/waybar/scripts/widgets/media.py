import shutil
from .common import classes, run

def _mmss(seconds: int) -> str:
    seconds = max(0, int(seconds))
    return f"{seconds // 60}:{seconds % 60:02d}"


_HIDDEN_MEDIA = {
    "text": "",
    "tooltip": "",
    "class": classes("media", "idle"),
    "alt": "idle",
}


def _pick_active_player() -> str | None:
    """Prefer a Playing player over a Paused one over the first available."""
    listed = run(["playerctl", "-l"])
    if listed.returncode != 0:
        return None
    names = [line.strip() for line in listed.stdout.splitlines() if line.strip()]
    if not names:
        return None

    playing: list[str] = []
    paused: list[str] = []
    for name in names:
        status_res = run(["playerctl", "--player", name, "status"])
        if status_res.returncode != 0:
            continue
        status = status_res.stdout.strip().lower()
        if status == "playing":
            playing.append(name)
        elif status == "paused":
            paused.append(name)
    if playing:
        return playing[0]
    if paused:
        return paused[0]
    return names[0]


def media_module(_state):
    if not shutil.which("playerctl"):
        return {
            "text": "",
            "tooltip": "playerctl is not installed",
            "class": classes("media", "muted"),
            "alt": "missing",
        }

    player = _pick_active_player()
    if not player:
        return _HIDDEN_MEDIA

    player_args = ["--player", player]

    sep = "\x1f"
    fmt = sep.join([
        "{{status}}",
        "{{playerName}}",
        "{{artist}}",
        "{{title}}",
        "{{album}}",
        "{{mpris:length}}",
    ])
    result = run(["playerctl", *player_args, "metadata", "--format", fmt])
    if result.returncode != 0 or not result.stdout.strip():
        return _HIDDEN_MEDIA

    parts = result.stdout.strip().split(sep)
    while len(parts) < 6:
        parts.append("")
    status, player_name, artist, title, album, length_raw = (p.strip() for p in parts)

    try:
        length = int(length_raw) // 1_000_000 if length_raw else 0
    except (ValueError, TypeError):
        length = 0

    position = 0
    pos_res = run(["playerctl", *player_args, "position"])
    if pos_res.returncode == 0 and pos_res.stdout.strip():
        try:
            position = int(float(pos_res.stdout.strip()))
        except ValueError:
            position = 0

    status_lower = status.lower()
    if status_lower == "playing":
        icon = ""
        state_class = "playing"
    elif status_lower == "paused":
        icon = ""
        state_class = "paused"
    else:
        return _HIDDEN_MEDIA

    if artist and title:
        display = f"{artist} — {title}"
    elif title:
        display = title
    elif player_name:
        display = player_name
    else:
        display = "Unknown"

    max_len = 48
    if len(display) > max_len:
        display = display[: max_len - 1].rstrip() + "…"

    if length > 0:
        position = max(0, min(position, length))
        percent = (position / length) * 100
        time_str = f"{_mmss(position)} / {_mmss(length)}"
    else:
        percent = 0.0
        time_str = _mmss(position) if position > 0 else ""

    text_parts = [icon, display]
    if time_str:
        text_parts.append(time_str)
    text = "  ".join(p for p in text_parts if p)

    bar_width = 22
    filled = int(round(percent / 100 * bar_width))
    bar = "━" * filled + "─" * (bar_width - filled)

    tooltip_lines = []
    if title:
        tooltip_lines.append(f"Title:  {title}")
    if artist:
        tooltip_lines.append(f"Artist: {artist}")
    if album:
        tooltip_lines.append(f"Album:  {album}")
    if player_name:
        tooltip_lines.append(f"Player: {player_name}")
    tooltip_lines.append(f"Status: {status or 'Unknown'}")
    if length > 0:
        remaining = max(0, length - position)
        tooltip_lines.append("")
        tooltip_lines.append(bar)
        tooltip_lines.append(
            f"{_mmss(position)} / {_mmss(length)}   -{_mmss(remaining)}   ({percent:.0f}%)"
        )
    tooltip_lines.append("")
    tooltip_lines.append("Left click: play/pause")
    tooltip_lines.append("Right click: next track")
    tooltip_lines.append("Middle click: previous track")
    tooltip_lines.append("Scroll: seek ±5s")
    tooltip = "\n".join(tooltip_lines)

    return {
        "text": text,
        "tooltip": tooltip,
        "class": classes("media", state_class),
        "alt": state_class,
    }
