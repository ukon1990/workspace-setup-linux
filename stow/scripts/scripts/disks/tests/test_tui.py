"""Headless interaction tests; sudo and all filesystem operations are mocked."""

import contextlib
import unittest
from unittest.mock import patch

from disks.system import Mount
from disks.tui import Configure, Confirm, DisksApp
from test_system import disk
from textual.widgets import DataTable, Input, Select, Switch


class TuiTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.devices = [disk(), disk(path="/dev/root", name="root", protected=True, devno="8:3")]
        self.discover = self.patch("disks.tui.discover", return_value=self.devices)
        self.read = self.patch("disks.tui.read_fstab", return_value="")
        self.patch("disks.tui.validate_target")
        self.patch("disks.fstab.validate_target")
        self.mode = self.patch("disks.tui.shared_root_mode", return_value=0o555)
        self.execute = self.patch("disks.tui.client.execute", return_value="Operation finished")
        self.patch("disks.tui.DisksApp.suspend", side_effect=contextlib.nullcontext)

    def patch(self, name, **kwargs):
        patcher = patch(name, **kwargs)
        self.addCleanup(patcher.stop)
        return patcher.start()

    async def test_table_navigation_and_refresh(self):
        app = DisksApp()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            self.assertEqual(app.query_one(DataTable).row_count, 2)
            self.assertEqual(app.selected().path, "/dev/sda2")
            await pilot.press("j")
            self.assertEqual(app.selected().path, "/dev/root")
            await pilot.press("k", "r")
            await pilot.pause()
            self.assertEqual(app.selected().path, "/dev/sda2")
            self.assertGreaterEqual(self.discover.call_count, 2)

    async def test_mount_review_cancel_does_not_call_sudo(self):
        app = DisksApp()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            await pilot.press("m")
            self.assertIsInstance(app.screen, Configure)
            self.assertEqual(app.screen.query_one(Input).value, "/mnt/sda2")
            await pilot.click("#review")
            await pilot.pause()
            self.assertIsInstance(app.screen, Confirm)
            self.assertIn("ntfs3", app.screen.text)
            self.assertIn("mode to 777", app.screen.text)
            await pilot.press("escape")
            self.execute.assert_not_called()

    async def test_mount_dialog_uses_arrows_and_space(self):
        app = DisksApp()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            await pilot.press("m")
            self.assertEqual(app.focused.id, "target")
            await pilot.press("right")
            self.assertEqual(app.focused.id, "target")
            await pilot.press("down")
            self.assertEqual(app.focused.id, "review")
            await pilot.press("space")
            self.assertIsInstance(app.screen, Confirm)
            self.assertEqual(app.focused.id, "confirm")
            await pilot.press("down")
            self.assertEqual(app.focused.id, "cancel")
            await pilot.press("left")
            self.assertEqual(app.focused.id, "confirm")
            await pilot.press("right")
            self.assertEqual(app.focused.id, "cancel")
            await pilot.press("enter")
            self.assertNotIsInstance(app.screen, Confirm)
            self.execute.assert_not_called()

    async def test_target_enter_opens_review_and_escape_cancels(self):
        app = DisksApp()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            await pilot.press("m", "enter")
            self.assertIsInstance(app.screen, Confirm)
            await pilot.press("escape")
            self.execute.assert_not_called()

    async def test_confirm_mount_and_close_result(self):
        app = DisksApp()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            await pilot.press("m")
            await pilot.click("#review")
            await pilot.click("#confirm")
            await pilot.pause()
            self.execute.assert_called_once()
            request = self.execute.call_args.args[0]
            self.assertEqual(request["action"], "mount")
            self.assertEqual(request["device"], self.devices[0].identity)
            self.assertTrue(request["repair_root"])
            self.assertIn("Operation finished", app.screen.text)
            self.assertEqual(app.focused.id, "cancel")
            await pilot.press("space")
            await pilot.pause()
            self.assertFalse(app.busy)

    async def test_failed_mount_resumes_terminal_before_showing_error(self):
        resumed = []

        @contextlib.contextmanager
        def suspend():
            yield
            resumed.append(True)

        self.patch("disks.tui.DisksApp.suspend", side_effect=suspend)
        self.execute.side_effect = RuntimeError("NTFS volume is dirty")
        app = DisksApp()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            await pilot.press("m")
            await pilot.click("#review")
            await pilot.click("#confirm")
            await pilot.pause()
            self.assertEqual(resumed, [True])
            self.assertIsInstance(app.screen, Confirm)
            self.assertIn("NTFS volume is dirty", app.screen.text)
            self.assertEqual(app.focused.id, "cancel")
            await pilot.press("space")
            await pilot.pause()
            self.assertFalse(app.busy)

    async def test_protected_disk_has_no_operation_dialog(self):
        app = DisksApp()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            await pilot.press("j", "m")
            self.assertIsInstance(app.screen, Confirm)
            self.assertIn("System filesystem", app.screen.text)
            self.assertFalse(app.screen.confirm)
            self.execute.assert_not_called()

    async def test_existing_boot_entry_can_be_disabled(self):
        self.read.return_value = "UUID=ABC123 /mnt/sda2 ntfs3 defaults 0 0\n"
        app = DisksApp()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            await pilot.press("b")
            self.assertTrue(app.screen.query_one(Input).disabled)
            self.assertFalse(app.screen.query_one(Switch).value)
            await pilot.click("#review")
            await pilot.pause()
            self.assertIn("noauto", app.screen.text)
            self.assertIn("/etc/fstab (proposed)", app.screen.text)
            await pilot.click("#confirm")
            await pilot.pause()
            request = self.execute.call_args.args[0]
            self.assertEqual(request["action"], "boot")
            self.assertFalse(request["enabled"])
            self.assertEqual(request["entry"], 0)
            self.assertIn("candidate_digest", request)

    async def test_boot_dialog_select_and_switch_keyboard(self):
        self.read.return_value = "UUID=ABC123 /mnt/sda2 ntfs3 defaults 0 0\n"
        app = DisksApp()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            await pilot.press("b")
            self.assertEqual(app.focused.id, "entry")
            await pilot.press("enter", "escape", "tab")
            self.assertEqual(app.focused.id, "enabled")
            await pilot.press("space", "down")
            self.assertTrue(app.screen.query_one(Switch).value)
            self.assertEqual(app.focused.id, "review")
            await pilot.press("enter")
            self.assertIsInstance(app.screen, Confirm)
            await pilot.press("escape")
            self.execute.assert_not_called()

    async def test_boot_review_discloses_mounted_root_repair(self):
        self.read.return_value = "UUID=ABC123 /mnt/sda2 ntfs3 defaults,noauto 0 0\n"
        self.devices[0].mounts = [Mount("/dev/sda2", "/mnt/sda2", "ntfs3", "rw", "8:2", 11)]
        app = DisksApp()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            await pilot.press("b")
            await pilot.click("#review")
            await pilot.pause()
            self.assertIn("NTFS root mode: 555", app.screen.text)
            await pilot.click("#confirm")
            await pilot.pause()
            self.assertTrue(self.execute.call_args.args[0]["repair_root"])

    async def test_multiple_entries_update_target_selection(self):
        self.read.return_value = (
            "UUID=ABC123 /mnt/first ntfs3 defaults 0 0\n"
            "UUID=ABC123 /mnt/second ntfs3 defaults,noauto 0 0\n"
        )
        app = DisksApp()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            await pilot.press("b")
            app.screen.query_one(Select).value = 1
            await pilot.pause()
            self.assertEqual(app.screen.query_one(Input).value, "/mnt/second")
            self.assertTrue(app.screen.query_one(Switch).value)

    async def test_unmount_dialog_retains_stacked_mount_ids(self):
        self.devices[0].mounts = [
            Mount("/dev/sda2", "/mnt/sda2", "ntfs3", "rw", "8:2", 10),
            Mount("/dev/sda2", "/mnt/sda2", "ntfs3", "ro", "8:2", 11),
        ]
        app = DisksApp()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            await pilot.press("u")
            self.assertEqual(app.screen.query_one(Select).value, 11)
            await pilot.click("#review")
            await pilot.click("#confirm")
            await pilot.pause()
            self.assertEqual(self.execute.call_args.args[0]["mount_id"], 11)

    async def test_unmount_dialog_select_and_review_keyboard(self):
        self.devices[0].mounts = [Mount("/dev/sda2", "/mnt/sda2", "ntfs3", "rw", "8:2", 11)]
        app = DisksApp()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            await pilot.press("u")
            self.assertEqual(app.focused.id, "mount")
            await pilot.press("tab")
            self.assertEqual(app.focused.id, "review")
            await pilot.press("space")
            self.assertIsInstance(app.screen, Confirm)
            await pilot.press("escape")
            self.execute.assert_not_called()
