"""Privileged operations tested entirely through mocked system boundaries."""

import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from disks import fstab, operations
from disks.system import Mount
from test_system import disk


class OperationsTests(unittest.TestCase):
    def setUp(self):
        self.device = disk()
        self.run = self.patch("disks.operations.run", return_value="")
        self.patch("disks.operations.discover", return_value=[self.device])
        self.read = self.patch("disks.operations.fstab.read_fstab", return_value="")
        self.target = Mock()
        self.patch("disks.operations.validate_target", return_value=self.target)
        self.patch("disks.fstab.validate_target", return_value=self.target)
        self.mode = self.patch("disks.operations.shared_root_mode", return_value=0o777)
        self.chmod = self.patch("disks.operations.Path.chmod")
        self.mount = Mount("/dev/sda2", "/mnt/sda2", "ntfs3", "rw,uid=1000,gid=1000", "8:2", 11)
        self.mounts = self.patch("disks.operations.current_mounts", side_effect=[[], [self.mount]])
        self.request = {
            "action": "mount",
            "device": self.device.identity,
            "entry": None,
            "target": "/mnt/sda2",
            "fstab_digest": fstab.digest(""),
            "repair_root": True,
        }

    def patch(self, name, **kwargs):
        patcher = patch(name, **kwargs)
        self.addCleanup(patcher.stop)
        return patcher.start()

    def test_mount_ntfs_as_invoking_user(self):
        result = operations.execute(self.request, 1000, 1000)
        self.assertIn("read/write", result)
        self.run.assert_called_once_with(
            [
                "mount",
                "-t",
                "ntfs3",
                "-o",
                "uid=1000,gid=1000,dmask=000,fmask=111,rw,nosuid,nodev",
                "--",
                "/dev/sda2",
                "/mnt/sda2",
            ]
        )

    def test_readonly_result_is_explicit(self):
        self.mount.options = "ro,uid=1000,gid=1000"
        self.assertIn("READ-ONLY", operations.execute(self.request, 1000, 1000))
        self.chmod.assert_not_called()

    def test_mount_repairs_restricted_ntfs_root(self):
        self.mode.side_effect = [0o555, 0o777]
        result = operations.execute(self.request, 1000, 1000)
        self.chmod.assert_called_once_with(0o777)
        self.assertIn("555 → 777", result)

    def test_mount_leaves_accessible_root_alone(self):
        self.assertIn("shared read/write", operations.execute(self.request, 1000, 1000))
        self.chmod.assert_not_called()

    def test_repair_failure_is_reported(self):
        self.mode.side_effect = [0o555, 0o555]
        result = operations.execute(self.request, 1000, 1000)
        self.assertIn("WARNING: NTFS root permission repair failed", result)

    def test_chmod_error_is_reported_after_mount(self):
        self.mode.return_value = 0o555
        self.chmod.side_effect = PermissionError("permission denied")
        result = operations.execute(self.request, 1000, 1000)
        self.assertIn("Mounted /dev/sda2", result)
        self.assertIn("WARNING: NTFS root permission repair failed: permission denied", result)

    def test_failed_ntfs_mount_explains_where_to_find_the_reason(self):
        self.run.side_effect = RuntimeError("mount: wrong fs type")
        with self.assertRaisesRegex(RuntimeError, "journalctl -k -n 50.*dirty.*chkdsk"):
            operations.execute(self.request, 1000, 1000)
        self.assertEqual(self.run.call_count, 1)

    def test_root_identity_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "regular user"):
            operations.execute(self.request, 0, 0)
        self.run.assert_not_called()

    def test_already_mounted_cannot_stack(self):
        self.device.mounts = [self.mount]
        with self.assertRaisesRegex(ValueError, "already mounted"):
            operations.execute(self.request, 1000, 1000)
        self.run.assert_not_called()

    def test_changed_fstab_prevents_mount(self):
        self.read.return_value = "# external edit"
        with self.assertRaisesRegex(ValueError, "fstab changed"):
            operations.execute(self.request, 1000, 1000)
        self.run.assert_not_called()

    def unmount_request(self):
        self.device.mounts = [self.mount]
        self.mounts.side_effect = None
        self.mounts.return_value = [self.mount]
        return {"action": "unmount", "device": self.device.identity, "mount_id": 11}

    def test_hidden_mount_refused(self):
        request = self.unmount_request()
        self.run.return_value = "12\n"
        with self.assertRaisesRegex(ValueError, "hidden"):
            operations.execute(request, 1000, 1000)
        self.assertEqual(self.run.call_count, 1)

    def test_one_unmount_only(self):
        request = self.unmount_request()
        self.run.side_effect = ["11\n", ""]
        self.assertIn("one layer", operations.execute(request, 1000, 1000))
        self.assertEqual(self.run.call_args.args[0], ["umount", "--", "/mnt/sda2"])

    def test_busy_error_never_forces(self):
        request = self.unmount_request()
        self.run.side_effect = ["11\n", RuntimeError("target is busy")]
        with self.assertRaisesRegex(RuntimeError, "busy"):
            operations.execute(request, 1000, 1000)
        self.assertEqual(self.run.call_count, 2)

    def test_boot_saves_reviewed_candidate_and_reports_reload_failure(self):
        candidate = fstab.propose(
            "",
            self.device,
            [self.device],
            target="/mnt/sda2",
            index=None,
            enabled=True,
            uid=1000,
            gid=1000,
        )
        request = self.request | {
            "action": "boot",
            "enabled": True,
            "candidate_digest": fstab.digest(candidate),
        }
        install = self.patch(
            "disks.operations.fstab.install", return_value=Path("/etc/fstab.backups/test")
        )
        self.run.side_effect = RuntimeError("reload failed")
        result = operations.execute(request, 1000, 1000)
        install.assert_called_once_with(candidate, fstab.digest(""))
        self.assertIn("Backup: /etc/fstab.backups/test", result)
        self.assertIn("reload failed", result)
        self.run.assert_called_once_with(["systemctl", "daemon-reload"])

    def test_boot_repairs_already_mounted_ntfs_root(self):
        self.device.mounts = [self.mount]
        candidate = fstab.propose(
            "", self.device, [self.device], target="/mnt/sda2", index=None,
            enabled=True, uid=1000, gid=1000,
        )
        request = self.request | {
            "action": "boot", "enabled": True,
            "candidate_digest": fstab.digest(candidate),
        }
        self.patch("disks.operations.fstab.install", return_value=None)
        self.mode.side_effect = [0o555, 0o777]
        self.run.return_value = "11\n"
        result = operations.execute(request, 1000, 1000)
        self.assertIn("555 → 777", result)
        self.chmod.assert_called_once_with(0o777)

    def test_unreviewed_candidate_is_rejected(self):
        request = self.request | {"action": "boot", "enabled": True, "candidate_digest": "wrong"}
        with self.assertRaisesRegex(ValueError, "configuration changed"):
            operations.execute(request, 1000, 1000)
        self.run.assert_not_called()
