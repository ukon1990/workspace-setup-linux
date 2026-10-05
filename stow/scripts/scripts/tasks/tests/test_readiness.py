"""Shared work evaluation and supporting-data resolution regressions."""

import tempfile
import unittest
from dataclasses import replace

from tasks.filters import WorkFilter
from tasks.models import BackendIdentity, TaskDetail, TaskSummary
from tasks.readiness import WorkState, evaluate, is_done
from tasks.tui import TasksController, selected_task, set_filter, visible_tasks
from tasks.tui.logic import work_result


def task(number, **kwargs):
    return TaskSummary(
        BackendIdentity.github(number, "owner/repo"),
        f"Task {number}",
        kwargs.pop("status", "Open"),
        **kwargs,
    )


class Backend:
    backend_label = "GitHub"
    scope_label = "owner/repo"
    limit = 100

    def __init__(self, tasks, supporting=()):
        self.tasks = list(tasks)
        self.details = {item.identity.stable_id: TaskDetail(item) for item in supporting}
        self.calls = []

    def list_tasks(self, **kwargs):
        return self.tasks

    def get_task(self, identity, refresh=False):
        self.calls.append((identity.stable_id, refresh))
        return self.details[identity.stable_id]


def ids(tasks):
    return {item.identity.key for item in tasks}


def node_ids(nodes):
    return {node.identity.key for node in nodes} | set().union(
        *(node_ids(node.children) for node in nodes)
    )


