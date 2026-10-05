"""Adapter metadata, cache and persisted work-filter coverage."""

import tempfile
import unittest
from pathlib import Path

from tasks.cache import CacheEntry, load_entry, save_entry
from tasks.filters import (
    AssigneeFilter,
    FilterStateError,
    WorkFilter,
    clear_assignee_filter,
    clear_work_filter,
    load_assignee_filter,
    load_work_filter,
    save_assignee_filter,
    save_work_filter,
)
from tasks.github import _normalize_summary
from tasks.jira import _summary


class WorkMetadataTests(unittest.TestCase):
    def github(self, **updates):
        issue = {
            "number": 1,
            "title": "Work",
            "state": "OPEN",
            "parent": None,
            "blockedBy": [],
            "blocking": [],
        }
        issue.update(updates)
        return _normalize_summary(issue, "owner/repo")

    def jira(self, **updates):
        fields = {
            "summary": "Work",
            "status": {"name": "Review", "statusCategory": {"key": "indeterminate"}},
            "parent": None,
            "issuelinks": [],
        }
        fields.update(updates)
        return _summary({"key": "PROJECT-1", "fields": fields})

    def test_native_completion(self):
        self.assertFalse(self.github().completed)
        self.assertTrue(self.github(state="CLOSED", stateReason="NOT_PLANNED").completed)
        self.assertIsNone(self.github(state="UNKNOWN").completed)
        self.assertFalse(self.jira().completed)
        self.assertTrue(
            self.jira(status={"name": "Released", "statusCategory": {"key": "done"}}).completed
        )
        self.assertIsNone(self.jira(status={"name": "Done"}).completed)

    def test_github_complete_and_truncated_dependencies(self):
        self.assertTrue(self.github().dependencies_complete)
        for value in (
            None,
            {"nodes": [], "totalCount": 1},
            {"nodes": [], "pageInfo": {"hasNextPage": True}},
            [{}],
            [None],
        ):
            with self.subTest(value=value):
                self.assertFalse(self.github(blockedBy=value).dependencies_complete)
        self.assertTrue(
            self.github(blockedBy={"nodes": [{"number": 2}], "totalCount": 1}).dependencies_complete
        )
        self.assertFalse(self.github(parent=[]).dependencies_complete)
        missing = _normalize_summary({"number": 1, "state": "OPEN"}, "owner/repo")
        self.assertFalse(missing.dependencies_complete)

    def test_jira_missing_or_malformed_dependencies(self):
        self.assertTrue(self.jira().dependencies_complete)
        self.assertFalse(self.jira(issuelinks=None).dependencies_complete)
        self.assertFalse(self.jira(issuelinks=[{}]).dependencies_complete)
        self.assertFalse(self.jira(parent={}).dependencies_complete)
        self.assertFalse(
            self.jira(
                issuelinks=[{"type": {}, "inwardIssue": {"key": "OTHER-1"}}]
            ).dependencies_complete
        )
        self.assertTrue(
            self.jira(
                issuelinks=[
                    {"type": {"inward": "is blocked by"}, "inwardIssue": {"key": "OTHER-1"}}
                ]
            ).dependencies_complete
        )
        self.assertTrue(
            _summary(
                {"key": "PROJECT-1", "fields": {"status": "Open", "issuelinks": []}}
            ).dependencies_complete
        )

    def test_cache_round_trip_retains_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            task = self.github(state="CLOSED", blockedBy=None)
            entry = CacheEntry(
                "2026-10-05T00:00:00+00:00",
                None,
                AssigneeFilter.ALL,
                {task.identity.stable_id: task},
            )
            save_entry("github:owner/repo", entry, cache_dir=directory)
            loaded = load_entry("github:owner/repo", None, AssigneeFilter.ALL, cache_dir=directory)
            self.assertEqual(loaded.items[task.identity.stable_id], task)


class WorkFilterTests(unittest.TestCase):
    def test_each_option_and_backward_compatibility(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "filters.yaml"
            path.write_text("scopes:\n  jira:PROJECT:\n    assignee: me\n")
            self.assertEqual(load_work_filter("jira:PROJECT", path).selection, WorkFilter.ALL)
            for option in WorkFilter:
                save_work_filter("jira:PROJECT", option, path)
                self.assertEqual(load_work_filter("jira:PROJECT", path).selection, option)
                self.assertEqual(
                    load_assignee_filter("jira:PROJECT", path).selection, AssigneeFilter.ME
                )

    def test_saving_and_clearing_preserve_other_filter(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "filters.yaml"
            save_work_filter("jira:PROJECT", WorkFilter.AVAILABLE, path)
            save_work_filter("github:owner/repo", WorkFilter.READY_ONLY, path)
            save_assignee_filter("jira:PROJECT", AssigneeFilter.ME, path)
            clear_assignee_filter("jira:PROJECT", path)
            self.assertEqual(load_work_filter("jira:PROJECT", path).selection, WorkFilter.AVAILABLE)
            save_assignee_filter("jira:PROJECT", AssigneeFilter.ME, path)
            clear_work_filter("jira:PROJECT", path)
            self.assertEqual(
                load_assignee_filter("jira:PROJECT", path).selection, AssigneeFilter.ME
            )
            self.assertEqual(
                load_work_filter("github:owner/repo", path).selection, WorkFilter.READY_ONLY
            )
            clear_assignee_filter("jira:PROJECT", path)
            self.assertNotIn("jira:PROJECT", path.read_text())
            clear_work_filter("github:owner/repo", path)
            self.assertFalse(path.exists())

    def test_invalid_selection_and_state(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "filters.yaml"
            with self.assertRaises(FilterStateError):
                save_work_filter("jira:PROJECT", "ready", path)
            path.write_text("scopes:\n  jira:PROJECT:\n    work: invalid\n")
            result = load_work_filter("jira:PROJECT", path)
            self.assertEqual(result.selection, WorkFilter.ALL)
            self.assertIn("work filter", result.warning)
