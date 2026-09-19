"""List managed applications and edit their desktop metadata."""

import json
import os
import re
import shutil
import uuid

from .bundles import executable
from .common import fail, replace_file, resolve_password_store, wrapper_script
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


def launcher_name(app):
    payload = app["parent"] / "current"
    if app.get("executable"):
        return app["executable"]
    if app["type"] == "appimage":
        candidates = [p.name for p in payload.iterdir() if p.suffix.lower() == ".appimage"]
        if len(candidates) != 1:
            fail("Cannot determine the installed AppImage launcher.")
        return candidates[0]
    hints = {
        "intellij-idea": ["bin/idea", "bin/idea.sh"],
        "rider": ["bin/rider", "bin/rider.sh"],
        "gitkraken": ["gitkraken", "resources/bin/gitkraken.sh"],
    }
    return executable(payload, hints.get(app["id"]), None, app["id"])


def edit_app(args, root, bins, desktops):
    changes = desktop_changes(args)
    password_store_arg = getattr(args, "password_store", None)
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
    if password_store_arg is not None:
        password_store = resolve_password_store(password_store_arg, None)
    else:
        password_store = resolve_password_store(None, app)
    if args.dry_run or os.environ.get("DRY_RUN") == "1":
        print(f"Would edit {app['name']}:")
        for key, value in changes.items():
            print(f"  {key}={value}")
        if args.icon:
            print(f"  Icon={args.icon.resolve()}")
        if password_store_arg is not None:
            print(f"  password_store={password_store or ''}")
        return
    if args.icon:
        icon = app["parent"] / ("icon-" + uuid.uuid4().hex + args.icon.suffix.lower())
        shutil.copy2(args.icon, icon)
        changes["Icon"] = desktop_escape(str(icon))
    if changes:
        text = update_desktop_text(path.read_text(), changes)
        desktop = desktop_read(path)
        desktop.update(changes)
        replace_file(path, text)
    else:
        desktop = desktop_read(path) or app.get("desktop", {})
    app["desktop"] = desktop
    if password_store_arg is not None:
        launch = launcher_name(app)
        app["executable"] = launch
        bins.mkdir(parents=True, exist_ok=True)
        replace_file(
            bins / app["id"],
            wrapper_script(app["parent"] / "current" / launch, app["type"], password_store),
            0o755,
        )
        if password_store:
            app["password_store"] = password_store
        else:
            app.pop("password_store", None)
    metadata = {key: value for key, value in app.items() if key != "parent"}
    replace_file(app["parent"] / "app-install.json", json.dumps(metadata, indent=2) + "\n")
    if changes or args.icon:
        refresh_desktops(desktops)
    label = desktop_unescape(desktop.get("Name", app["name"]))
    print(f"Updated desktop metadata for {label}")
