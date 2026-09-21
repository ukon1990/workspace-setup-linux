import tempfile
import unittest
from pathlib import Path

from tasks.filters import (
    AssigneeFilter,
    FilterStateError,
    clear_assignee_filter,
    load_assignee_filter,
    save_assignee_filter,
)


class FilterStateTests(unittest.TestCase):
    def temporary_directory(self):
        return tempfile.TemporaryDirectory(dir=Path(__file__).parent)

    def test_missing_file_returns_all_without_warning(self):
        with self.temporary_directory() as directory:
            result = load_assignee_filter("jira:PROJECT", Path(directory) / "filters.yaml")

        self.assertEqual(result.selection, AssigneeFilter.ALL)
        self.assertIsNone(result.warning)

    def test_saves_and_loads_each_option(self):
        with self.temporary_directory() as directory:
            path = Path(directory) / "state" / "filters.yaml"
            for option in AssigneeFilter:
                with self.subTest(option=option):
                    save_assignee_filter("jira:PROJECT", option, path)
                    result = load_assignee_filter("jira:PROJECT", path)
                    self.assertEqual(result.selection, option)
                    self.assertIsNone(result.warning)

            self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_preserves_other_scopes_and_clear_removes_only_one(self):
        with self.temporary_directory() as directory:
            path = Path(directory) / "filters.yaml"
            save_assignee_filter("jira:PROJECT", AssigneeFilter.ME, path)
            save_assignee_filter("github:owner/repo", AssigneeFilter.UNASSIGNED, path)

            clear_assignee_filter("jira:PROJECT", path)

            self.assertEqual(
                load_assignee_filter("jira:PROJECT", path).selection,
                AssigneeFilter.ALL,
            )
            self.assertEqual(
                load_assignee_filter("github:owner/repo", path).selection,
                AssigneeFilter.UNASSIGNED,
            )

    def test_corrupt_state_warns_and_is_not_overwritten(self):
        with self.temporary_directory() as directory:
            path = Path(directory) / "filters.yaml"
            original = "scopes: [not, a, mapping]\n"
            path.write_text(original, encoding="utf-8")

            result = load_assignee_filter("jira:PROJECT", path)

            self.assertEqual(result.selection, AssigneeFilter.ALL)
            self.assertIn("must be a mapping", result.warning)
            with self.assertRaises(FilterStateError):
                save_assignee_filter("jira:PROJECT", AssigneeFilter.ME, path)
            self.assertEqual(path.read_text(encoding="utf-8"), original)

    def test_rejects_invalid_scope_and_selection(self):
        with self.temporary_directory() as directory:
            path = Path(directory) / "filters.yaml"
            for scope in ("jira:project", "github:owner", "other:value", ""):
                with self.subTest(scope=scope), self.assertRaises(FilterStateError):
                    load_assignee_filter(scope, path)
            with self.assertRaisesRegex(FilterStateError, "assignee filter"):
                save_assignee_filter("jira:PROJECT", "mine", path)

    def test_labels_are_concise_and_distinct(self):
        labels = [option.label for option in AssigneeFilter]
        self.assertEqual(len(labels), len(set(labels)))
        self.assertTrue(all(label and len(label) <= 20 for label in labels))


if __name__ == "__main__":
    unittest.main()
