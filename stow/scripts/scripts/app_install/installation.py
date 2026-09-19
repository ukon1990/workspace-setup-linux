"""Stage bundles and publish launchers, icons, and installation metadata."""

import json
import os
import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path

from .bundles import executable, extract_tar
from .common import fail, identifier, replace_file, resolve_password_store, wrapper_script
from .desktop import desktop_escape, desktop_read, exec_quote, refresh_desktops
from .icons import prepare_icon
from .registry import installations, select_app

EXTENSIONS = (".appimage", ".tar.gz", ".tar.xz", ".tar.bz2", ".tar.zst", ".tgz", ".tar")


def install_app(args, root, bins, desktops):
    source = args.archive.resolve()
    if not source.is_file():
        fail(f"Archive not found: {source}")
    extension = next((ext for ext in EXTENSIONS if source.name.lower().endswith(ext)), None)
    if extension is None:
        fail("Unsupported format: expected AppImage or tarball.")
    kind = "appimage" if extension == ".appimage" else "tar"
    if args.icon and (
        not args.icon.is_file() or args.icon.suffix.lower() not in (".svg", ".png", ".xpm")
    ):
        fail("--icon must be an existing SVG, PNG, or XPM file.")
    name = args.name or source.name[: -len(extension)]
    app_id = args.id or identifier(name)
    if app_id != identifier(app_id):
        fail("--id must be a lowercase filesystem-safe identifier.")
    installed = installations(root, desktops)
    existing = next((app for app in installed if app["id"] == app_id), None)
    if args.update and not args.name and not args.id:
        existing = select_app([app for app in installed if app["type"] == kind])
        if existing is None:
            print("Cancelled.")
            return
    if args.update and existing is None:
        fail("No installed application matches --name.")
    if existing:
        if existing["type"] != kind:
            fail("The installed app uses a different bundle type.")
        app_id, name = existing["id"], existing["name"]
    parent = existing["parent"] if existing else root / args.subdir / app_id
    if existing is None and any(app["parent"] == parent for app in installed):
        fail("This installation directory belongs to a renamed app; choose another --name.")
    bin_path, desktop_path = bins / app_id, desktops / f"{app_id}.desktop"
    if args.dry_run or os.environ.get("DRY_RUN") == "1":
        print(
            f"Would {'update' if existing else 'install'} {name} from {source} into {parent}/current"
        )
        return
    for path in (parent, bins, desktops):
        path.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".stage-", dir=parent) as temporary:
        stage = Path(temporary)
        payload = stage / "payload"
        payload.mkdir()
        if kind == "appimage":
            target = payload / f"{app_id}.AppImage"
            shutil.copy2(source, target)
            target.chmod(target.stat().st_mode | 0o111)
            launcher = target.name
        else:
            archive = source
            if extension == ".tar.zst":
                archive = stage / "uncompressed.tar"
                with archive.open("wb") as output:
                    subprocess.run(["zstd", "-dc", "--", str(source)], stdout=output, check=True)
            payload = extract_tar(archive, payload)
            launcher = executable(
                payload, args.executable, (existing or {}).get("executable"), app_id
            )
        desktop = desktop_read(desktop_path)
        icon_value, saved_icon = prepare_icon(
            args.icon, desktop, existing, parent, stage, kind, payload, launcher, app_id
        )
        # Each release is immutable from the installer's perspective. Keep the old
        # release so running apps and rollback paths remain valid.
        release_name = "release-" + uuid.uuid4().hex
        release = parent / release_name
        desktop.update(
            {
                "Type": "Application",
                "Name": desktop_escape(name),
                "Icon": desktop_escape(icon_value or "application-x-executable"),
            }
        )
        desktop.setdefault("Terminal", "false")
        desktop.setdefault("Categories", "Utility;")
        if args.categories:
            desktop["Categories"] = args.categories
        if args.startup_class:
            desktop["StartupWMClass"] = args.startup_class
        preserve_launcher = (
            args.preserve_launcher and bin_path.is_file() and os.access(bin_path, os.X_OK)
        )
        if not (preserve_launcher and desktop.get("Exec")):
            desktop["Exec"] = desktop_escape(exec_quote(str(bin_path)) + " %U")
        password_store = resolve_password_store(getattr(args, "password_store", None), existing)
        wrapper = wrapper_script(parent / "current" / launcher, kind, password_store)
        metadata = {
            "id": app_id,
            "name": name,
            "type": kind,
            "executable": launcher,
            "desktop": desktop,
        }
        if password_store:
            metadata["password_store"] = password_store
        os.replace(payload, release)
        if saved_icon:
            os.replace(stage / saved_icon.name, saved_icon)
        current = parent / "current"
        old_directory = None
        if current.is_dir() and not current.is_symlink():
            old_directory = parent / ("legacy-" + uuid.uuid4().hex)
            current.rename(old_directory)
        link = stage / "current"
        link.symlink_to(release_name)
        try:
            os.replace(link, current)
        except OSError:
            if old_directory:
                old_directory.rename(current)
            raise
        if not preserve_launcher:
            replace_file(bin_path, wrapper, 0o755)
        replace_file(
            desktop_path, "[Desktop Entry]\n" + "".join(f"{k}={v}\n" for k, v in desktop.items())
        )
        replace_file(parent / "app-install.json", json.dumps(metadata, indent=2) + "\n")
    refresh_desktops(desktops)
    print(f"{'Updated' if existing else 'Installed'} {name}: {bin_path}")
