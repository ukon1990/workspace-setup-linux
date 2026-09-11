import io
import json
import os
import sys
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from collect import filter_writable_repos, parse_artifacts
from delete import confirm_and_delete
from overview import print_overview
from tui import format_row
from util import age_cutoff


class CollectTests(unittest.TestCase):
    def test_filter_mine_only(self):
        repos = [
            {"owner": {"login": "alice"}, "permissions": {"push": True}},
            {"owner": {"login": "org"}, "permissions": {"push": True}},
        ]
        result = filter_writable_repos(repos, "alice", "mine", "")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["owner"]["login"], "alice")

    def test_filter_owner_missing_repos(self):
        repos = [{"owner": {"login": "other"}, "permissions": {"push": True}}]
        with self.assertRaises(ValueError):
            filter_writable_repos(repos, "alice", "owner", "missing")

    def test_parse_artifacts_counts_old(self):
        cutoff = age_cutoff(7)
        raw = [
            {"id": 1, "name": "old", "size_in_bytes": 10, "created_at": "2020-01-01T00:00:00Z"},
            {"id": 2, "name": "new", "size_in_bytes": 20, "created_at": "2099-01-01T00:00:00Z"},
        ]
        parsed, total, old_count, old_size = parse_artifacts(raw, cutoff)
        self.assertEqual(len(parsed), 2)
        self.assertEqual(old_count, 1)
        self.assertEqual(old_size, 10)
        self.assertEqual(total, 30)


class OverviewTests(unittest.TestCase):
    def test_print_overview(self):
        fixture = os.path.join(os.path.dirname(__file__), "fixtures", "sample_data.json")
        buf = io.StringIO()
        with redirect_stdout(buf):
            print_overview(fixture, 7)
        out = buf.getvalue()
        self.assertIn("alice/big-repo", out)
        self.assertIn("Scope:", out)


class DeleteTests(unittest.TestCase):
    def test_aborts_without_yes(self):
        fixture = os.path.join(os.path.dirname(__file__), "fixtures", "sample_data.json")
        with patch("delete.preview_delete", return_value=[("alice/big-repo", 1, "a.zip")]):
            code = confirm_and_delete(
                fixture,
                {"alice/big-repo"},
                True,
                7,
                input_func=lambda _prompt: "no",
                sleep_func=lambda _s: None,
            )
        self.assertEqual(code, 0)

    @patch("delete.subprocess.run")
    def test_deletes_when_confirmed(self, mock_run):
        fixture = os.path.join(os.path.dirname(__file__), "fixtures", "sample_data.json")
        mock_run.return_value.returncode = 0
        code = confirm_and_delete(
            fixture,
            {"alice/small-repo"},
            True,
            7,
            input_func=lambda _prompt: "yes",
            sleep_func=lambda _s: None,
        )
        self.assertEqual(code, 0)
        mock_run.assert_called_once()


class TuiFormatTests(unittest.TestCase):
    def test_format_row_marks_current_and_selected(self):
        repo = {
            "full_name": "alice/repo",
            "owner": "alice",
            "artifact_count": 2,
            "total_size": 1024,
            "old_count": 1,
        }
        line = format_row(
            repo,
            current_user="alice",
            is_current=True,
            is_selected=True,
            age_filter=True,
            age_limit_days=7,
            width=100,
        )
        self.assertIn(">", line)
        self.assertIn("[x]", line)
        self.assertIn("*", line)


if __name__ == "__main__":
    unittest.main()
