"""Rename and uninstall managed applications."""

import json
import os
import shlex
import shutil

from .bundles import executable
from .common import fail, identifier, replace_file
from .desktop import desktop_escape, desktop_read, exec_quote, refresh_desktops
from .registry import find_named, installations, select_app


def manage_app(args, root, bins, desktops):
    apps = installations(root, desktops)
    action = "uninstall" if args.uninstall else "rename"
    app = find_named(apps, args.name) if args.name else select_app(apps, action)
    if app is None:
        print("Cancelled.")
        return
    parent, old_id = app["parent"], app["id"]
    old_bin, old_desktop = bins / old_id, desktops / f"{old_id}.desktop"
    for path in (old_bin, old_desktop):
        if path.is_dir() and not path.is_symlink():
            fail(f"Expected a file, found a directory: {path}")
    dry_run = args.dry_run or os.environ.get("DRY_RUN") == "1"
    if args.uninstall:
        if dry_run:
            print(f"Would uninstall {app['name']}: {parent}, {old_bin}, {old_desktop}")
            return
        # Unlink launchers themselves, including Stow links; never their targets.
        old_bin.unlink(missing_ok=True)
        old_desktop.unlink(missing_ok=True)
        shutil.rmtree(parent)
        refresh_desktops(desktops)
        print(f"Uninstalled {app['name']}")
        return
    new_name, new_id = args.rename, identifier(args.rename)
    new_bin, new_desktop = bins / new_id, desktops / f"{new_id}.desktop"
    if new_id != old_id:
        if any(other["id"] == new_id for other in apps):
            fail(f"An application already uses the name {new_name!r}.")
        if any(os.path.lexists(path) for path in (new_bin, new_desktop)):
            fail(f"A launcher or desktop entry already uses {new_id!r}.")
    if dry_run:
        print(f"Would rename {app['name']} ({old_id}) to {new_name} ({new_id})")
        return
    # Keep the payload directory stable: legacy current symlinks and custom
    # launchers may contain absolute paths into it.
    if old_bin.is_file() and os.access(old_bin, os.X_OK):
        wrapper = old_bin.read_text()
    else:
        payload = parent / "current"
        if app["type"] == "appimage":
            candidates = [p.name for p in payload.iterdir() if p.suffix.lower() == ".appimage"]
            if len(candidates) != 1:
                fail("Cannot determine the installed AppImage launcher.")
            launch = candidates[0]
        else:
            hints = {
                "intellij-idea": ["bin/idea", "bin/idea.sh"],
                "rider": ["bin/rider", "bin/rider.sh"],
                "gitkraken": ["gitkraken", "resources/bin/gitkraken.sh"],
            }
            launch = executable(payload, hints.get(old_id), app.get("executable"), old_id)
        command = shlex.quote(str(payload / launch))
        if app["type"] == "appimage":
            command += " --appimage-extract-and-run"
        wrapper = "#!/usr/bin/env bash\nset -euo pipefail\nexec " + command + ' "$@"\n'
        app["executable"] = launch
    desktop = desktop_read(old_desktop) or app.get("desktop", {})
    desktop.update(
        {
            "Type": "Application",
            "Name": desktop_escape(new_name),
            "Exec": desktop_escape(exec_quote(str(new_bin)) + " %U"),
        }
    )
    desktop.setdefault("Terminal", "false")
    desktop.setdefault("Categories", "Utility;")
    app.update({"id": new_id, "name": new_name, "desktop": desktop})
    metadata = {key: value for key, value in app.items() if key != "parent"}
    bins.mkdir(parents=True, exist_ok=True)
    desktops.mkdir(parents=True, exist_ok=True)
    replace_file(new_bin, wrapper, 0o755)
    replace_file(
        new_desktop, "[Desktop Entry]\n" + "".join(f"{k}={v}\n" for k, v in desktop.items())
    )
    replace_file(parent / "app-install.json", json.dumps(metadata, indent=2) + "\n")
    if new_id != old_id:
        old_bin.unlink(missing_ok=True)
        old_desktop.unlink(missing_ok=True)
    refresh_desktops(desktops)
    print(f"Renamed {old_id} to {new_name}: {new_bin}")
