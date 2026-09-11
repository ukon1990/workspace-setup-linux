"""Validate and extract archives, and discover launchers and icons."""

import os
import tarfile
from pathlib import Path

from .common import fail, identifier
from .desktop import desktop_read


def extract_tar(source, destination):
    # Validate all paths and links before extraction. Reject devices and FIFOs.
    with tarfile.open(source, "r:*") as archive:
        members = archive.getmembers()
        if not members:
            fail("Archive is empty.")
        for member in members:
            if Path(member.name).is_absolute() or ".." in Path(member.name).parts:
                fail(f"Unsafe archive path: {member.name}")
            if not (member.isfile() or member.isdir() or member.issym() or member.islnk()):
                fail(f"Unsupported archive entry: {member.name}")
            if member.issym() or member.islnk():
                base = Path(member.name).parent if member.issym() else Path(".")
                target = os.path.normpath(str(base / member.linkname))
                if os.path.isabs(target) or target == ".." or target.startswith("../"):
                    fail(f"Unsafe archive link: {member.name}")
        archive.extractall(destination, members=members, filter="data")
    entries = list(destination.iterdir())
    return (
        entries[0]
        if len(entries) == 1 and entries[0].is_dir() and not entries[0].is_symlink()
        else destination
    )


def executable(payload, explicit, previous, app_id):
    def valid(relative):
        path = payload / relative
        return (
            path.resolve().is_relative_to(payload.resolve())
            and path.is_file()
            and os.access(path, os.X_OK)
        )

    if explicit:
        for relative in explicit:
            if not Path(relative).is_absolute() and valid(relative):
                return relative
        fail(f"Executable is missing, outside the archive, or not executable: {explicit}")
    if previous and valid(previous):
        return previous
    candidates = sorted(
        str(p.relative_to(payload))
        for p in payload.rglob("*")
        if p.is_file() and os.access(p, os.X_OK) and valid(str(p.relative_to(payload)))
    )
    matches = [p for p in candidates if identifier(Path(p).stem) == app_id]
    native = [p for p in matches if not p.endswith(".sh")]
    if len(native) == 1:
        return native[0]
    if len(matches) == 1:
        return matches[0]
    if len(candidates) == 1:
        return candidates[0]
    fail(
        "Cannot determine launcher; pass --exec with a relative path. Candidates: "
        + (", ".join(candidates) or "(none)")
    )


def discover_icon(payload, hints=()):
    for candidate in [payload / ".DirIcon"]:
        if candidate.is_file() and candidate.resolve().is_relative_to(payload.resolve()):
            return candidate.resolve()
    icons = sorted(
        p
        for p in payload.rglob("*")
        if p.suffix.lower() in (".png", ".svg", ".xpm")
        and p.is_file()
        and p.resolve().is_relative_to(payload.resolve())
    )
    for desktop in sorted(payload.rglob("*.desktop")):
        name = desktop_read(desktop).get("Icon", "")
        matches = [p for p in icons if p.name == name or p.stem == name]
        if matches:
            return matches[0]
    for hint in hints:
        matches = [p for p in icons if p.stem.lower() == hint.lower()]
        if matches:
            return matches[0]
    return icons[0] if len(icons) == 1 else None
