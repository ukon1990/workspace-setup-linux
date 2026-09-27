"""Preview and transaction tests using only temporary fstab files."""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from disks import fstab
from test_system import disk


class PreviewTests(unittest.TestCase):
    def setUp(self):
        patcher = patch("disks.fstab.validate_target")
        patcher.start()
        self.addCleanup(patcher.stop)

    def propose(self, text="", **kwargs):
        defaults = dict(target="/mnt/sda2", index=None, enabled=True, uid=1000, gid=1000)
        device = disk()
        return fstab.propose(text, device, [device], **(defaults | kwargs))

    def test_uuid_boot_options_and_unrelated_content(self):
        original = "# keep me\nUUID=ROOT / ext4 defaults 0 1\n"
        result = self.propose(original)
        self.assertTrue(result.startswith(original))
        self.assertIn("UUID=ABC123\t/mnt/sda2\tntfs3\t", result)
        self.assertIn("uid=1000,gid=1000,dmask=000,fmask=111", result)
        self.assertIn("nofail,x-systemd.device-timeout=5s", result)

    def test_escaped_paths_and_comments_preserved(self):
        original = "# keep\nUUID=ABC123 /mnt/My\\040Disk ntfs ro,uid=0 0 0 # data\n"
        result = self.propose(original, target="/mnt/My Disk", index=1)
        self.assertIn("/mnt/My\\040Disk", result)
        self.assertTrue(result.endswith(" # data\n"))
        self.assertEqual(fstab.entries(result)[0][1][1], "/mnt/My Disk")
        value = "/mnt/back\\slash #1"
        self.assertEqual(fstab.unescape(fstab.escape(value)), value)

    def test_no_duplicate_entries_or_targets(self):
        for original in (
            "UUID=ABC123 /mnt/other ntfs3 defaults 0 0\n",
            "UUID=OTHER /mnt/sda2 ext4 defaults 0 0\n",
        ):
            with self.subTest(original=original), self.assertRaises(ValueError):
                self.propose(original)

    def test_selects_one_of_multiple_entries(self):
        original = (
            "UUID=ABC123 /mnt/sda2 ntfs3 defaults 0 0\nUUID=ABC123 /mnt/other ntfs3 defaults 0 0\n"
        )
        result = self.propose(original, index=1, target="/mnt/other", enabled=False)
        self.assertTrue(result.startswith(original.splitlines(keepends=True)[0]))
        self.assertIn("defaults,noauto", result)

    def test_disable_removes_automount_and_boot_dependency(self):
        original = "UUID=ABC123 /mnt/sda2 ntfs3 defaults,x-systemd.automount,x-systemd.wanted-by=multi-user.target 0 0\n"
        result = self.propose(original, index=0, enabled=False)
        fields = fstab.entries(result)[0][1]
        self.assertFalse(fstab.boot_enabled(fields))
        self.assertEqual(fields[3], "defaults,noauto")

    def test_unique_uuid_required(self):
        for devices in ([disk(uuid="")], [disk(), disk(path="/dev/sdb2")]):
            with self.subTest(devices=devices), self.assertRaisesRegex(ValueError, "unique"):
                fstab.propose(
                    "",
                    devices[0],
                    devices,
                    target="/mnt/sda2",
                    index=None,
                    enabled=True,
                    uid=1000,
                    gid=1000,
                )

    def test_repeated_enable_is_noop(self):
        original = self.propose()
        self.assertEqual(self.propose(original, index=0), original)

    def test_source_matching(self):
        for source in ("UUID=ABC123", "LABEL=Data", "PARTUUID=PART123", "/dev/sda2"):
            self.assertTrue(fstab.matches(source, disk()))
        self.assertFalse(fstab.matches("UUID=OTHER", disk()))


class TransactionTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "fstab"
        self.original = "# Original\n"
        self.candidate = "# Updated\n"
        self.path.write_text(self.original)
        self.path.chmod(0o640)

    def install(self):
        return fstab.install(self.candidate, fstab.digest(self.original), self.path)

    @patch("disks.fstab.run")
    def test_backup_and_atomic_update(self, run):
        backup = self.install()
        self.assertEqual(backup.read_text(), self.original)
        self.assertEqual(self.path.read_text(), self.candidate)
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o640)
        self.assertEqual(backup.stat().st_uid, os.geteuid())
        self.assertEqual(run.call_args.args[0][:3], ["findmnt", "--verify", "--tab-file"])
        self.assertEqual(list(self.path.parent.glob(".fstab.disks-*")), [])

    @patch("disks.fstab.run", side_effect=RuntimeError("invalid candidate"))
    def test_validation_failure_leaves_original(self, run):
        with self.assertRaisesRegex(RuntimeError, "invalid"):
            self.install()
        self.assertEqual(self.path.read_text(), self.original)
        self.assertFalse((self.path.parent / "fstab.backups").exists())

    @patch("disks.fstab.run")
    def test_backup_failure_leaves_original(self, run):
        with patch("disks.fstab.shutil.copystat", side_effect=OSError("backup failed")):
            with self.assertRaisesRegex(OSError, "backup"):
                self.install()
        self.assertEqual(self.path.read_text(), self.original)

    def test_concurrent_edit_before_preview_commit(self):
        self.path.write_text("# Someone else's edit\n")
        with self.assertRaisesRegex(ValueError, "changed since preview"):
            self.install()
        self.assertEqual(self.path.read_text(), "# Someone else's edit\n")

    def test_concurrent_edit_during_validation(self):
        with patch(
            "disks.fstab.run", side_effect=lambda _: self.path.write_text("# Concurrent edit\n")
        ):
            with self.assertRaisesRegex(ValueError, "changed during"):
                self.install()
        self.assertEqual(self.path.read_text(), "# Concurrent edit\n")

    @patch("disks.fstab.run")
    def test_noop_has_no_backup(self, run):
        self.assertIsNone(fstab.install(self.original, fstab.digest(self.original), self.path))
        run.assert_not_called()

    @patch("disks.fstab.run")
    def test_backups_accumulate(self, run):
        first = self.install()
        second = fstab.install(self.original, fstab.digest(self.candidate), self.path)
        self.assertNotEqual(first, second)
        self.assertEqual(first.read_text(), self.original)
        self.assertEqual(second.read_text(), self.candidate)

    @patch("disks.fstab.run")
    def test_symlink_backup_directory_rejected(self, run):
        (self.path.parent / "fstab.backups").symlink_to(self.path.parent)
        with self.assertRaisesRegex(ValueError, "symlink"):
            self.install()
        self.assertEqual(self.path.read_text(), self.original)