class ReadinessTests(unittest.TestCase):
    def result(self, tasks, candidates=None):
        return evaluate(
            {item.identity.stable_id: item for item in tasks},
            tasks if candidates is None else candidates,
        )

    def test_completion_and_direct_blockers(self):
        closed = task(1, status="Released", completed=True)
        ready = task(2, status="In Progress", blocked_by=(closed.identity,))
        blocked = task(3, blocked_by=(ready.identity,))
        unknown = task(4, blocked_by=(task(99).identity,))
        result = self.result([closed, ready, blocked, unknown])
        self.assertTrue(is_done(closed))
        self.assertEqual(
            [result.states[item.identity.stable_id] for item in [closed, ready, blocked, unknown]],
            [WorkState.DONE, WorkState.READY, WorkState.BLOCKED, WorkState.UNKNOWN],
        )

    def test_inherited_blockers_and_known_blocker_over_unknown(self):
        blocker = task(1)
        parent = task(2, blocked_by=(blocker.identity,), dependencies_complete=False)
        child = task(3, parent=parent.identity)
        grandchild = task(4, parent=child.identity)
        result = self.result([blocker, parent, child, grandchild])
        self.assertEqual(result.states[grandchild.identity.stable_id], WorkState.BLOCKED)
        result = self.result([parent, child, grandchild])
        self.assertEqual(result.states[grandchild.identity.stable_id], WorkState.UNKNOWN)

    def test_cycle_and_missing_parent_are_unknown(self):
        first = task(1, parent=task(2).identity)
        second = task(2, parent=first.identity)
        for tasks in ([first], [first, second]):
            self.assertEqual(self.result(tasks).states[first.identity.stable_id], WorkState.UNKNOWN)

    def test_unique_counts_match_candidates_at_every_depth(self):
        parent = task(1)
        child = task(2, parent=parent.identity)
        leaf = task(3, parent=child.identity)
        result = self.result([parent, child, leaf], [leaf, leaf])
        self.assertEqual(result.ready_descendants[parent.identity.stable_id], 1)
        self.assertEqual(result.ready_descendants[child.identity.stable_id], 1)
        self.assertEqual(ids(result.selected("available")), {"1", "2", "3"})
        self.assertEqual(ids(result.selected("ready_only")), {"3"})
        self.assertEqual(ids(result.selected("all")), {"3"})

    def test_modes_views_progress_and_text_filter(self):
        done = task(1, completed=True)
        parent = task(2)
        child = task(3, parent=parent.identity)
        done_child = task(4, parent=parent.identity, completed=True)
        backend = Backend([parent, child], [done])
        controller = TasksController(backend)
        state = controller.make_list_state()
        controller.load_list(state)
        controller.cached_items[done_child.identity.stable_id] = done_child
        state.readiness.items[done_child.identity.stable_id] = done_child
        set_filter(state, "Task 3")
        for mode, expected in [
            (WorkFilter.ALL, {"3"}),
            (WorkFilter.AVAILABLE, {"2", "3"}),
            (WorkFilter.READY_ONLY, {"3"}),
        ]:
            controller.change_work_filter(state, mode)
            self.assertEqual(ids(visible_tasks(state)), expected)
            forest = controller.build_work_forest(state)
            self.assertEqual(node_ids(forest), expected)
            if mode is WorkFilter.AVAILABLE:
                self.assertEqual((forest[0].done_leaves, forest[0].total_leaves), (1, 2))
        state.sort_column = "work"
        self.assertEqual(selected_task(state).identity, child.identity)
        state.sort_column = "ready_descendants"
        self.assertEqual(ids(visible_tasks(state)), {"3"})

    def test_resolved_summary_is_not_overwritten_by_incomplete_list_item(self):
        incomplete = task(1, dependencies_complete=False)
        backend = Backend([incomplete], [replace(incomplete, dependencies_complete=True)])
        controller = TasksController(backend)
        state = controller.make_list_state()
        controller.load_list(state)
        self.assertEqual(work_result(state).states[incomplete.identity.stable_id], WorkState.READY)

    def test_refresh_rechecks_unchanged_issue_and_external_blocker(self):
        blocker = task(1)
        child = task(2, blocked_by=(blocker.identity,))
        backend = Backend([child], [blocker])
        with tempfile.TemporaryDirectory() as directory:
            controller = TasksController(
                backend, cache_scope="github:owner/repo", cache_dir=directory
            )
            state = controller.make_list_state()
            controller.load_list(state)
            self.assertEqual(work_result(state).states[child.identity.stable_id], WorkState.BLOCKED)
            backend.details[blocker.identity.stable_id] = TaskDetail(
                replace(blocker, completed=True)
            )
            controller.load_list(state, refresh=True)
            self.assertEqual(work_result(state).states[child.identity.stable_id], WorkState.READY)
            self.assertIn((blocker.identity.stable_id, True), backend.calls)
            backend.details.clear()
            controller.load_list(state, full=True)
            self.assertEqual(work_result(state).states[child.identity.stable_id], WorkState.UNKNOWN)

    def test_resolution_caps_and_duplicate_support(self):
        blocker = task(1000)
        tasks = [task(i, blocked_by=(blocker.identity,)) for i in range(1, 20)]
        backend = Backend(tasks, [blocker])
        controller = TasksController(backend)
        state = controller.make_list_state()
        controller.load_list(state)
        self.assertEqual(len(backend.calls), 1)
        tasks = [task(i, blocked_by=(task(i + 200).identity,)) for i in range(1, 100)]
        backend = Backend(tasks)
        controller = TasksController(backend)
        state = controller.make_list_state()
        controller.load_list(state)
        self.assertEqual(len(backend.calls), 80)
        self.assertTrue(
            all(value is WorkState.UNKNOWN for value in work_result(state).states.values())
        )
        backend.limit = len(tasks)
        controller.load_list(state)
        self.assertIn("partial", controller.work_status(state))

    def test_incomplete_support_is_fetched_once_even_in_multiple_roles(self):
        incomplete = task(1, dependencies_complete=False)
        dependent = task(2, blocked_by=(incomplete.identity,))
        backend = Backend([incomplete, dependent], [incomplete])
        controller = TasksController(backend)
        state = controller.make_list_state()
        controller.load_list(state, refresh=True)
        self.assertEqual(backend.calls, [(incomplete.identity.stable_id, True)])
        self.assertEqual(
            work_result(state).states[incomplete.identity.stable_id], WorkState.UNKNOWN
        )

    def test_depth_limit_and_filter_persistence_callback(self):
        chain = [task(i, parent=task(i + 1).identity) for i in range(1, 11)]
        backend = Backend([chain[0]], chain[1:])
        saved = []
        controller = TasksController(backend, on_work_filter_change=saved.append)
        state = controller.make_list_state()
        controller.load_list(state)
        self.assertEqual(len(backend.calls), 8)
        self.assertEqual(work_result(state).states[chain[0].identity.stable_id], WorkState.UNKNOWN)
        controller.change_work_filter(state, WorkFilter.AVAILABLE)
        searched = controller.make_list_state(query="new", work_filter=state.work_filter)
        self.assertEqual(searched.work_filter, WorkFilter.AVAILABLE)
        controller.clear_filters(state)
        self.assertEqual(saved, [WorkFilter.AVAILABLE, WorkFilter.ALL])
