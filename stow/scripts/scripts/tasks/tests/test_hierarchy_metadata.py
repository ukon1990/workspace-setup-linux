"""Child inventory completeness, backend lookups and cache migration."""

import tempfile
import unittest
from dataclasses import replace
from unittest.mock import patch

from tasks.cache import CacheEntry, cache_path, load_entry, save_entry
from tasks.config import JiraConfig
from tasks.filters import AssigneeFilter
from tasks.github import _normalize_summary
from tasks.issue_cache import IssueStore, load_store, save_store, store_path
from tasks.jira import JiraBackend, JiraError, _summary
from tasks.models import BackendIdentity, TaskDetail, TaskSummary
from tasks.process import ProcessError, ProcessErrorKind


def gh_summary(children):
    return _normalize_summary(
        {"number": 1, "state": "OPEN", "parent": None, "blockedBy": [], "subIssues": children},
        "owner/repo",
    )


def jira_row(key, parent=None, issue_type=None, **updates):
    fields = {
        "summary": "Child",
        "status": {"name": "Open"},
        "issuelinks": [],
        "subtasks": [],
        "parent": {"key": parent} if parent else None,
        "issuetype": issue_type or {"name": "Story", "subtask": False},
    }
    fields.update(updates)
    return {"key": key, "fields": fields}


class ChildMetadataTests(unittest.TestCase):
    def test_legacy_constructed_summary_remains_known_leaf(self):
        task = TaskSummary(BackendIdentity.jira("PROJECT-1"), "Work", "Open")
        self.assertEqual(task.children, ())
        self.assertTrue(task.children_complete)

    def test_github_full_native_children_and_cross_repository(self):
        task = gh_summary(
            [{"number": 2}, {"number": 3, "url": "https://github.com/other/repo/issues/3"}]
        )
        self.assertTrue(task.children_complete)
        self.assertEqual(
            [child.display_key for child in task.children], ["owner/repo#2", "other/repo#3"]
        )
        self.assertTrue(gh_summary([]).children_complete)
        self.assertTrue(gh_summary({"nodes": [], "totalCount": 0}).children_complete)

    def test_github_missing_truncated_capped_malformed_inventories(self):
        missing = _normalize_summary({"number": 1}, "owner/repo")
        self.assertFalse(missing.children_complete)
        cases = [
            None,
            {},
            [None],
            [{}],
            [{"number": 2}, {"number": 2}],
            {"nodes": [{"number": 2}], "totalCount": 2},
            {"nodes": [], "pageInfo": {"hasNextPage": True}},
            {"nodes": [], "totalCount": "unknown"},
            [{"number": i} for i in range(2, 102)],
        ]
        for inventory in cases:
            with self.subTest(inventory=inventory):
                self.assertFalse(gh_summary(inventory).children_complete)
        nodes = [{"number": i} for i in range(2, 102)]
        self.assertTrue(gh_summary({"nodes": nodes, "totalCount": 100}).children_complete)

    def test_jira_subtasks_do_not_claim_full_story_or_epic_inventory(self):
        task = _summary(jira_row("PROJECT-1", subtasks=[{"key": "PROJECT-2"}]))
        self.assertEqual(task.children, (BackendIdentity.jira("PROJECT-2"),))
        self.assertFalse(task.children_complete)
        self.assertFalse(_summary(jira_row("PROJECT-1")).children_complete)
        self.assertFalse(_summary({"key": "PROJECT-1", "fields": {}}).children_complete)
        leaf = _summary(jira_row("PROJECT-2", issue_type={"name": "Custom", "subtask": True}))
        self.assertTrue(leaf.children_complete)
        malformed = _summary(jira_row("PROJECT-2", issue_type={"subtask": True}, subtasks=[{}]))
        self.assertFalse(malformed.children_complete)


