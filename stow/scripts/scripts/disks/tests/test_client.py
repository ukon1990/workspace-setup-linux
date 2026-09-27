"""Verify authentication failures cannot reach the privileged helper."""

import subprocess
import unittest
from unittest.mock import patch

from disks import client


class ClientTests(unittest.TestCase):
    @patch("disks.client.subprocess.run")
    def test_authentication_failure_stops_before_helper(self, run):
        run.return_value = subprocess.CompletedProcess(["sudo", "-v"], 1)
        with self.assertRaisesRegex(RuntimeError, "authentication"):
            client.execute({"action": "mount"})
        run.assert_called_once_with(["sudo", "-v"], check=False)

    @patch("disks.client.subprocess.run")
    def test_helper_uses_isolated_system_python_and_json_stdin(self, run):
        run.side_effect = [
            subprocess.CompletedProcess(["sudo", "-v"], 0),
            subprocess.CompletedProcess([], 0, stdout="Mounted\n", stderr=""),
        ]
        self.assertEqual(client.execute({"action": "mount"}), "Mounted")
        command = run.call_args.args[0]
        self.assertEqual(command[:6], ["sudo", "-n", "--", "/usr/bin/python3", "-I", "-B"])
        self.assertEqual(run.call_args.kwargs["input"], '{"action": "mount"}')

    @patch("disks.client.subprocess.run")
    def test_helper_failure_is_reported(self, run):
        run.side_effect = [
            subprocess.CompletedProcess(["sudo", "-v"], 0),
            subprocess.CompletedProcess([], 1, stdout="", stderr="target is busy\n"),
        ]
        with self.assertRaisesRegex(RuntimeError, "target is busy"):
            client.execute({"action": "unmount"})
