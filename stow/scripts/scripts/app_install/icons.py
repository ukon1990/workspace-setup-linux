"""Preserve existing icons and stage explicit or bundled replacements."""

import shutil
import subprocess
import uuid
from pathlib import Path

from .bundles import discover_icon
from .desktop import desktop_unescape


def prepare_icon(supplied_icon, desktop, existing, parent, stage, kind, payload, launcher, app_id):
    icon_value = desktop.get("Icon") or (existing or {}).get("desktop", {}).get("Icon")
    icon_value = desktop_unescape(icon_value) if icon_value else None
    icon_source = supplied_icon.resolve() if supplied_icon else None
    if not icon_source and icon_value and Path(icon_value).is_absolute():
        if Path(icon_value).is_file():
            saved = Path(icon_value).resolve()
            if saved.parent != parent or not saved.name.startswith("icon-"):
                icon_source = saved
        else:
            icon_value = None
    if not icon_source and not icon_value:
        if kind == "appimage":
            extraction = stage / "icons"
            extraction.mkdir()
            try:
                result = subprocess.run(
                    [str(payload / launcher), "--appimage-extract"],
                    cwd=extraction,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                if result.returncode == 0:
                    icon_source = discover_icon(extraction / "squashfs-root")
            except OSError:
                pass  # Icon discovery is optional, including on a different architecture.
        else:
            icon_source = discover_icon(payload, (app_id, Path(launcher).stem))
    if icon_source:
        suffix = icon_source.suffix.lower()
        if suffix not in (".png", ".svg", ".xpm"):
            suffix = ".png"
        saved_icon = parent / ("icon-" + uuid.uuid4().hex + suffix)
        shutil.copy2(icon_source, stage / saved_icon.name)
        icon_value = str(saved_icon)
    else:
        saved_icon = None
    return icon_value, saved_icon
