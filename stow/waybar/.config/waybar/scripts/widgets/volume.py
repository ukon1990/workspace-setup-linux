import re
from .common import classes, clamp, run, use_compact_perf_text

def volume_bar(percent):
    filled = int(round(clamp(percent) / 100 * 8))
    return "▁▂▃▄▅▆▇█"[max(0, filled - 1)] if filled else "·"
def inspect_value(output, names):
    for name in names:
        match = re.search(rf"{re.escape(name)}\s*=\s*\"([^\"]+)\"", output)
        if match:
            return match.group(1)
    return None


def volume_module(state):
    volume_result = run(["wpctl", "get-volume", "@DEFAULT_AUDIO_SINK@"])
    compact = use_compact_perf_text(state)
    if volume_result.returncode != 0:
        return {
            "text": "󰖁 audio off",
            "tooltip": "Audio server unavailable",
            "class": classes("metric", "muted", "compact" if compact else None),
        }

    line = volume_result.stdout.strip()
    match = re.search(r"Volume:\s*([0-9.]+)", line)
    if not match:
        return {
            "text": "󰕾 --",
            "tooltip": "Could not read volume",
            "class": classes("metric", "compact" if compact else None),
        }

    volume = float(match.group(1)) * 100
    muted = "[MUTED]" in line

    inspect = run(["wpctl", "inspect", "@DEFAULT_AUDIO_SINK@"])
    description = "Default sink"
    if inspect.returncode == 0:
        description = (
            inspect_value(inspect.stdout, ["node.description", "node.nick", "device.description"])
            or description
        )

    if muted:
        icon = "󰝟"
        state_class = "metric muted"
    elif volume < 35:
        icon = "󰕿"
        state_class = "metric"
    elif volume < 70:
        icon = "󰖀"
        state_class = "metric"
    else:
        icon = "󰕾"
        state_class = "metric active"

    bar = volume_bar(volume)
    return {
        "text": f"{icon}  {volume:.0f}%" if compact else f"{icon} {volume:3.0f}% {bar}",
        "tooltip": f"{description}\nVolume: {volume:.0f}%\nLeft click: open mixer\nRight click: mute\nScroll: adjust volume",
        "class": classes(*state_class.split(), "compact" if compact else None),
    }
