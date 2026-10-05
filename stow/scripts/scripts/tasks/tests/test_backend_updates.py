"""Scope-wide update feeds, pagination and checkpoint safety."""

import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from tasks.config import JiraConfig
from tasks.github import GithubBackend, GithubError, _normalize_summary
from tasks.jira import JiraBackend, JiraError, _summary
from tasks.models import UpdateBatch
from tasks.process import ProcessError, ProcessErrorKind

SINCE = "2026-10-05T10:11:12+02:00"
UPDATED = "2026-10-05T08:15:00Z"


def gh_row(number, **updates):
    row = {
        "number": number,
        "title": f"Work {number}",
        "state": "open",
        "assignees": [{"login": "other"}],
        "labels": [{"name": "ready"}],
        "html_url": f"https://github.com/owner/repo/issues/{number}",
        "updated_at": UPDATED,
    }
    row.update(updates)
    return row


def gh_page(rows, total=None, incomplete=False):
    return {
        "items": rows,
        "total_count": len(rows) if total is None else total,
        "incomplete_results": incomplete,
    }


def jira_row(key, **updates):
    fields = {
        "summary": "Work",
        "status": {"name": "Released", "statusCategory": {"key": "done"}},
        "issuelinks": [],
        "updated": UPDATED,
    }
    fields.update(updates)
    return {"key": key, "fields": fields}


class GithubUpdateTests(unittest.TestCase):
    @patch("tasks.backend_updates.run_json")
    def test_scope_feed_ignores_browser_filters_and_includes_closed(self, run):
        run.return_value = gh_page([gh_row(1, state="closed")])
        backend = GithubBackend(repository="different/repo", search="assignee:me", limit=1)
        batch = backend.list_updates("github:owner/repo", SINCE)
        self.assertIsInstance(batch, UpdateBatch)
        self.assertTrue(batch.complete)
        self.assertEqual(batch.items[0].identity.repository, "owner/repo")
        self.assertTrue(batch.items[0].completed)
        self.assertEqual(batch.items[0].updated_at, UPDATED)
        self.assertFalse(batch.items[0].dependencies_complete)
        argv = run.call_args.args[0]
        self.assertIn("q=repo:owner/repo is:issue updated:>=2026-10-05T08:06:12Z", argv)
        self.assertFalse(any("assignee" in token for token in argv))
        self.assertNotIn("--limit", argv)

    @patch("tasks.backend_updates.run_json")
    def test_fetches_multiple_pages_and_deduplicates(self, run):
        run.side_effect = [
            gh_page([gh_row(i) for i in range(1, 101)], total=101),
            gh_page([gh_row(101)], total=101),
        ]
        batch = GithubBackend().list_updates("github:owner/repo", SINCE)
        self.assertEqual(len(batch.items), 101)
        self.assertTrue(batch.complete)
        self.assertEqual(run.call_count, 2)
        self.assertIn("page=2", run.call_args.args[0])

    @patch("tasks.backend_updates.run_json")
    def test_search_cap_does_not_claim_complete(self, run):
        run.side_effect = [
            gh_page([gh_row(i) for i in range(start, start + 100)], total=1001)
            for start in range(1, 1001, 100)
        ]
        batch = GithubBackend().list_updates("github:owner/repo", SINCE)
        self.assertFalse(batch.complete)
        self.assertEqual(len(batch.items), 1000)
        self.assertEqual(run.call_count, 10)

    @patch("tasks.backend_updates.run_json")
    def test_incomplete_results_short_pages_duplicates_and_missing_timestamps(self, run):
        for payload in (
            gh_page([gh_row(1)], total=2),
            gh_page([gh_row(1)], incomplete=True),
            gh_page([gh_row(1), gh_row(1)]),
            gh_page([gh_row(1, updated_at=None)]),
            {"items": []},
        ):
            with self.subTest(payload=payload):
                run.return_value = payload
                self.assertFalse(GithubBackend().list_updates("github:owner/repo", SINCE).complete)

    @patch("tasks.backend_updates.run_json", return_value=gh_page([]))
    def test_empty_feed_complete_and_scope_validation(self, run):
        self.assertTrue(GithubBackend().list_updates("github:owner/repo", SINCE).complete)
        for scope in ("jira:PROJECT", "github:owner", "github:owner/repo is:open"):
            with self.subTest(scope=scope), self.assertRaises(ValueError):
                GithubBackend().list_updates(scope, SINCE)
        with self.assertRaises(ValueError):
            GithubBackend().list_updates("github:owner/repo", "invalid")

    @patch("tasks.backend_updates.run_json")
    def test_failure_or_invalid_response_raises(self, run):
        run.side_effect = ProcessError(ProcessErrorKind.TIMEOUT, "gh", "timed out")
        with self.assertRaises(GithubError):
            GithubBackend().list_updates("github:owner/repo", SINCE)
        run.side_effect = None
        run.return_value = []
        with self.assertRaises(GithubError):
            GithubBackend().list_updates("github:owner/repo", SINCE)

    def test_standard_normalizer_retains_updated_timestamp(self):
        task = _normalize_summary(
            {"number": 1, "state": "OPEN", "updatedAt": UPDATED}, "owner/repo"
        )
        self.assertEqual(task.updated_at, UPDATED)


