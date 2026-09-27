"""Privileged operations. No Textual or virtualenv dependencies."""

from __future__ import annotations

from pathlib import Path

from . import fstab
from .system import (
    current_mounts,
    discover,
    mount_matches,
    mount_options,
    run,
    selected_device,
    shared_root_mode,
    validate_target,
)


def repair_ntfs_root(target: str, mount_options_text: str) -> str:
    if "ro" in mount_options_text.split(","):
        return "Root permissions unchanged: mount is read-only."
    mode = shared_root_mode(target)
    if mode != 0o777:
        try:
            Path(target).chmod(mode | 0o777)
            updated = shared_root_mode(target)
        except OSError as error:
            return f"WARNING: NTFS root permission repair failed: {error}"
        if updated != 0o777:
            return (
                f"WARNING: NTFS root permission repair failed: "
                f"mode is {updated:o}, expected 777."
            )
        return f"Root permissions repaired: {mode:o} → {updated:o}."
    return "Root permissions: 777 (shared read/write)."


def execute(request: dict, uid: int, gid: int) -> str:
    if uid <= 0 or gid < 0:
        raise ValueError("Launch disks.sh as your regular user, not root.")
    devices = discover()
    device = selected_device(request["device"], devices)
    action = request["action"]
    if action == "unmount":
        mounts = current_mounts()
        matching = [
            m for m in mounts if m.mount_id == request["mount_id"] and mount_matches(m, device)
        ]
        if len(matching) != 1:
            raise ValueError("Mount changed or disappeared. Refresh and try again.")
        mount = matching[0]
        validate_target(mount.target, devices)
        # findmnt resolves the visible mount, including overmounts of another device.
        visible_id = run(
            ["findmnt", "--noheadings", "--output", "ID", "--target", mount.target]
        ).strip()
        if visible_id != str(mount.mount_id):
            raise ValueError(
                "This mount is hidden beneath another mount. Unmount the top layer first."
            )
        if any(Path(mount.target) in Path(m.target).parents for m in mounts):
            raise ValueError("This directory contains other mounts. Unmount those first.")
        run(["umount", "--", mount.target])
        return f"Unmounted one layer at {mount.target}."
    if action not in {"mount", "boot"}:
        raise ValueError("Unknown disk operation.")
    text = fstab.read_fstab()
    if fstab.digest(text) != request["fstab_digest"]:
        raise ValueError("fstab changed since preview. Refresh and try again.")
    old = fstab.entry_for(text, device, request["entry"])
    if old and sum(fstab.matches(old[0], d) for d in devices) != 1:
        raise ValueError("Existing fstab source matches multiple devices; use a unique UUID first.")
    target = request["target"]
    if old and target != old[1]:
        raise ValueError("Use the existing fstab mount directory.")
    path = validate_target(target, devices, mounting=action == "mount")
    if action == "mount":
        if device.mounts:
            raise ValueError("Partition is already mounted. Unmount it first.")
        if any(
            fields[1] == target and not fstab.matches(fields[0], device)
            for _, fields in fstab.entries(text)
        ):
            raise ValueError("Another fstab entry already uses this mount directory.")
        mounts = current_mounts()
        if any(Path(m.target) == path or path in Path(m.target).parents for m in mounts):
            raise ValueError("Mount directory already contains a mount.")
        options = mount_options(device, uid, gid, old[3] if old else "")
        path.mkdir(parents=True, exist_ok=True, mode=0o755)
        validate_target(target, devices, mounting=True)
        try:
            run(["mount", "-t", device.driver, "-o", ",".join(options), "--", device.path, target])
        except RuntimeError as error:
            if device.driver != "ntfs3":
                raise
            raise RuntimeError(
                f"{error}\nCheck sudo journalctl -k -n 50 for the ntfs3 reason. "
                "If the volume is dirty, run chkdsk X: /f in Windows "
                "(replace X with its drive letter), "
                "fully shut down Windows, then retry. Do not force-mount it."
            ) from error
        mounted = [m for m in current_mounts() if mount_matches(m, device) and m.target == target]
        if not mounted:
            raise RuntimeError(
                "Mount command returned, but the mount could not be verified. Refresh."
            )
        status = "READ-ONLY" if "ro" in mounted[-1].options.split(",") else "read/write"
        message = f"Mounted {device.path} at {target}: {status}.\nOptions: {mounted[-1].options}"
        if device.driver == "ntfs3" and request.get("repair_root"):
            message += f"\n{repair_ntfs_root(target, mounted[-1].options)}"
        return message
    candidate = fstab.propose(
        text,
        device,
        devices,
        target=target,
        index=request["entry"],
        enabled=request["enabled"],
        uid=uid,
        gid=gid,
    )
    if fstab.digest(candidate) != request["candidate_digest"]:
        raise ValueError("Proposed configuration changed. Refresh and review it again.")
    path.mkdir(parents=True, exist_ok=True, mode=0o755)
    validate_target(target, devices)
    backup = fstab.install(candidate, request["fstab_digest"])
    message = (
        f"fstab updated. Backup: {backup}\nCurrent mounts were not remounted."
        if backup is not None
        else "fstab already matches; no change or backup needed."
    )
    if backup is not None:
        try:
            run(["systemctl", "daemon-reload"])
        except RuntimeError as error:
            message += f"\nWARNING: systemd reload failed: {error}\nRun sudo systemctl daemon-reload."
    if request.get("repair_root") and request["enabled"] and device.driver == "ntfs3":
        matching = [m for m in device.mounts if m.target == target and mount_matches(m, device)]
        visible_id = (
            run(["findmnt", "--noheadings", "--output", "ID", "--target", target]).strip()
            if matching else ""
        )
        if matching and visible_id == str(matching[-1].mount_id):
            message += f"\n{repair_ntfs_root(target, matching[-1].options)}"
        else:
            message += "\nRoot permissions not checked: drive is no longer mounted here."
    return message
