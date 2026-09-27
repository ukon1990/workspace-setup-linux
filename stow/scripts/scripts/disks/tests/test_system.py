"""Discovery and policy tests; no disk mutations."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from disks.system import Device, discover, mount_options, selected_device, validate_target


def disk(**kwargs):
    defaults = dict(
        path="/dev/sda2",
        name="sda2",
        kind="part",
        fstype="ntfs",
        label="Data",
        uuid="ABC123",
        partuuid="PART123",
        partlabel="",
        devno="8:2",
        size="1T",
        readonly=False,
    )
    return Device(**(defaults | kwargs))


class PolicyTests(unittest.TestCase):
    def test_ntfs_driver_and_normal_user_ownership(self):
        device = disk()
        self.assertEqual(device.driver, "ntfs3")
        options = mount_options(device, 1000, 1001, "ro,uid=0,gid=0,acl,umask=077,force")
        self.assertEqual(
            options,
            ["uid=1000", "gid=1001", "dmask=000", "fmask=111", "rw", "nosuid", "nodev"],
        )

    def test_native_filesystem_preserves_permissions_and_subvolume(self):
        options = mount_options(
            disk(fstype="btrfs"), 1000, 1000, "subvol=/data,compress=zstd,noauto"
        )
        self.assertIn("subvol=/data", options)
        self.assertIn("compress=zstd", options)
        self.assertFalse(any(o.startswith("uid=") for o in options))

    def test_fat_ownership(self):
        for fs in ("vfat", "exfat"):
            with self.subTest(fs=fs):
                options = mount_options(disk(fstype=fs), 1000, 1000)
                self.assertIn("uid=1000", options)
                self.assertIn("dmask=000", options)
                self.assertIn("fmask=111", options)

    def test_changed_and_protected_device_rejected(self):
        device = disk()
        with self.assertRaisesRegex(ValueError, "changed"):
            selected_device(device.identity, [disk(uuid="OTHER")])
        device.protected = True
        with self.assertRaisesRegex(ValueError, "System"):
            selected_device(device.identity, [device])

    def test_unsafe_targets(self):
        for target in ("/", "/home", "/etc/data", "/mnt", "/mnt/../etc", "/mnt/a\nb", "relative"):
            with self.subTest(target=target), self.assertRaises(ValueError):
                validate_target(target, [])

    def test_symlink_and_nonempty_target(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            patch("disks.system.DATA_ROOTS", (Path(directory),)),
        ):
            root = Path(directory)
            actual = root / "actual"
            actual.mkdir()
            link = root / "link"
            link.symlink_to(actual)
            with self.assertRaisesRegex(ValueError, "symlinks"):
                validate_target(str(link), [], mounting=True)
            (actual / "keep.txt").write_text("existing data")
            with self.assertRaisesRegex(ValueError, "not empty"):
                validate_target(str(actual), [], mounting=True)

    def test_discovery_protects_system_backing_devices_but_not_sibling_data(self):
        def block(path, devno, fs, children=None):
            return {
                "path": path,
                "kname": path,
                "type": "part",
                "fstype": fs,
                "maj:min": devno,
                "size": "1T",
                "ro": False,
                "children": children or [],
            }

        blocks = {
            "blockdevices": [
                block(
                    "/dev/sda",
                    "8:0",
                    None,
                    [
                        block("/dev/sda1", "8:1", "btrfs"),
                        block("/dev/sda2", "8:2", "ntfs"),
                    ],
                )
            ]
        }
        mounts = {
            "filesystems": [
                {
                    "source": "/dev/sda1",
                    "target": "/",
                    "fstype": "btrfs",
                    "options": "rw",
                    "maj:min": "8:1",
                    "id": 10,
                }
            ]
        }
        with patch("disks.system.run", side_effect=[json.dumps(blocks), json.dumps(mounts)]):
            devices = discover()
        self.assertEqual([d.protected for d in devices], [True, True, False])

    def test_btrfs_virtual_device_number_still_protects_root(self):
        blocks = {
            "blockdevices": [
                {
                    "path": "/dev/nvme0n1p4",
                    "kname": "/dev/nvme0n1p4",
                    "type": "part",
                    "fstype": "btrfs",
                    "maj:min": "259:4",
                    "size": "1T",
                    "ro": False,
                }
            ]
        }
        mounts = {
            "filesystems": [
                {
                    "source": "/dev/nvme0n1p4[/@]",
                    "target": "/",
                    "fstype": "btrfs",
                    "options": "rw,subvol=/@",
                    "maj:min": "0:36",
                    "id": 10,
                }
            ]
        }
        with patch("disks.system.run", side_effect=[json.dumps(blocks), json.dumps(mounts)]):
            devices = discover()
        self.assertTrue(devices[0].protected)
        self.assertEqual(devices[0].mounts[0].target, "/")

    def test_lsblk_mountpoints_protects_secondary_btrfs_members(self):
        blocks = {
            "blockdevices": [
                {
                    "path": "/dev/sdb1",
                    "kname": "/dev/sdb1",
                    "type": "part",
                    "fstype": "btrfs",
                    "maj:min": "8:17",
                    "size": "1T",
                    "ro": False,
                    "mountpoints": ["/home"],
                }
            ]
        }
        with patch("disks.system.run", side_effect=[json.dumps(blocks), '{"filesystems": []}']):
            self.assertTrue(discover()[0].protected)
