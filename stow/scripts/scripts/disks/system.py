"""Read-only disk discovery and mount policy, shared with the privileged helper."""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

SUPPORTED = {"ntfs", "ntfs3", "vfat", "exfat", "ext4", "xfs", "btrfs"}
DATA_ROOTS = (Path("/mnt"), Path("/media"), Path("/run/media"))


def run(args: list[str]) -> str:
    result = subprocess.run(args, capture_output=True, text=True, check=False)
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip() or f"{args[0]} failed")
    return result.stdout


def data_target(target: str) -> bool:
    path = Path(target)
    return path.is_absolute() and any(root in path.parents for root in DATA_ROOTS)


@dataclass
class Mount:
    source: str
    target: str
    fstype: str
    options: str
    devno: str
    mount_id: int


@dataclass
class Device:
    path: str
    name: str
    kind: str
    fstype: str
    label: str
    uuid: str
    partuuid: str
    partlabel: str
    devno: str
    size: str
    readonly: bool
    mounts: list[Mount] = field(default_factory=list)
    protected: bool = False

    @property
    def identity(self) -> dict:
        return {"path": self.path, "devno": self.devno, "uuid": self.uuid, "fstype": self.fstype}

    @property
    def driver(self) -> str:
        return "ntfs3" if self.fstype in {"ntfs", "ntfs3"} else self.fstype

    @property
    def reason(self) -> str:
        if self.protected:
            return "System filesystem or backing device (view only)"
        if self.fstype not in SUPPORTED:
            return "Unsupported filesystem or container (view only)"
        if self.readonly:
            return "Read-only device (view only)"
        return ""


def mount_matches(mount: Mount, device: Device) -> bool:
    # Btrfs uses a virtual MAJ:MIN for mounts; its source still names the block device.
    source = mount.source.split("[", 1)[0]
    return mount.devno == device.devno or (
        source.startswith("/dev/") and Path(source).resolve() == Path(device.path).resolve()
    )


def current_mounts() -> list[Mount]:
    mounted = json.loads(
        run(
            [
                "findmnt",
                "--json",
                "--list",
                "--output",
                "SOURCE,TARGET,FSTYPE,OPTIONS,MAJ:MIN,ID",
            ]
        )
    )
    return [
        Mount(
            item["source"],
            item["target"],
            item["fstype"],
            item["options"],
            item["maj:min"],
            int(item["id"]),
        )
        for item in mounted.get("filesystems", [])
    ]


def discover() -> list[Device]:
    block = json.loads(
        run(
            [
                "lsblk",
                "--json",
                "--paths",
                "--output",
                "NAME,KNAME,PATH,TYPE,FSTYPE,LABEL,UUID,PARTUUID,PARTLABEL,MAJ:MIN,SIZE,RO,MOUNTPOINTS",
            ]
        )
    )
    mounts = current_mounts()
    devices: dict[str, Device] = {}
    parents: dict[str, set[str]] = {}

    def visit(item: dict, parent: str = "") -> None:
        devno = item["maj:min"]
        parents.setdefault(devno, set()).update([parent] if parent else [])
        devices[devno] = Device(
            path=item["path"],
            name=Path(item["kname"]).name,
            kind=item["type"],
            fstype=item.get("fstype") or "",
            label=item.get("label") or "",
            uuid=item.get("uuid") or "",
            partuuid=item.get("partuuid") or "",
            partlabel=item.get("partlabel") or "",
            devno=devno,
            size=item["size"],
            readonly=bool(item["ro"]),
            protected=any(not data_target(p) for p in item.get("mountpoints", []) if p),
        )
        devices[devno].mounts = [m for m in mounts if mount_matches(m, devices[devno])]
        for child in item.get("children", []):
            visit(child, devno)

    for item in block.get("blockdevices", []):
        visit(item)
    protected = {
        d.devno
        for d in devices.values()
        if d.protected or any(not data_target(m.target) for m in d.mounts)
    }
    protected_uuids = {d.uuid for d in devices.values() if d.devno in protected and d.uuid}
    protected.update(d.devno for d in devices.values() if d.uuid in protected_uuids)
    pending = list(protected)
    while pending:
        for parent in parents.get(pending.pop(), set()):
            if parent not in protected:
                protected.add(parent)
                pending.append(parent)
    for device in devices.values():
        device.protected = device.devno in protected
    return list(devices.values())


def selected_device(identity: dict, devices: list[Device]) -> Device:
    matches = [d for d in devices if d.identity == identity]
    if len(matches) != 1:
        raise ValueError("Device changed or disappeared. Refresh and try again.")
    device = matches[0]
    if device.reason:
        raise ValueError(device.reason)
    return device


def validate_target(target: str, devices: list[Device], *, mounting: bool = False) -> Path:
    path = Path(target)
    if not data_target(target) or ".." in path.parts or any(ord(c) < 32 for c in target):
        raise ValueError("Choose a data directory below /mnt, /media, or /run/media.")
    if str(path) != target or path.resolve() != path:
        raise ValueError("Mount directory must be normalized and contain no symlinks.")
    for ancestor in (path, *path.parents):
        if ancestor.is_symlink():
            raise ValueError("Mount directory must contain no symlinks.")
    if path.exists() and not path.is_dir():
        raise ValueError("Mount directory is not a directory.")
    if mounting:
        for device in devices:
            if any(Path(m.target) == path or path in Path(m.target).parents for m in device.mounts):
                raise ValueError("Directory already contains a mount. Unmount it first.")
        if path.exists() and next(path.iterdir(), None) is not None:
            raise ValueError("Mount directory is not empty.")
    return path


def mount_options(device: Device, uid: int, gid: int, existing: str = "") -> list[str]:
    options = [
        o
        for o in existing.split(",")
        if o
        and o
        not in {
            "defaults",
            "ro",
            "rw",
            "auto",
            "noauto",
            "nofail",
            "user",
            "users",
            "owner",
            "suid",
            "nosuid",
            "dev",
            "nodev",
        }
        and not o.startswith("x-systemd.")
    ]
    if device.driver in {"ntfs3", "vfat", "exfat"}:
        options = [
            o
            for o in options
            if o.split("=", 1)[0]
            not in {
                "uid",
                "gid",
                "umask",
                "fmask",
                "dmask",
                "acl",
                "noacsrules",
                "no_acs_rules",
                "permissions",
                "usermapping",
                "force",
                "remove_hiberfile",
            }
        ]
        options += [f"uid={uid}", f"gid={gid}", "dmask=000", "fmask=111"]
    return list(dict.fromkeys([*options, "rw", "nosuid", "nodev"]))


def access_status(target: str) -> str:
    return "read/write" if os.access(target, os.R_OK | os.W_OK | os.X_OK) else "limited access"


def shared_root_mode(target: str) -> int:
    return os.stat(target).st_mode & 0o777
