"""Tests for tasks TUI helpers and controller."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from tasks.filters import AssigneeFilter
from tasks.models import (
    BackendIdentity,
    Comment,
    RelationshipKind,
    TaskDetail,
    TaskRelationship,
    TaskSummary,
)
from tasks.tui import (
    ListState,
    TasksController,
    assignee_filter_for_key,
    assignee_filter_text,
    clip,
    detail_content_lines,
    filter_tasks,
    relationship_line,
    selected_task,
    set_filter,
    task_url,
    wrap_text,
)


def summary(number, title="Task", **kwargs):
    return TaskSummary(
        BackendIdentity.github(number, "owner/repo"),
        title,
        kwargs.pop("status", "OPEN"),
        **kwargs,
    )


def detail(number, *, relationships=()):
    item = summary(number, f"Task {number}", labels=("ui",))
    return TaskDetail(
        item,
        description="First paragraph\n\nSecond paragraph",
        comments=(Comment("alice", "Looks good", "2026-01-02"),),
        relationships=relationships,
    )


class FakeBackend:
    backend_label = "GitHub"
    scope_label = "owner/repo"

    def __init__(self):
        self.tasks = [summary(1, "Alpha"), summary(2, "Beta")]
        self.details = {
            item.identity.stable_id: detail(int(item.identity.key)) for item in self.tasks
        }
        self.list_calls = []
        self.detail_calls = []
        self.failures = set()

    def list_tasks(
        self,
        query=None,
        refresh=False,
        assignee_filter=AssigneeFilter.ALL,
    ):
        self.list_calls.append((query, refresh, assignee_filter))
        return self.tasks

    def get_task(self, identity, refresh=False):
        self.detail_calls.append((identity.stable_id, refresh))
        if identity.stable_id in self.failures:
            raise RuntimeError("not available")
        return self.details[identity.stable_id]


class HelperTests(unittest.TestCase):
    def test_assignee_filter_labels_and_keys(self):
        expected = {
            "a": (AssigneeFilter.ALL, "all"),
            "m": (AssigneeFilter.ME, "@me"),
            "u": (AssigneeFilter.UNASSIGNED, "unassigned"),
            "o": (AssigneeFilter.ME_OR_UNASSIGNED, "@me-or-unassigned"),
            "d": (AssigneeFilter.ASSIGNED_ANYONE, "assigned"),
        }
        for key, (selection, label) in expected.items():
            with self.subTest(key=key):
                self.assertEqual(assignee_filter_for_key(key), selection)
                self.assertEqual(assignee_filter_for_key(key.upper()), selection)
                self.assertEqual(assignee_filter_text(selection), label)
        self.assertIsNone(assignee_filter_for_key("?"))
        self.assertIsNone(assignee_filter_for_key(1))

    def test_clip_and_wrap_are_bounded(self):
        self.assertEqual(clip("abcdef", 3), "abc")
        self.assertEqual(clip("abc", -1), "")
        self.assertEqual(wrap_text("abcdef\n\nxy", 3), ["abc", "def", "", "xy"])
        self.assertEqual(wrap_text("text", 0), [])

    def test_filter_searches_all_visible_summary_fields(self):
        tasks = [
            summary(
                1,
                "Render panel",
                status="Ready",
                task_type="Bug",
                priority="High",
                assignees=("Alice",),
                labels=("terminal",),
                components=("CLI",),
            )
        ]
        for needle in ("#1", "render", "ready", "bug", "high", "alice", "terminal", "cli"):
            with self.subTest(needle=needle):
                self.assertEqual(filter_tasks(tasks, needle), tasks)
        self.assertEqual(filter_tasks(tasks, "missing"), [])

    def test_filter_resets_index(self):
        state = ListState([summary(i) for i in range(1, 7)], index=4)
        set_filter(state, "Task")
        self.assertEqual(state.index, 0)
        self.assertEqual(selected_task(state).identity.key, "1")

    def test_detail_text_and_relationship_keep_directional_labels(self):
        relation = TaskRelationship(
            RelationshipKind.BLOCKED_BY,
            BackendIdentity.github(8, "owner/repo"),
            "is blocked by",
            "Dependency",
        )
        lines = detail_content_lines(detail(1), 30)
        self.assertIn("Description", lines)
        self.assertIn("Comments", lines)
        self.assertEqual(
            relationship_line(relation),
            "is blocked by: owner/repo#8 — Dependency",
        )

    def test_task_url_prefers_summary_then_identity(self):
        item = summary(1, url="https://example.test/1")
        loaded = TaskDetail(item, description="")
        self.assertEqual(task_url(loaded), "https://example.test/1")
        identity = BackendIdentity.github(2, "owner/repo", url="https://example.test/2")
        self.assertEqual(task_url(None, identity), "https://example.test/2")
        self.assertIsNone(task_url(None, BackendIdentity.github(3, "owner/repo")))


class ControllerTests(unittest.TestCase):
    def test_initial_list_and_refresh_use_protocol_flags(self):
        backend = FakeBackend()
        controller = TasksController(
            backend,
            initial_assignee_filter=AssigneeFilter.ME_OR_UNASSIGNED,
        )
        state = controller.make_list_state(query="ready")
        controller.load_list(state)
        controller.load_list(state, refresh=True)
        self.assertEqual(
            backend.list_calls,
            [
                ("ready", False, AssigneeFilter.ME_OR_UNASSIGNED),
                ("ready", True, AssigneeFilter.ME_OR_UNASSIGNED),
            ],
        )

    def test_structured_filter_reloads_search_and_notifies(self):
        backend = FakeBackend()
        changes = []
        controller = TasksController(backend, on_assignee_filter_change=changes.append)
        state = controller.make_list_state(query="ready")
        controller.load_list(state)

        self.assertTrue(controller.change_assignee_filter(state, AssigneeFilter.ME))
        self.assertEqual(
            backend.list_calls[-1],
            ("ready", False, AssigneeFilter.ME),
        )
        self.assertEqual(changes, [AssigneeFilter.ME])

        self.assertFalse(
            controller.change_assignee_filter(
                state,
                AssigneeFilter.ME,
                reload_if_unchanged=True,
            )
        )
        self.assertEqual(backend.list_calls[-1], ("ready", False, AssigneeFilter.ME))
        self.assertEqual(changes, [AssigneeFilter.ME])

    def test_clear_resets_both_filters_and_only_reloads_structured_change(self):
        backend = FakeBackend()
        changes = []
        controller = TasksController(
            backend,
            initial_assignee_filter=AssigneeFilter.UNASSIGNED,
            on_assignee_filter_change=changes.append,
        )
        state = controller.make_list_state(tasks=backend.tasks)
        state.filter_text = "alpha"

        self.assertTrue(controller.clear_filters(state))
        self.assertEqual(state.filter_text, "")
        self.assertEqual(state.assignee_filter, AssigneeFilter.ALL)
        self.assertEqual(
            backend.list_calls,
            [(None, False, AssigneeFilter.ALL)],
        )
        self.assertEqual(changes, [AssigneeFilter.ALL])

        state.filter_text = "beta"
        self.assertFalse(controller.clear_filters(state))
        self.assertEqual(state.filter_text, "")
        self.assertEqual(len(backend.list_calls), 1)
        self.assertEqual(changes, [AssigneeFilter.ALL, AssigneeFilter.ALL])

    def test_filter_reload_and_callback_errors_keep_state(self):
        class FailingBackend(FakeBackend):
            def list_tasks(
                self,
                query=None,
                refresh=False,
                assignee_filter=AssigneeFilter.ALL,
            ):
                self.list_calls.append((query, refresh, assignee_filter))
                raise RuntimeError("offline")

        backend = FailingBackend()

        def fail_to_persist(_selection):
            raise RuntimeError("cannot persist")

        controller = TasksController(
            backend,
            on_assignee_filter_change=fail_to_persist,
        )
        state = controller.make_list_state(tasks=backend.tasks)
        self.assertTrue(controller.change_assignee_filter(state, AssigneeFilter.ME))
        self.assertEqual(state.assignee_filter, AssigneeFilter.ME)
        self.assertEqual(state.tasks, backend.tasks)
        self.assertEqual(state.error, "offline; cannot persist")

    def test_details_are_loaded_lazily_and_cached(self):
        backend = FakeBackend()
        controller = TasksController(backend)
        identity = backend.tasks[0].identity
        first, error = controller.load_detail(identity)
        self.assertIsNone(error)
        self.assertEqual(first.summary.title, "Task 1")
        self.assertEqual(backend.detail_calls, [("github:owner/repo:1", False)])
        second, error = controller.load_detail(identity)
        self.assertIs(first, second)
        self.assertEqual(backend.detail_calls, [("github:owner/repo:1", False)])

    def test_refresh_replaces_cached_detail(self):
        backend = FakeBackend()
        controller = TasksController(backend)
        identity = backend.tasks[0].identity
        controller.load_detail(identity)
        controller.load_detail(identity, refresh=True)
        self.assertEqual(
            backend.detail_calls,
            [("github:owner/repo:1", False), ("github:owner/repo:1", True)],
        )

    def test_failed_relationship_fetch_is_retryable(self):
        target = BackendIdentity.github(2, "owner/repo")
        backend = FakeBackend()
        controller = TasksController(backend)
        backend.failures.add(target.stable_id)

        detail, error = controller.load_detail(target)
        self.assertIsNone(detail)
        self.assertEqual(error, "not available")

        backend.failures.clear()
        detail, error = controller.load_detail(target)
        self.assertIsNone(error)
        self.assertEqual(detail.identity, target)
        self.assertEqual(
            backend.detail_calls[-2:],
            [("github:owner/repo:2", False), ("github:owner/repo:2", False)],
        )

    def test_search_list_state_keeps_assignee_filter(self):
        backend = FakeBackend()
        controller = TasksController(
            backend,
            initial_assignee_filter=AssigneeFilter.ME,
        )
        state = controller.make_list_state(query="backend query")
        controller.load_list(state)
        self.assertEqual(state.query, "backend query")
        self.assertEqual(state.assignee_filter, AssigneeFilter.ME)
        self.assertEqual(
            backend.list_calls[-1],
            ("backend query", False, AssigneeFilter.ME),
        )

    def test_list_error_and_empty_results_remain_refreshable(self):
        class FailingBackend(FakeBackend):
            def list_tasks(
                self,
                query=None,
                refresh=False,
                assignee_filter=AssigneeFilter.ALL,
            ):
                raise RuntimeError("offline")

        controller = TasksController(FailingBackend())
        state = controller.make_list_state()
        controller.load_list(state)
        self.assertEqual(state.error, "offline")
        self.assertEqual(state.tasks, [])


class AppSmokeTests(unittest.TestCase):
    def test_list_to_detail_and_back(self):
        from tasks.tui.app import TasksApp

        backend = FakeBackend()
        controller = TasksController(backend)
        app = TasksApp(
            controller,
            initial_tasks=backend.tasks,
            load_list_on_mount=False,
        )

        async def run_pilot(pilot):
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()
            from tasks.tui.screens import DetailScreen, ListScreen

            self.assertIsInstance(app.screen, DetailScreen)
            await pilot.press("h")
            await pilot.pause()
            self.assertIsInstance(app.screen, ListScreen)
            await pilot.press("q")

        app.run(headless=True, auto_pilot=run_pilot)

    def test_open_url_uses_webbrowser(self):
        from tasks.tui.app import TasksApp

        backend = FakeBackend()
        backend.tasks = [summary(1, "Alpha", url="https://example.test/issue/1")]
        backend.details = {
            backend.tasks[0].identity.stable_id: TaskDetail(backend.tasks[0], description="")
        }
        controller = TasksController(backend)
        app = TasksApp(
            controller,
            initial_identity=backend.tasks[0].identity,
            load_list_on_mount=False,
        )

        opened = []

        async def run_pilot(pilot):
            await pilot.pause()
            await pilot.press("o")
            await pilot.pause()
            self.assertEqual(opened, ["https://example.test/issue/1"])
            await pilot.press("q")

        with patch("tasks.tui.screens.webbrowser.open", side_effect=opened.append):
            app.run(headless=True, auto_pilot=run_pilot)


if __name__ == "__main__":
    unittest.main()
