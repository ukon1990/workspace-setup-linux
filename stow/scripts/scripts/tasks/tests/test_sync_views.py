"""Changed markers and scope synchronization in issue screens."""

import unittest

from tasks.models import (
    BackendIdentity,
    RelationshipKind,
    TaskDetail,
    TaskRelationship,
    TaskSummary,
)
from tasks.tui.app import TasksApp
from tasks.tui.logic import TasksController, build_relationship_hierarchy
from tasks.tui.pulls import PullsController
from textual.widgets import DataTable, Static, Tree


def issue(number, repository="other/repo"):
    return TaskSummary(BackendIdentity.github(number, repository), f"Issue {number}", "OPEN")


class Backend:
    backend_label = "GitHub"
    scope_label = "default/repo"


class RecordingController(TasksController):
    """Record screen behavior independently of disk/network synchronization."""

    def __init__(self, details):
        super().__init__(Backend())
        self.details = {detail.identity.stable_id: detail for detail in details}
        self.calls = []
        self.changed_ids = {details[-1].identity.stable_id}
        self.sync_warning = "Sync unavailable; showing cached data"

    @property
    def persistent_sync(self):
        return True

    def scope_for_identity(self, identity):
        return "github:" + identity.repository

    def sync_scope(self, scope=None, *, refresh=False, full=False, on_progress=None):
        self.calls.append(("sync", scope, refresh, full))

    def load_detail(self, identity, *, refresh=False):
        self.calls.append(("detail", identity.stable_id, refresh))
        return self.details[identity.stable_id], None

    def load_list(self, state, *, refresh=False, full=False, on_progress=None):
        self.sync_scope("github:default/repo", refresh=refresh, full=full)
        state.changed_ids = self.changed_ids


class SyncViewTests(unittest.TestCase):
    def test_detail_syncs_target_scope_before_cached_load_and_refresh(self):
        current, blocker = issue(1), issue(2)
        detail = TaskDetail(
            current,
            description="Cached issue description",
            relationships=(
                TaskRelationship(RelationshipKind.BLOCKED_BY, blocker.identity, "blocked by"),
            ),
        )
        controller = RecordingController([detail, TaskDetail(blocker)])
        app = TasksApp(controller, PullsController(None), initial_identity=current.identity)

        async def run(pilot):
            await pilot.pause()
            self.assertEqual(controller.calls[0], ("sync", "github:other/repo", False, False))
            self.assertTrue(all(not call[2] for call in controller.calls if call[0] == "detail"))
            screen = app.screen
            self.assertIsNotNone(screen.detail)
            self.assertIn("1 changed", str(screen.query_one("#status-bar", Static).content))
            self.assertIn(
                "showing cached data", str(screen.query_one("#status-bar", Static).content)
            )
            tree = screen.query_one(Tree)
            linked = tree.root.children[0].children[0]
            self.assertIn(blocker.display_key + "*", str(linked.label))
            self.assertEqual(linked.data, blocker.identity)
            controller.calls.clear()
            await pilot.press("r")
            await pilot.pause()
            self.assertEqual(controller.calls[0], ("sync", "github:other/repo", True, False))
            self.assertTrue(all(not call[2] for call in controller.calls if call[0] == "detail"))
            controller.calls.clear()
            await pilot.press("R")
            await pilot.pause()
            self.assertEqual(controller.calls[0], ("sync", "github:other/repo", True, True))
            self.assertTrue(all(not call[2] for call in controller.calls if call[0] == "detail"))
            await pilot.press("q")

        app.run(headless=True, auto_pilot=run)

    def test_seeded_list_syncs_before_display_and_changed_column_preserves_identity(self):
        first, second = issue(1, "default/repo"), issue(2, "default/repo")
        controller = RecordingController([TaskDetail(first), TaskDetail(second)])
        app = TasksApp(
            controller,
            PullsController(None),
            initial_tasks=[first, second],
            load_list_on_mount=False,
        )

        async def run(pilot):
            await pilot.pause()
            self.assertEqual(controller.calls, [("sync", "github:default/repo", False, False)])
            table = app.screen.query_one(DataTable)
            changed_column = list(table.columns).index(
                next(key for key in table.columns if key.value == "changed")
            )
            self.assertEqual(table.get_row(first.identity.stable_id)[changed_column], "")
            self.assertEqual(table.get_row(second.identity.stable_id)[changed_column], "*")
            self.assertEqual(table.get_row(second.identity.stable_id)[0], second.display_key)
            app.screen.state.sort_column = "changed"
            app.screen.state.sort_reverse = True
            app.screen._populate_view()
            self.assertEqual(table.ordered_rows[0].key.value, second.identity.stable_id)
            await pilot.press("t")
            tree = app.screen.query_one(Tree)
            marked = next(node for node in tree.root.children if node.data == second.identity)
            self.assertIn(second.display_key + "*", str(marked.label))
            self.assertIn(
                "showing cached data", str(app.screen.query_one("#status-bar", Static).content)
            )
            await pilot.press("q")

        app.run(headless=True, auto_pilot=run)

    def test_detail_markers_cover_jira_and_github_without_affecting_labels_or_identity(self):
        for target in (issue(1), TaskSummary(BackendIdentity.jira("PROJ-1"), "Issue", "OPEN")):
            with self.subTest(backend=target.identity.backend):
                controller = RecordingController([TaskDetail(target)])
                node = build_relationship_hierarchy(controller, TaskDetail(target))
                self.assertTrue(node.changed)
                self.assertTrue(node.progress_label.startswith("○ "))
                self.assertIn(target.display_key + "* —", node.progress_label)
                self.assertEqual(node.identity, target.identity)
                self.assertEqual(node.title, target.title)
