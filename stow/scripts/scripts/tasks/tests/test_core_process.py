import subprocess
import unittest
from unittest.mock import Mock, patch

from tasks.process import ProcessError, ProcessErrorKind, run_json, run_text


class ProcessTests(unittest.TestCase):
    @patch("tasks.process.subprocess.run")
    def test_runs_argument_list_without_shell(self, run):
        run.return_value = Mock(returncode=0, stdout="ok\n", stderr="")
        self.assertEqual(run_text(["gh", "auth", "status"]), "ok\n")
        run.assert_called_once_with(
            ["gh", "auth", "status"],
            shell=False,
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
            cwd=None,
            env=None,
        )

    def test_rejects_string_command(self):
        with self.assertRaises(ProcessError) as raised:
            run_text("gh issue list")
        self.assertEqual(raised.exception.kind, ProcessErrorKind.INVALID_COMMAND)

    def test_rejects_invalid_timeout(self):
        with self.assertRaises(ProcessError) as raised:
            run_text(["gh"], timeout=False)
        self.assertEqual(raised.exception.kind, ProcessErrorKind.INVALID_COMMAND)

    @patch("tasks.process.subprocess.run")
    def test_reports_missing_command(self, run):
        run.side_effect = FileNotFoundError
        with self.assertRaises(ProcessError) as raised:
            run_text(["acli", "jira", "auth"])
        self.assertEqual(raised.exception.kind, ProcessErrorKind.NOT_FOUND)

    @patch("tasks.process.subprocess.run")
    def test_reports_timeout_without_arguments(self, run):
        run.side_effect = subprocess.TimeoutExpired(["gh", "secret-token"], 2)
        with self.assertRaises(ProcessError) as raised:
            run_text(["gh", "secret-token"], timeout=2)
        self.assertEqual(raised.exception.kind, ProcessErrorKind.TIMEOUT)
        self.assertNotIn("secret-token", str(raised.exception))

    @patch("tasks.process.subprocess.run")
    def test_redacts_credentials_from_failure(self, run):
        run.return_value = Mock(
            returncode=1,
            stdout="",
            stderr="Authorization: Bearer abc123",
        )
        with self.assertRaises(ProcessError) as raised:
            run_text(["gh", "api"])
        self.assertIn("[REDACTED]", str(raised.exception))
        self.assertNotIn("abc123", str(raised.exception))

    @patch("tasks.process.run_text", return_value='{"items": [1]}')
    def test_parses_json(self, _run):
        self.assertEqual(run_json(["gh", "issue", "list"]), {"items": [1]})

    @patch("tasks.process.run_text", return_value="not json")
    def test_reports_invalid_json_without_output(self, _run):
        with self.assertRaises(ProcessError) as raised:
            run_json(["gh", "issue", "list"])
        self.assertEqual(raised.exception.kind, ProcessErrorKind.INVALID_JSON)
        self.assertNotIn("not json", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
