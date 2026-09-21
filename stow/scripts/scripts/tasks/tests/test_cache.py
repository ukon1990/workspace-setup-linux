"""Tests for the incremental task list disk cache."""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from tasks.cache import (
    CacheEntry,
    format_github_since,
    format_jira_since,
    load_entry,
    save_entry,
    utc_now_iso,
)
from tasks.filters import AssigneeFilter
from tasks.github import GithubBackend
from tasks.models import BackendIdentity, TaskSummary
from tasks.tui import TasksController


def _summary(number, title="Task", status="Open", parent=None, blocked_by=(), blocks=()):
    return TaskSummary(
        BackendIdentity.github(number, "acme/app"),
        title,
        status,
        parent=parent,
        blocked_by=tuple(blocked_by),
        blocks=tuple(blocks),
    )


class CacheRoundTripTests(unittest.TestCase):
    def test_save_load_and_merge(self):
        with TemporaryDirectory() as directory:
            scope = "github:acme/app"
            cache_dir = Path(directory)
            first = _summary(1, "Alpha")
            entry = CacheEntry(
                synced_at="2026-09-21T10:00:00+00:00",
                query=None,
                assignee=AssigneeFilter.ALL,
            )
            entry.replace_items([first])
            save_entry(scope, entry, cache_dir=cache_dir)

            loaded = load_entry(scope, None, AssigneeFilter.ALL, cache_dir=cache_dir)
            self.assertIsNotNone(loaded)
            self.assertEqual(loaded.synced_at, "2026-09-21T10:00:00+00:00")
            self.assertEqual(loaded.items[first.identity.stable_id].title, "Alpha")

            updated = _summary(1, "Alpha edited", status="Closed")
            child = _summary(
                2,
                "Child",
                parent=first.identity,
                blocked_by=(first.identity,),
                blocks=(BackendIdentity.github(9, "acme/app"),),
            )
            loaded.merge_items([updated, child])
            loaded.synced_at = utc_now_iso()
            save_entry(scope, loaded, cache_dir=cache_dir)

            again = load_entry(scope, None, AssigneeFilter.ALL, cache_dir=cache_dir)
            self.assertEqual(again.items[first.identity.stable_id].status, "Closed")
            self.assertEqual(again.items[child.identity.stable_id].parent, first.identity)
            self.assertEqual(
                again.items[child.identity.stable_id].blocked_by[0].key,
                "1",
            )
            self.assertEqual(again.items[child.identity.stable_id].blocks[0].key, "9")
            self.assertNotEqual(again.synced_at, "2026-09-21T10:00:00+00:00")

    def test_outdated_format_is_ignored(self):
        with TemporaryDirectory() as directory:
            scope = "github:acme/app"
            cache_dir = Path(directory)
            entry = CacheEntry(
                synced_at="2026-09-21T10:00:00+00:00",
                query=None,
                assignee=AssigneeFilter.ALL,
            )
            entry.replace_items([_summary(1, "Alpha")])
            save_entry(scope, entry, cache_dir=cache_dir)
            path = cache_dir / "github-acme-app.yaml"
            raw = path.read_text(encoding="utf-8")
            path.write_text(raw.replace("format: 2", "format: 1"), encoding="utf-8")
            self.assertIsNone(load_entry(scope, None, AssigneeFilter.ALL, cache_dir=cache_dir))

    def test_format_since_helpers(self):
        self.assertEqual(format_github_since("2026-09-21T18:30:00+00:00"), "2026-09-21")
        self.assertEqual(format_jira_since("2026-09-21T18:30:00+00:00"), "2026-09-21 18:30")


class IncrementalControllerTests(unittest.TestCase):
    def test_warm_refresh_requests_delta_only(self):
        class RecordingBackend:
            backend_label = "GitHub"
            scope_label = "acme/app"

            def __init__(self):
                self.calls = []

            def list_tasks(self, query=None, refresh=False, assignee_filter=AssigneeFilter.ALL, **kwargs):
                self.calls.append((query, refresh, assignee_filter, kwargs))
                if kwargs.get("updated_since"):
                    return (_summary(1, "Updated", status="Closed"),)
                return (_summary(1, "Seed"), _summary(2, "Other"))

            def get_task(self, identity, refresh=False):
                raise AssertionError("unexpected detail fetch")

        with TemporaryDirectory() as directory:
            backend = RecordingBackend()
            controller = TasksController(
                backend,
                cache_scope="github:acme/app",
                cache_dir=directory,
            )
            state = controller.make_list_state()
            controller.load_list(state, full=True)
            self.assertEqual(len(state.tasks), 2)
            self.assertEqual(backend.calls[-1][3].get("include_closed"), False)

            controller.load_list(state, refresh=True, full=False)
            kwargs = backend.calls[-1][3]
            self.assertTrue(kwargs.get("include_closed"))
            self.assertIn("updated_since", kwargs)
            self.assertEqual(controller.cached_items["github:acme/app:1"].status, "Closed")
            # Default open presentation hides closed seed when no query.
            self.assertEqual(len(state.tasks), 1)
            self.assertEqual(state.tasks[0].identity.key, "2")


class GithubParentListTests(unittest.TestCase):
    @patch("tasks.github.run_json")
    def test_list_includes_parent_field_and_normalizes(self, run_json):
        run_json.return_value = [
            {
                "number": 4,
                "title": "Child",
                "state": "OPEN",
                "assignees": [],
                "labels": [],
                "url": "https://github.com/acme/app/issues/4",
                "parent": {
                    "number": 2,
                    "title": "Parent",
                    "url": "https://github.com/acme/app/issues/2",
                },
                "blockedBy": {
                    "nodes": [
                        {
                            "number": 5,
                            "title": "Blocker",
                            "url": "https://github.com/acme/app/issues/5",
                        }
                    ],
                    "totalCount": 1,
                },
                "blocking": {
                    "nodes": [
                        {
                            "number": 6,
                            "title": "Blocked",
                            "url": "https://github.com/acme/app/issues/6",
                        }
                    ],
                    "totalCount": 1,
                },
            }
        ]
        issues = GithubBackend("acme/app").list_issues()
        self.assertEqual(issues[0].parent.key, "2")
        self.assertEqual([item.key for item in issues[0].blocked_by], ["5"])
        self.assertEqual([item.key for item in issues[0].blocks], ["6"])
        fields = run_json.call_args.args[0][run_json.call_args.args[0].index("--json") + 1]
        self.assertIn("parent", fields.split(","))
        self.assertIn("blockedBy", fields.split(","))
        self.assertIn("blocking", fields.split(","))

    @patch("tasks.github.run_json", return_value=[])
    def test_delta_list_uses_updated_and_all_state(self, run_json):
        GithubBackend("acme/app").list_issues(
            updated_since="2026-09-21",
            include_closed=True,
        )
        command = run_json.call_args.args[0]
        self.assertEqual(command[command.index("--state") + 1], "all")
        self.assertIn("updated:>=2026-09-21", command[command.index("--search") + 1])


if __name__ == "__main__":
    unittest.main()
