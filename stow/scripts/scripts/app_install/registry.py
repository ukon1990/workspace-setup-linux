"""Discover managed installations and select an application."""

import json
import shutil
import subprocess
import sys

from .common import fail, identifier
from .desktop import desktop_read, desktop_unescape

LEGACY_IDS = {
    "apps": {"cursor", "gitkraken", "raiderio", "archon", "curseforge"},
    "jetbrains": {"intellij-idea", "rider"},
}


def installations(root, desktops):
    result = []
    for group in ("apps", "jetbrains"):
        parent = root / group
        if not parent.is_dir() or parent.is_symlink():
            continue
        for app in sorted(parent.iterdir()):
            if app.is_symlink() or not app.is_dir() or not (app / "current").is_dir():
                continue
            metadata = app / "app-install.json"
            if metadata.is_file():
                data = json.loads(metadata.read_text())
            elif app.name in LEGACY_IDS[group]:
                desk = desktop_read(desktops / f"{app.name}.desktop")
                data = {
                    "id": app.name,
                    "name": desktop_unescape(desk.get("Name", app.name)),
                    "type": "appimage"
                    if any(p.suffix.lower() == ".appimage" for p in (app / "current").iterdir())
                    else "tar",
                    "desktop": desk,
                }
            else:
                continue
            if data["id"] != identifier(data["id"]):
                fail(f"Invalid installed app identifier in {metadata}")
            data["parent"] = app
            result.append(data)
    return result


def select_app(apps, action="update"):
    if not apps:
        fail("No matching installed applications were found.")
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        fail(f"--{action} requires a terminal or --name identifying an installed app.")
    if shutil.which("whiptail"):
        command = [
            "whiptail",
            "--title",
            f"{action.capitalize()} application",
            "--menu",
            f"Select the application to {action}",
            "20",
            "80",
            "12",
            "--output-fd",
            "1",
        ]
        for index, app in enumerate(apps, 1):
            command.extend([str(index), f"{app['name']} ({app['id']})"])
        completed = subprocess.run(command, stdout=subprocess.PIPE, text=True)
        if completed.returncode:
            return None
        answer = completed.stdout.strip()
    else:
        for index, app in enumerate(apps, 1):
            print(f"{index}. {app['name']} ({app['id']})")
        answer = input("Application number (Enter to cancel): ").strip()
        if not answer:
            return None
    if not answer.isdigit() or not 1 <= int(answer) <= len(apps):
        fail("Invalid application selection.")
    return apps[int(answer) - 1]


def find_named(apps, name):
    matches = [
        app
        for app in apps
        if app["id"] == identifier(name) or app["name"].casefold() == name.casefold()
    ]
    if len(matches) > 1:
        fail("More than one installation matches; use the selector instead.")
    if not matches:
        fail(f"No installed application matches {name!r}.")
    return matches[0]
