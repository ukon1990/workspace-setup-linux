"""Headless checks for the available-work browser controls."""

import unittest

from tasks.filters import WorkFilter
from tasks.models import BackendIdentity, TaskSummary
from tasks.tui.app import TasksApp
from tasks.tui.logic import TasksController, set_filter
from tasks.tui.pulls import PullsController
from tasks.tui.screens import ListScreen, WorkFilterModal
from textual.widgets import DataTable, OptionList, Static, Tree


def identity(number):
    return BackendIdentity.github(number, "owner/repo")


class ViewBackend:
    backend_label = "GitHub"
    scope_label = "owner/repo"


class WorkViewTests(unittest.TestCase):
    def make_app(self, tasks, **kwargs):
        controller = TasksController(ViewBackend(), **kwargs)
        return TasksApp(
            controller,
            PullsController(None),
            initial_tasks=tasks,
            load_list_on_mount=False,
        )

    def test_picker_cancel_available_ready_only_and_tree_match_table(self):
        parent = TaskSummary(identity(1), "Feature", "OPEN")
        child = TaskSummary(identity(2), "Ready child", "In Progress", parent=parent.identity)
        done = TaskSummary(identity(3), "Done child", "CLOSED", parent=parent.identity)
        blocker = TaskSummary(identity(4), "Blocked", "OPEN", blocked_by=(parent.identity,))
        saved = []
        app = self.make_app([parent, child, done, blocker], on_work_filter_change=saved.append)

        async def run(pilot):
            await pilot.pause()
            screen = app.screen
            set_filter(screen.state, "Ready child")
            screen._populate_view()
            screen._update_chrome()
            await pilot.press("w")
            self.assertIsInstance(app.screen, WorkFilterModal)
            self.assertEqual(app.screen.query_one(OptionList).highlighted, 0)
            await pilot.press("escape")
            self.assertIsInstance(app.screen, ListScreen)
            self.assertEqual(saved, [])
            await pilot.press("w", "down", "enter")
            await pilot.pause()
            self.assertEqual(screen.state.work_filter, WorkFilter.AVAILABLE)
            table = screen.query_one(DataTable)
            self.assertEqual(table.row_count, 2)
            self.assertEqual(
                {str(key.value) for key in table.rows},
                {parent.identity.stable_id, child.identity.stable_id},
            )
            self.assertEqual(table.get_row(child.identity.stable_id)[2:4], ["Ready", 0])
            await pilot.press("t")
            tree = screen.query_one(Tree)
            self.assertEqual(len(tree.root.children), 1)
            self.assertEqual(tree.root.children[0].data, parent.identity)
            self.assertEqual(tree.root.children[0].children[0].data, child.identity)
            self.assertIn("Ready", str(tree.root.children[0].label))
            self.assertIn("1/2 50%", str(tree.root.children[0].label))
            await pilot.press("w")
            self.assertEqual(app.screen.query_one(OptionList).highlighted, 1)
            await pilot.press("down", "enter")
            await pilot.pause()
            self.assertEqual(screen.state.work_filter, WorkFilter.READY_ONLY)
            self.assertEqual(len(tree.root.children), 1)
            self.assertEqual(tree.root.children[0].data, child.identity)
            await pilot.press("t")
            self.assertEqual(table.row_count, 1)
            self.assertEqual(table.get_row(child.identity.stable_id)[2], "Ready")
            self.assertIn("1 ready", str(screen.query_one("#status-bar", Static).content))
            self.assertEqual(saved, [WorkFilter.AVAILABLE, WorkFilter.READY_ONLY])
            await pilot.press("q")

        app.run(headless=True, auto_pilot=run)

    def test_unknown_empty_mode_and_pr_picker_noop(self):
        unknown = TaskSummary(identity(1), "Unknown", "OPEN", dependencies_complete=False)
        app = self.make_app([unknown])

        async def run(pilot):
            await pilot.pause()
            screen = app.screen
            self.assertIn("1 unknown", str(screen.query_one("#status-bar", Static).content))
            await pilot.press("w", "down", "down", "enter")
            await pilot.pause()
            self.assertEqual(screen.query_one(DataTable).row_count, 0)
            self.assertTrue(screen.query_one("#empty-message", Static).display)
            self.assertIn(
                "No available work", str(screen.query_one("#empty-message", Static).content)
            )
            await pilot.press("t")
            self.assertFalse(screen.query_one(Tree).display)
            self.assertTrue(screen.query_one("#empty-message", Static).display)
            screen._active_tab = "pulls"
            screen.action_work_filter()
            self.assertIs(app.screen, screen)
            await pilot.press("q")

        app.run(headless=True, auto_pilot=run)
