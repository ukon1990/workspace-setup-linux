#!/usr/bin/env python3
"""Pick the default PipeWire output or input from the volume island's panel."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path.home() / "scripts"))
import rofi_menu  # noqa: E402
import wofi_anchor  # noqa: E402

MENU_WIDTH = 480
MODES = (("Output", "Sinks"), ("Input", "Sources"))
# Optional readable names: {"text found in the system name": "Name to show"}.
ALIASES_FILE = Path.home() / ".config" / "waybar" / "audio-aliases.json"
SECTION_PATTERN = re.compile(r"[├└]─\s+(?P<name>[^:]+):\s*$")
DEVICE_PATTERN = re.compile(
    r"^[│\s]*(?P<default>\*)?\s*(?P<id>\d+)\.\s+"
    r"(?P<description>.*?)(?:\s+\[vol:\s*(?P<volume>[0-9.]+)(?P<muted>\s+MUTED)?\])?\s*$"
)
# "Arctis Nova Pro Wireless Analog Stereo" -> name + "analog stereo" detail.
PROFILE_PATTERN = re.compile(r"\s+((?:Analog|Digital)\s.*|Mono|Stereo)$")


class AudioMenuError(RuntimeError):
    """A user-facing audio menu failure."""


@dataclass(frozen=True)
class AudioDevice:
    id: int
    description: str
    default: bool
    volume: float | None = None
    muted: bool = False

    def name_and_detail(self, aliases: dict[str, str]) -> tuple[str, str]:
        match = PROFILE_PATTERN.search(self.description)
        name = self.description[: match.start()] if match else self.description
        detail = match.group(1).lower() if match else ""
        for needle, alias in aliases.items():
            if needle in self.description:
                return alias, f"{name} · {detail}".strip(" ·")
        return name, detail

    def row(self, aliases: dict[str, str]) -> rofi_menu.Row:
        name, detail = self.name_and_detail(aliases)
        facts = [detail] if detail else []
        if self.volume is not None:
            filled = round(min(self.volume, 1.0) * 8)
            meter = f"<tt>{'█' * filled}<span alpha='22%'>{'█' * (8 - filled)}</span></tt>"
            facts.insert(0, f"{meter} {'muted' if self.muted else f'{self.volume:.0%}'}")
        if self.default:
            facts.append("default")
        marker = "●" if self.default else "○"
        text = f"{marker}  <b>{rofi_menu.esc(name)}</b>"
        return rofi_menu.Row(
            f"{text}\n<span size='small' alpha='70%'>{' · '.join(facts)}</span>"
        )


def load_aliases() -> dict[str, str]:
    try:
        aliases = json.loads(ALIASES_FILE.read_text())
    except (OSError, json.JSONDecodeError):
        return {}
    return aliases if isinstance(aliases, dict) else {}


def run(command: list[str]) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "LC_ALL": "C"}
    try:
        return subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
            env=env,
        )
    except FileNotFoundError as exc:
        raise AudioMenuError(f"{command[0]} is not installed") from exc
    except subprocess.TimeoutExpired as exc:
        raise AudioMenuError(f"{command[0]} timed out") from exc


def parse_devices(status: str, section_name: str) -> list[AudioDevice]:
    devices: list[AudioDevice] = []
    current_group = ""
    current_section = ""
    found_section = False

    for line in status.splitlines():
        if line and not line[0].isspace():
            current_group = line.rstrip(":")
            current_section = ""
            continue
        section_match = SECTION_PATTERN.search(line)
        if section_match:
            current_section = section_match.group("name")
            found_section |= current_group == "Audio" and current_section == section_name
            continue
        if current_group != "Audio" or current_section != section_name:
            continue
        device_match = DEVICE_PATTERN.match(line)
        if not device_match:
            continue
        devices.append(
            AudioDevice(
                id=int(device_match.group("id")),
                description=device_match.group("description").rstrip(),
                default=device_match.group("default") == "*",
                volume=float(volume) if (volume := device_match.group("volume")) else None,
                muted=bool(device_match.group("muted")),
            )
        )

    if not found_section:
        raise AudioMenuError(f"wpctl status did not contain an {section_name} section")
    return devices


def audio_devices(section_name: str) -> list[AudioDevice]:
    result = run(["wpctl", "status"])
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip() or f"exit {result.returncode}"
        raise AudioMenuError(f"wpctl status failed: {detail}")
    devices = parse_devices(result.stdout, section_name)
    if not devices:
        kind = "output" if section_name == "Sinks" else "input"
        raise AudioMenuError(f"No {kind} devices are available")
    return devices


def choose(
    mode: int, devices: list[AudioDevice], anchor: wofi_anchor.DropdownAnchor | None
) -> rofi_menu.Choice:
    """Show one mode's devices; Choice.key is 0 Enter, 1 flip mode, 2 mute, 3 mixer."""
    if not shutil.which("rofi"):
        raise AudioMenuError("rofi is not installed")
    aliases = load_aliases()
    current = next((device for device in devices if device.default), None)
    level = "muted" if current and current.muted else f"{current.volume:.0%}" if current and current.volume is not None else ""
    names = tuple(name for name, _ in MODES)
    return rofi_menu.pick(
        [device.row(aliases) for device in devices],
        header=f"{rofi_menu.label('VOLUME')}  <b>{level}</b>      {rofi_menu.chips(names, mode)}",
        hint=rofi_menu.hints(
            ("Enter", "make default"),
            ("Alt M", "mute"),
            ("Ctrl Tab", names[1 - mode].lower()),
            ("Alt Enter", "mixer"),
        ),
        selected=next((i for i, device in enumerate(devices) if device.default), 0),
        width=MENU_WIDTH,
        row_lines=2,
        custom_keys=("Control+Tab", "Alt+m", "Alt+Return"),
        anchor=anchor,
    )


def set_default(device: AudioDevice) -> None:
    result = run(["wpctl", "set-default", str(device.id)])
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip() or f"exit {result.returncode}"
        raise AudioMenuError(f"Could not select {device.description}: {detail}")


def toggle_mute(device: AudioDevice) -> None:
    result = run(["wpctl", "set-mute", str(device.id), "toggle"])
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip() or f"exit {result.returncode}"
        raise AudioMenuError(f"Could not mute {device.description}: {detail}")


def open_audio_controls() -> None:
    try:
        subprocess.Popen(
            ["pavucontrol"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except FileNotFoundError as exc:
        raise AudioMenuError("pavucontrol is not installed") from exc


def notify_error(message: str) -> None:
    print(f"audio-menu: {message}", file=sys.stderr)
    if shutil.which("notify-send"):
        subprocess.run(
            ["notify-send", "--urgency=critical", "Audio menu", message],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )


def main() -> int:
    try:
        anchor = wofi_anchor.cursor_anchor()
        mode = 0
        while True:
            devices = audio_devices(MODES[mode][1])
            choice = choose(mode, devices, anchor)
            if choice.key == 1:
                mode = 1 - mode
            elif choice.key == 3:
                open_audio_controls()
                return 0
            elif choice.key == rofi_menu.CANCEL or choice.index is None:
                return 0
            elif choice.key == 2:
                toggle_mute(devices[choice.index])
            else:
                if not devices[choice.index].default:
                    set_default(devices[choice.index])
                return 0
    except AudioMenuError as exc:
        notify_error(str(exc))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
