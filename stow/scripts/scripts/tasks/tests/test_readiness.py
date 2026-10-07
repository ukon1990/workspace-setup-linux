"""Shared work evaluation and supporting-data resolution regressions."""

import tempfile
import unittest
from dataclasses import replace

from tasks.filters import WorkFilter
from tasks.models import BackendIdentity, TaskDetail, TaskSummary
from tasks.readiness import WORK_ICONS, WorkState, evaluate, is_done, work_icon
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

    def test_feature_rollup_and_filter_independence_both_backends(self):
        for jira in (False, True):

            def make(number, jira=jira, **kwargs):
                value = task(number, **kwargs)
                return (
                    replace(value, identity=BackendIdentity.jira(f"PROJ-{number}"))
                    if jira
                    else value
                )

            with self.subTest(jira=jira):
                blocker = make(99)
                ready = make(1, status="In Progress")
                blocked = [make(i, blocked_by=(blocker.identity,)) for i in (2, 3)]
                feature = make(15, children=tuple(item.identity for item in [ready, *blocked]))
                feature_blocked_children = [make(i, blocked_by=(blocker.identity,)) for i in (4, 5)]
                blocked_feature = make(
                    16, children=tuple(item.identity for item in feature_blocked_children)
                )
                items = [
                    feature,
                    blocked_feature,
                    ready,
                    *blocked,
                    *feature_blocked_children,
                    blocker,
                ]
                result = self.result(items)
                self.assertEqual(result.states[feature.identity.stable_id], WorkState.READY)
                self.assertEqual(
                    result.states[blocked_feature.identity.stable_id], WorkState.BLOCKED
                )
                self.assertEqual(result.ready_descendants[feature.identity.stable_id], 1)
                filtered = self.result(items, [blocked[0]])
                self.assertEqual(filtered.states, result.states)
                self.assertEqual(filtered.ready_descendants[feature.identity.stable_id], 0)
                self.assertEqual(filtered.selected("available"), [])

    def test_child_inventory_unknown_done_and_proven_ready_rules(self):
        ready = task(1)
        blocker = task(2)
        blocked = task(3, blocked_by=(blocker.identity,))
        done = task(4, completed=True)
        unknown = task(5, dependencies_complete=False)
        cases = [
            (task(10, children_complete=False), WorkState.UNKNOWN),
            (task(10, children=(task(999).identity,)), WorkState.UNKNOWN),
            (task(10, children=(done.identity,)), WorkState.READY),
            (task(10, children=(blocked.identity,), children_complete=False), WorkState.UNKNOWN),
            (task(10, children=(blocked.identity,)), WorkState.BLOCKED),
            (task(10, children=(ready.identity,), children_complete=False), WorkState.READY),
            (task(10, children=(unknown.identity,)), WorkState.UNKNOWN),
            (task(10, children=(ready.identity,), dependencies_complete=False), WorkState.UNKNOWN),
            (task(10, children=(task(999).identity,), completed=True), WorkState.DONE),
            (
                task(10, children=(ready.identity,), blocked_by=(blocker.identity,)),
                WorkState.BLOCKED,
            ),
        ]
        for parent, expected in cases:
            with self.subTest(parent=parent):
                result = self.result([parent, ready, blocker, blocked, done, unknown])
                self.assertEqual(result.states[parent.identity.stable_id], expected)

    def test_parent_link_inventory_nested_rollup_and_inherited_blockers(self):
        blocker = task(99)
        parent = task(15)
        feature = task(16, parent=parent.identity)
        ready = task(1, parent=parent.identity)
        blocked = task(2, parent=feature.identity, blocked_by=(blocker.identity,))
        result = self.result([parent, feature, ready, blocked, blocker])
        self.assertEqual(result.states[parent.identity.stable_id], WorkState.READY)
        self.assertEqual(result.states[feature.identity.stable_id], WorkState.BLOCKED)
        self.assertEqual(result.states[ready.identity.stable_id], WorkState.READY)
        result = self.result(
            [replace(parent, blocked_by=(blocker.identity,)), feature, ready, blocked, blocker]
        )
        self.assertTrue(
            all(
                result.states[item.identity.stable_id] is WorkState.BLOCKED
                for item in [parent, feature, ready, blocked]
            )
        )

    def test_child_cycles_stay_unknown_even_with_ready_exit_but_blocker_dominates(self):
        ready, blocker = task(3), task(99)
        first = task(1, children=(task(2).identity, ready.identity))
        second = task(2, children=(first.identity,))
        result = self.result([first, second, ready, blocker])
        self.assertEqual(result.states[first.identity.stable_id], WorkState.UNKNOWN)
        self.assertEqual(result.states[second.identity.stable_id], WorkState.UNKNOWN)
        result = self.result(
            [replace(first, blocked_by=(blocker.identity,)), second, ready, blocker]
        )
        self.assertEqual(result.states[first.identity.stable_id], WorkState.BLOCKED)
        result = self.result([first, replace(second, completed=True, children=()), ready])
        self.assertEqual(result.states[first.identity.stable_id], WorkState.READY)

    def test_explicit_children_infer_ancestry_but_native_parent_overrides_stale_edge(self):
        blocker = task(99)
        child = task(1)
        parent = task(15, children=(child.identity,), blocked_by=(blocker.identity,))
        result = self.result([parent, child, blocker])
        self.assertEqual(result.states[child.identity.stable_id], WorkState.BLOCKED)
        actual_parent = task(16)
        moved_child = replace(child, parent=actual_parent.identity)
        result = self.result([parent, actual_parent, moved_child, blocker])
        self.assertEqual(result.states[moved_child.identity.stable_id], WorkState.READY)
        self.assertEqual(result.ready_descendants[parent.identity.stable_id], 0)
        self.assertEqual(result.ready_descendants[actual_parent.identity.stable_id], 1)

    def test_parent_identity_url_does_not_change_explicit_child_membership(self):
        parent = replace(
            task(15), identity=replace(task(15).identity, url="https://example.test/15")
        )
        child = task(1, parent=task(15).identity, blocked_by=(task(99).identity,))
        parent = replace(parent, children=(child.identity,))
        result = self.result([parent, child, task(99)])
        self.assertEqual(result.states[parent.identity.stable_id], WorkState.BLOCKED)
        self.assertEqual(result.states[child.identity.stable_id], WorkState.BLOCKED)

    def test_conflicting_inferred_parents_are_unknown_unless_blocking_is_proven(self):
        child = task(1)
        parents = [task(number, children=(child.identity,)) for number in (15, 16)]
        result = self.result([*parents, child])
        self.assertEqual(result.states[child.identity.stable_id], WorkState.UNKNOWN)
        blocker = task(99)
        result = self.result(
            [replace(parents[0], blocked_by=(blocker.identity,)), parents[1], child, blocker]
        )
        self.assertEqual(result.states[child.identity.stable_id], WorkState.BLOCKED)

    def test_work_icons_are_shared_for_all_states(self):
        self.assertEqual(
            WORK_ICONS,
            {
                WorkState.DONE: "✓",
                WorkState.READY: "○",
                WorkState.BLOCKED: "x",
                WorkState.UNKNOWN: "?",
            },
        )
        self.assertEqual([work_icon(state) for state in WorkState], ["○", "x", "✓", "?"])

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