class JiraChildLookupTests(unittest.TestCase):
    @patch("tasks.hierarchy_metadata.run_json")
    def test_batches_unfiltered_all_children_across_requested_parents(self, run):
        run.return_value = [
            jira_row("PROJECT-2", "PROJECT-1"),
            jira_row("OTHER-3", "OTHER-1", status={"name": "Done"}),
        ]
        backend = JiraBackend(
            JiraConfig(default_project="ELSE", jql_extra="assignee=currentUser()", limit=1)
        )
        parents = [BackendIdentity.jira("PROJECT-1"), BackendIdentity.jira("OTHER-1")]
        batch = backend.list_children(parents + parents)
        self.assertTrue(batch.complete)
        self.assertEqual([task.parent for task in batch.items], parents)
        argv = run.call_args.args[0]
        self.assertEqual(
            argv[argv.index("--jql") + 1], "parent IN (PROJECT-1, OTHER-1) ORDER BY key ASC"
        )
        self.assertIn("--paginate", argv)
        self.assertNotIn("--limit", argv)
        fields = argv[argv.index("--fields") + 1].split(",")
        self.assertIn("subtasks", fields)
        self.assertIn("parent", fields)

    @patch("tasks.hierarchy_metadata.run_json")
    def test_empty_leaf_lookup_and_omitted_parent_stamp(self, run):
        backend = JiraBackend()
        self.assertTrue(backend.list_children([]).complete)
        run.assert_not_called()
        run.return_value = []
        self.assertEqual(backend.list_children([BackendIdentity.jira("PROJECT-1")]).items, ())
        run.return_value = [jira_row("PROJECT-2")]
        batch = backend.list_children([BackendIdentity.jira("PROJECT-1")])
        self.assertTrue(batch.complete)
        self.assertEqual(batch.items[0].parent, BackendIdentity.jira("PROJECT-1"))

    @patch("tasks.hierarchy_metadata.run_json")
    def test_truncation_and_ambiguous_or_unrequested_parent_incomplete(self, run):
        parents = [BackendIdentity.jira("PROJECT-1"), BackendIdentity.jira("OTHER-1")]
        for payload in (
            {"issues": [jira_row("PROJECT-2", "PROJECT-1")], "total": 2},
            {"issues": [], "isLast": False},
            [jira_row("PROJECT-2")],
            [jira_row("PROJECT-2", "ELSE-1")],
            [jira_row("PROJECT-2", "PROJECT-1"), jira_row("PROJECT-2", "PROJECT-1")],
        ):
            with self.subTest(payload=payload):
                run.return_value = payload
                self.assertFalse(JiraBackend().list_children(parents).complete)

    @patch("tasks.hierarchy_metadata.run_json")
    def test_invalid_keys_and_errors(self, run):
        for parent in (
            BackendIdentity.github(1, "owner/repo"),
            BackendIdentity.jira("PROJECT-1) OR true"),
        ):
            with self.subTest(parent=parent), self.assertRaises(ValueError):
                JiraBackend().list_children([parent])
        run.side_effect = ProcessError(ProcessErrorKind.TIMEOUT, "acli", "timed out")
        with self.assertRaises(JiraError):
            JiraBackend().list_children([BackendIdentity.jira("PROJECT-1")])


class ChildCacheTests(unittest.TestCase):
    def task(self):
        return replace(gh_summary([{"number": 2}]), children_complete=False)

    def test_overview_child_metadata_roundtrip_and_old_version_ignored(self):
        with tempfile.TemporaryDirectory() as directory:
            task = self.task()
            entry = CacheEntry(
                "2026-10-07T10:00:00Z", None, AssigneeFilter.ALL, {task.identity.stable_id: task}
            )
            save_entry("github:owner/repo", entry, cache_dir=directory)
            loaded = load_entry("github:owner/repo", None, AssigneeFilter.ALL, cache_dir=directory)
            self.assertEqual(loaded.items[task.identity.stable_id], task)
            path = cache_path("github:owner/repo", directory)
            path.write_text(path.read_text().replace("format: 5", "format: 4"))
            self.assertIsNone(
                load_entry("github:owner/repo", None, AssigneeFilter.ALL, cache_dir=directory)
            )

    def test_issue_store_child_metadata_roundtrip_and_old_version_ignored(self):
        with tempfile.TemporaryDirectory() as directory:
            task = self.task()
            store = IssueStore()
            store.put_detail(TaskDetail(task, "Body"))
            save_store("github:owner/repo", store, directory)
            loaded = load_store("github:owner/repo", directory)
            self.assertEqual(loaded.items[task.identity.stable_id], task)
            self.assertEqual(loaded.details[task.identity.stable_id].summary, task)
            path = store_path("github:owner/repo", directory)
            path.write_text(path.read_text().replace("format: 2", "format: 1"))
            self.assertEqual(load_store("github:owner/repo", directory).items, {})