class JiraUpdateTests(unittest.TestCase):
    @patch("tasks.backend_updates.run_json")
    @patch("tasks.backend_updates.datetime")
    def test_paginated_unfiltered_scope_feed_and_timezone_independent_overlap(self, clock, run):
        clock.fromisoformat.side_effect = datetime.fromisoformat
        clock.now.return_value = datetime(2026, 10, 5, 8, 16, 20, tzinfo=timezone.utc)
        run.return_value = [jira_row("PROJECT-1")]
        backend = JiraBackend(
            JiraConfig(default_project="OTHER", jql_extra="assignee=currentUser()", limit=1)
        )
        batch = backend.list_updates("jira:PROJECT", SINCE)
        self.assertTrue(batch.complete)
        self.assertTrue(batch.items[0].completed)
        self.assertTrue(batch.items[0].dependencies_complete)
        self.assertEqual(batch.items[0].updated_at, UPDATED)
        argv = run.call_args.args[0]
        self.assertEqual(
            argv[argv.index("--jql") + 1],
            'project = "PROJECT" AND updated >= "-11m" ORDER BY updated ASC',
        )
        self.assertIn("--paginate", argv)
        self.assertNotIn("--limit", argv)
        self.assertIn("updated", argv[argv.index("--fields") + 1].split(","))

    @patch("tasks.backend_updates.run_json")
    def test_completeness_metadata_and_missing_timestamps(self, run):
        for payload in (
            {"issues": [jira_row("PROJECT-1")], "total": 2},
            {"issues": [jira_row("PROJECT-1")], "isLast": False},
            {"issues": [], "nextPageToken": "more"},
            {"issues": [], "pagination": {"hasMore": True}},
            {"issues": [], "total": "unknown"},
            [jira_row("PROJECT-1", updated=None)],
        ):
            with self.subTest(payload=payload):
                run.return_value = payload
                self.assertFalse(JiraBackend().list_updates("jira:PROJECT", SINCE).complete)
        run.return_value = {"issues": [jira_row("PROJECT-1")], "total": 1, "isLast": True}
        self.assertTrue(JiraBackend().list_updates("jira:PROJECT", SINCE).complete)
        run.return_value = []
        self.assertTrue(JiraBackend().list_updates("jira:PROJECT", SINCE).complete)

    @patch("tasks.backend_updates.run_json")
    def test_scope_validation_and_failures(self, run):
        for scope in ("github:owner/repo", "jira:lower", "jira:PROJECT OR true"):
            with self.subTest(scope=scope), self.assertRaises(ValueError):
                JiraBackend().list_updates(scope, SINCE)
        with self.assertRaises(ValueError):
            JiraBackend().list_updates("jira:PROJECT", "invalid")
        run.side_effect = ProcessError(ProcessErrorKind.TIMEOUT, "acli", "timed out")
        with self.assertRaises(JiraError):
            JiraBackend().list_updates("jira:PROJECT", SINCE)

    def test_standard_normalizer_retains_updated_timestamp(self):
        self.assertEqual(_summary(jira_row("PROJECT-1")).updated_at, UPDATED)
