"""Conservative fstab edits and atomic, backed-up installation."""

from __future__ import annotations

import fcntl
import hashlib
import os
import re
import shutil
import stat
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from .system import Device, mount_matches, mount_options, run, validate_target


def read_fstab() -> str:
    return Path("/etc/fstab").read_bytes().decode()


def digest(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def escape(value: str) -> str:
    return (
        value.replace("\\", "\\134")
        .replace(" ", "\\040")
        .replace("\t", "\\011")
        .replace("#", "\\043")
    )


def unescape(value: str) -> str:
    return re.sub(r"\\([0-7]{3})", lambda m: chr(int(m[1], 8)), value)


def entries(text: str) -> list[tuple[int, list[str]]]:
    result = []
    for index, line in enumerate(text.splitlines()):
        if line.strip() and not line.lstrip().startswith("#"):
            fields = line.split("#", 1)[0].split()
            if len(fields) not in {4, 5, 6}:
                raise ValueError(f"Invalid fstab entry on line {index + 1}; fix it first.")
            result.append((index, [unescape(f) for f in fields] + ["0"] * (6 - len(fields))))
    return result


def matches(source: str, device: Device) -> bool:
    tags = {
        "UUID": device.uuid,
        "LABEL": device.label,
        "PARTUUID": device.partuuid,
        "PARTLABEL": device.partlabel,
    }
    if "=" in source:
        tag, value = source.split("=", 1)
        return bool(tags.get(tag)) and value.strip('"') == tags[tag]
    return source.startswith("/dev/") and Path(source).resolve() == Path(device.path).resolve()


def matching_entries(text: str, device: Device) -> list[tuple[int, list[str]]]:
    return [(i, fields) for i, fields in entries(text) if matches(fields[0], device)]


def boot_enabled(fields: list[str]) -> bool:
    options = fields[3].split(",")
    return "noauto" not in options or "x-systemd.automount" in options


def entry_for(text: str, device: Device, index: int | None) -> list[str] | None:
    found = matching_entries(text, device)
    if index is None:
        if found:
            raise ValueError("Select an existing fstab entry; duplicate entries are not added.")
        return None
    for line, fields in found:
        if line == index:
            return fields
    raise ValueError("Selected fstab entry changed. Refresh and try again.")


def propose(
    text: str,
    device: Device,
    devices: list[Device],
    *,
    target: str,
    index: int | None,
    enabled: bool,
    uid: int,
    gid: int,
) -> str:
    old = entry_for(text, device, index)
    already_mounted_here = any(
        m.target == target and mount_matches(m, device) for m in device.mounts
    )
    validate_target(target, devices, mounting=enabled and not already_mounted_here)
    if any(m.target == target and not mount_matches(m, device) for d in devices for m in d.mounts):
        raise ValueError("A different filesystem is currently mounted at this directory.")
    if old and old[1] != target:
        raise ValueError("Existing fstab mount directories cannot be moved here.")
    for line, fields in entries(text):
        if line != index and fields[1] == target:
            raise ValueError("Another fstab entry already uses this mount directory.")
    if not old and (not device.uuid or sum(d.uuid == device.uuid for d in devices) != 1):
        raise ValueError("A unique filesystem UUID is required for boot configuration.")
    if enabled:
        options = mount_options(device, uid, gid, old[3] if old else "")
        options += ["nofail", "x-systemd.device-timeout=5s"]
    elif old:
        options = [
            o
            for o in old[3].split(",")
            if o not in {"auto", "noauto", "x-systemd.automount"}
            and not o.startswith(("x-systemd.wanted-by=", "x-systemd.required-by="))
        ]
        options.append("noauto")
    else:
        raise ValueError("This partition has no boot entry to disable.")
    fields = [
        old[0] if old else f"UUID={device.uuid}",
        target,
        device.driver if enabled else old[2],
        ",".join(options),
        old[4] if old else "0",
        old[5] if old else "0",
    ]
    replacement = "\t".join(escape(f) for f in fields)
    lines = text.splitlines(keepends=True)
    if index is None:
        if lines and not lines[-1].endswith("\n"):
            lines[-1] += "\n"
        lines.append(replacement + "\n")
    else:
        original = lines[index]
        comment = " #" + original.split("#", 1)[1].rstrip("\n") if "#" in original else ""
        # Keep byte-for-byte formatting when the effective entry already matches.
        if old == fields:
            return text
        lines[index] = replacement + comment + ("\n" if original.endswith("\n") else "")
    return "".join(lines)


def install(candidate: str, expected: str, path: Path = Path("/etc/fstab")) -> Path | None:
    """Caller is privileged. Never overwrite a concurrently changed file."""
    backup_dir = path.with_name("fstab.backups")
    lock_path = path.with_name(".fstab.disks.lock")
    descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if path.is_symlink() or not path.is_file():
            raise ValueError("fstab must be a regular file, not a symlink.")
        original = path.read_bytes().decode()
        if digest(original) != expected:
            raise ValueError("fstab changed since preview. Refresh and review the change again.")
        if candidate == original:
            return None
        metadata = path.stat()
        fd, temporary = tempfile.mkstemp(prefix=".fstab.disks-", dir=path.parent)
        staged = Path(temporary)
        try:
            with os.fdopen(fd, "w") as output:
                output.write(candidate)
                output.flush()
                os.fsync(output.fileno())
                os.fchown(output.fileno(), metadata.st_uid, metadata.st_gid)
                os.fchmod(output.fileno(), stat.S_IMODE(metadata.st_mode))
            run(["findmnt", "--verify", "--tab-file", str(staged)])
            if backup_dir.is_symlink():
                raise ValueError("Backup directory must not be a symlink.")
            backup_dir.mkdir(mode=0o700, exist_ok=True)
            if backup_dir.stat().st_uid != os.geteuid() or backup_dir.stat().st_mode & 0o022:
                raise ValueError(
                    "Backup directory must be owned by root and not group/world writable."
                )
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
            backup = backup_dir / f"fstab.{stamp}"
            with backup.open("xb") as output:
                output.write(original.encode())
                output.flush()
                os.fsync(output.fileno())
            shutil.copystat(path, backup)
            if digest(path.read_bytes().decode()) != expected:
                raise ValueError("fstab changed during validation; nothing was overwritten.")
            os.replace(staged, path)
            directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
            return backup
        finally:
            staged.unlink(missing_ok=True)
