"""List managed applications and edit their desktop metadata."""

import json
import os
import re
import shutil
import uuid

from .common import fail, replace_file
from .desktop import desktop_escape, desktop_read, desktop_unescape, refresh_desktops
from .registry import find_named, installations, select_app


def list_apps(args, root, desktops):
    apps = installations(root, desktops)
    if args.name:
        apps = [find_named(apps, args.name)]
    if not apps:
        print("No managed applications installed.")
        return
    rows = [("NAME", "ID", "TYPE", "CATEGORIES")]
    for app in sorted(apps, key=lambda app: app["name"].casefold()):
        desktop = desktop_read(desktops / f"{app['id']}.desktop") or app.get("desktop", {})
        rows.append((app["name"], app["id"], app["type"], desktop.get("Categories", "—")))
    rows = [tuple(value.replace("\n", " ").replace("\t", " ") for value in row) for row in rows]
    widths = [max(len(row[i]) for row in rows) for i in range(4)]
    for row in rows:
        print(
            "  ".join(value.ljust(width) for value, width in zip(row, widths, strict=True)).rstrip()
        )


def desktop_changes(args):
    changes = {}
    for option, key in (("comment", "Comment"), ("startup_class", "StartupWMClass")):
        value = getattr(args, option)
        if value is not None:
            changes[key] = desktop_escape(value)
    for option, key in (("categories", "Categories"), ("keywords", "Keywords")):
        value = getattr(args, option)
        if value is not None:
            entries = list(dict.fromkeys(part.strip() for part in value.split(";") if part.strip()))
            if option == "categories" and any(
                not re.fullmatch(r"[A-Za-z0-9-]+", part) for part in entries
            ):
                fail('Categories must be semicolon-separated identifiers, e.g. "Development;IDE;".')
            changes[key] = ";".join(desktop_escape(part) for part in entries) + (
                ";" if entries else ""
            )
    if args.terminal is not None:
        changes["Terminal"] = str(args.terminal).lower()
    return changes


def update_desktop_text(text, changes):
    """Replace main-entry fields while retaining actions, comments, and other groups."""
    output, pending = [], dict(changes)
    active = False
    found = False
    for line in text.splitlines():
        if line.startswith("["):
            if active:
                output.extend(f"{key}={value}" for key, value in pending.items())
                pending.clear()
            active = line == "[Desktop Entry]"
            found = found or active
        if active and "=" in line and line.split("=", 1)[0] in changes:
            key = line.split("=", 1)[0]
            if key in pending:
                output.append(f"{key}={pending.pop(key)}")
        else:
            output.append(line)
    if not found:
        output.append("[Desktop Entry]")
    output.extend(f"{key}={value}" for key, value in pending.items())
    return "\n".join(output) + "\n"


def edit_app(args, root, desktops):
    changes = desktop_changes(args)
    if args.icon and (
        not args.icon.is_file() or args.icon.suffix.lower() not in (".svg", ".png", ".xpm")
    ):
        fail("--icon must be an existing SVG, PNG, or XPM file.")
    apps = installations(root, desktops)
    app = find_named(apps, args.name) if args.name else select_app(apps, "edit")
    if app is None:
        print("Cancelled.")
        return
    path = desktops / f"{app['id']}.desktop"
    if not path.is_file():
        fail(f"Desktop entry missing: {path}. Reinstall the app to recreate it.")
    if args.dry_run or os.environ.get("DRY_RUN") == "1":
        print(f"Would edit {app['name']}:")
        for key, value in changes.items():
            print(f"  {key}={value}")
        if args.icon:
            print(f"  Icon={args.icon.resolve()}")
        return
    if args.icon:
        icon = app["parent"] / ("icon-" + uuid.uuid4().hex + args.icon.suffix.lower())
        shutil.copy2(args.icon, icon)
        changes["Icon"] = desktop_escape(str(icon))
    text = update_desktop_text(path.read_text(), changes)
    desktop = desktop_read(path)
    desktop.update(changes)
    app["desktop"] = desktop
    metadata = {key: value for key, value in app.items() if key != "parent"}
    replace_file(path, text)
    replace_file(app["parent"] / "app-install.json", json.dumps(metadata, indent=2) + "\n")
    refresh_desktops(desktops)
    print(f"Updated desktop metadata for {desktop_unescape(desktop.get('Name', app['name']))}")
