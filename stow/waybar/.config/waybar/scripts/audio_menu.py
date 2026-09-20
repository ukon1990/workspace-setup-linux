#!/usr/bin/env python3
"""Select default PipeWire audio devices from a Waybar dropdown."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path.home() / "scripts"))
import wofi_anchor  # noqa: E402

MENU_WIDTH = 420
MENU_HEIGHT = 320
TOP_LEVEL_OPTIONS = ("Output devices", "Input devices", "Open audio controls")
SECTION_BY_OPTION = {
    "Output devices": "Sinks",
    "Input devices": "Sources",
}
SECTION_PATTERN = re.compile(r"[├└]─\s+(?P<name>[^:]+):\s*$")
DEVICE_PATTERN = re.compile(
    r"^[│\s]*(?P<default>\*)?\s*(?P<id>\d+)\.\s+"
    r"(?P<description>.*?)(?:\s+\[vol:[^\]]+\])?\s*$"
)


class AudioMenuError(RuntimeError):
    """A user-facing audio menu failure."""


@dataclass(frozen=True)
class AudioDevice:
    id: int
    description: str
    default: bool

    @property
    def menu_label(self) -> str:
        marker = "●" if self.default else "○"
        return f"{marker} {self.description}  ·  {self.id}"


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


def menu_command(prompt: str, option_count: int) -> list[str]:
    command = [
        "wofi",
        "--dmenu",
        "--prompt",
        prompt,
        "--lines",
        str(option_count),
        "--no-custom-entry",
        "--hide-scroll",
        "--define",
        "dynamic_lines=true",
    ]
    command.extend(wofi_anchor.wofi_menu_args(MENU_WIDTH, MENU_HEIGHT))
    return command


def choose(
    prompt: str,
    options: list[str] | tuple[str, ...],
    anchor: wofi_anchor.DropdownAnchor | None = None,
) -> str:
    if not shutil.which("wofi"):
        raise AudioMenuError("wofi is not installed")
    return wofi_anchor.run_wofi_menu(
        menu_command(prompt, len(options)),
        input_text="\n".join(options),
        anchor=anchor,
    )


def choose_device(
    section_name: str, anchor: wofi_anchor.DropdownAnchor | None = None
) -> AudioDevice | None:
    devices = audio_devices(section_name)
    devices_by_label = {device.menu_label: device for device in devices}
    kind = "output" if section_name == "Sinks" else "input"
    choice = choose(f"Audio {kind}", list(devices_by_label), anchor)
    if not choice:
        return None
    try:
        return devices_by_label[choice]
    except KeyError as exc:
        raise AudioMenuError(f"Unknown audio device selection: {choice}") from exc


def set_default(device: AudioDevice) -> None:
    result = run(["wpctl", "set-default", str(device.id)])
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip() or f"exit {result.returncode}"
        raise AudioMenuError(f"Could not select {device.description}: {detail}")


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
        choice = choose("Audio", TOP_LEVEL_OPTIONS, anchor)
        if not choice:
            return 0
        if choice == "Open audio controls":
            open_audio_controls()
            return 0
        try:
            section_name = SECTION_BY_OPTION[choice]
        except KeyError as exc:
            raise AudioMenuError(f"Unknown audio menu selection: {choice}") from exc
        device = choose_device(section_name, anchor)
        if device is not None and not device.default:
            set_default(device)
    except AudioMenuError as exc:
        notify_error(str(exc))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
