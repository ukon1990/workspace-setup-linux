"""Resolve child work outside filters and reconcile hierarchy changes in caches."""

import unittest
from dataclasses import replace
from tempfile import TemporaryDirectory
from unittest.mock import patch

from tasks.filters import WorkFilter
from tasks.models import (
    BackendIdentity,
    ChildrenBatch,
    RelationshipKind,
    TaskDetail,
    TaskRelationship,
    TaskSummary,
    UpdateBatch,
)
from tasks.readiness import WorkState
from tasks.tui.controller import TasksController
from tasks.tui.hierarchy import build_relationship_hierarchy
from tasks.tui.logic import set_filter, visible_tasks, work_result

T1 = "2026-10-01T10:00:00Z"
T2 = "2026-10-02T10:00:00Z"
T3 = "2026-10-03T10:00:00Z"


def issue(number, *, jira=False, **kwargs):
    identity = (
        BackendIdentity.jira(f"PROJ-{number}")
        if jira
        else BackendIdentity.github(number, "owner/repo")
    )
    return TaskSummary(identity, f"Task {number}", "Open", updated_at=T1, **kwargs)


class Backend:
    def __init__(self, candidates, tasks, *, jira=False):
        self.candidates = candidates
        self.tasks = {task.identity.stable_id: task for task in tasks}
        self.calls = []
        self.updates = UpdateBatch()
        self.updates_by_scope = {}
        self.jira = jira
        self.partial = False

    def list_tasks(self, **kwargs):
        self.calls.append(("list", kwargs))
        return self.candidates

    def get_task(self, identity, refresh=False):
        self.calls.append(("detail", identity.stable_id))
        task = self.tasks[identity.stable_id]
        relations = tuple(
            TaskRelationship(RelationshipKind.CHILD, child, "sub-issue") for child in task.children
        )
        return TaskDetail(task, relationships=relations)

    def list_updates(self, scope, since):
        self.calls.append(("updates", scope))
        return self.updates_by_scope.get(scope, self.updates)

    def list_children(self, parents):
        self.calls.append(("children", tuple(parent.stable_id for parent in parents)))
        keys = {parent.stable_id for parent in parents}
        return ChildrenBatch(
            tuple(
                task
                for task in self.tasks.values()
                if task.parent is not None and task.parent.stable_id in keys
            ),
            not self.partial,
        )


class WorkResolutionTests(unittest.TestCase):
    def test_jira_discovers_children_without_candidate_membership_or_filters(self):
        blocker = issue(90, jira=True)
        feature = issue(15, jira=True, children_complete=False)
        first = issue(151, jira=True, parent=feature.identity)
        second = issue(152, jira=True, parent=feature.identity, blocked_by=(first.identity,))
        third = issue(153, jira=True, parent=feature.identity, blocked_by=(first.identity,))
        blocked_feature = issue(16, jira=True, children_complete=False)
        blocked_child = issue(
            161, jira=True, parent=blocked_feature.identity, blocked_by=(blocker.identity,)
        )
        backend = Backend(
            [feature, blocked_feature],
            [feature, first, second, third, blocked_feature, blocked_child, blocker],
            jira=True,
        )
        controller = TasksController(backend)
        state = controller.make_list_state(query="features")
        controller.load_list(state)
        self.assertEqual(state.readiness.states[feature.identity.stable_id], WorkState.READY)
        self.assertEqual(
            state.readiness.states[blocked_feature.identity.stable_id], WorkState.BLOCKED
        )
        self.assertEqual(state.tasks, [feature, blocked_feature])
        self.assertEqual(state.readiness.ready_descendants[feature.identity.stable_id], 0)
        self.assertEqual(len([call for call in backend.calls if call[0] == "children"]), 1)
        set_filter(state, "Task 16")
        self.assertEqual(work_result(state).states[feature.identity.stable_id], WorkState.READY)
        state.work_filter = WorkFilter.READY_ONLY
        self.assertEqual(visible_tasks(state), [])
        set_filter(state, "")
        self.assertEqual([task.identity for task in visible_tasks(state)], [feature.identity])
        detail, _ = controller.load_detail(feature.identity)
        tree = build_relationship_hierarchy(controller, detail)
        self.assertEqual([node.completion_icon for node in tree.children], ["○", "x", "x"])

    def test_partial_children_unknown_and_known_ready_branch_proves_ready(self):
        feature = issue(1, jira=True, children_complete=False)
        blocker = issue(9, jira=True)
        child = issue(2, jira=True, parent=feature.identity, blocked_by=(blocker.identity,))
        backend = Backend([feature], [feature, child, blocker], jira=True)
        backend.partial = True
        controller = TasksController(backend)
        state = controller.make_list_state()
        controller.load_list(state)
        self.assertEqual(state.readiness.states[feature.identity.stable_id], WorkState.UNKNOWN)
        backend.tasks[child.identity.stable_id] = replace(child, blocked_by=())
        controller.cached_items.clear()
        controller.load_list(state, refresh=True)
        self.assertEqual(state.readiness.states[feature.identity.stable_id], WorkState.READY)

    def test_new_hidden_child_and_parent_move_with_unchanged_parent_versions(self):
        with (
            TemporaryDirectory() as directory,
            patch("tasks.tui.sync.utc_now_iso", return_value=T2),
        ):
            parent = issue(1, children=(issue(2).identity,))
            blocker = issue(9)
            child = issue(2, parent=parent.identity, blocked_by=(blocker.identity,))
            other = issue(3)
            backend = Backend([parent, other], [parent, child, blocker, other])
            controller = TasksController(
                backend, cache_scope="github:owner/repo", cache_dir=directory
            )
            state = controller.make_list_state()
            controller.load_list(state)
            controller.load_detail(parent.identity)
            self.assertEqual(state.readiness.states[parent.identity.stable_id], WorkState.BLOCKED)
            fresh = replace(issue(4, parent=parent.identity), updated_at=T3)
            backend.tasks[fresh.identity.stable_id] = fresh
            backend.updates = UpdateBatch(
                (replace(fresh, parent=None, dependencies_complete=False, children_complete=False),)
            )
            controller.load_list(state, refresh=True)
            self.assertEqual(state.readiness.states[parent.identity.stable_id], WorkState.READY)
            detail, _ = controller.load_detail(parent.identity)
            self.assertIn(
                fresh.identity,
                [
                    node.identity
                    for node in build_relationship_hierarchy(controller, detail).children
                ],
            )
            moved = replace(fresh, parent=other.identity, updated_at="2026-10-04T10:00:00Z")
            backend.tasks[moved.identity.stable_id] = moved
            backend.updates = UpdateBatch(
                (replace(moved, parent=None, dependencies_complete=False, children_complete=False),)
            )
            controller.load_list(state, refresh=True)
            self.assertEqual(state.readiness.states[parent.identity.stable_id], WorkState.BLOCKED)
            self.assertEqual(state.readiness.states[other.identity.stable_id], WorkState.READY)
            detail, _ = controller.load_detail(parent.identity)
            self.assertNotIn(
                moved.identity,
                [
                    node.identity
                    for node in build_relationship_hierarchy(controller, detail).children
                ],
            )
            backend.calls.clear()
            restarted = TasksController(
                backend, cache_scope="github:owner/repo", cache_dir=directory
            )
            restarted.load_list(restarted.make_list_state())
            self.assertFalse(any(call[0] in {"detail", "children"} for call in backend.calls))

    def test_unresolved_update_cannot_leave_all_blocked_inventory_claim(self):
        parent = issue(1, children=(issue(2).identity,))
        blocker = issue(9)
        child = issue(2, parent=parent.identity, blocked_by=(blocker.identity,))
        missing = replace(
            issue(4, dependencies_complete=False, children_complete=False), updated_at=T3
        )
        backend = Backend([parent], [parent, child, blocker])
        controller = TasksController(backend)
        controller.changed_ids.add(missing.identity.stable_id)
        controller.cached_items[missing.identity.stable_id] = missing
        result = controller.resolve_readiness([parent])
        self.assertEqual(result.states[parent.identity.stable_id], WorkState.UNKNOWN)
        self.assertLessEqual(controller.last_readiness_loads, 80)

    def test_failed_hidden_update_is_retried_across_restart_and_external_ancestors(self):
        for external in (False, True):
            with (
                self.subTest(external=external),
                TemporaryDirectory() as directory,
                patch("tasks.tui.sync.utc_now_iso", return_value=T2),
            ):
                parent = issue(1, children=(issue(2).identity,))
                if external:
                    parent = replace(parent, identity=BackendIdentity.github(1, "other/repo"))
                blocker = issue(9)
                child = issue(2, parent=parent.identity, blocked_by=(blocker.identity,))
                fresh = replace(issue(4, parent=parent.identity), updated_at=T3)
                if external:
                    fresh = replace(fresh, identity=BackendIdentity.github(4, "other/repo"))
                candidates = [child] if external else [parent]
                backend = Backend(candidates, [parent, child, blocker])
                first = TasksController(
                    backend, cache_scope="github:owner/repo", cache_dir=directory
                )
                first.load_list(first.make_list_state())
                pending = replace(
                    fresh, parent=None, dependencies_complete=False, children_complete=False
                )
                scope = first.scope_for_identity(parent.identity)
                if external:
                    backend.updates_by_scope["github:owner/repo"] = UpdateBatch()
                backend.updates_by_scope[scope] = UpdateBatch((pending,))
                state = first.make_list_state()
                first.load_list(state, refresh=True)
                self.assertEqual(
                    state.readiness.states[parent.identity.stable_id], WorkState.UNKNOWN
                )
                restarted = TasksController(
                    backend, cache_scope="github:owner/repo", cache_dir=directory
                )
                state = restarted.make_list_state()
                restarted.load_list(state)
                self.assertEqual(
                    state.readiness.states[parent.identity.stable_id], WorkState.UNKNOWN
                )
                backend.tasks[fresh.identity.stable_id] = fresh
                final = TasksController(
                    backend, cache_scope="github:owner/repo", cache_dir=directory
                )
                state = final.make_list_state()
                final.load_list(state)
                self.assertEqual(state.readiness.states[parent.identity.stable_id], WorkState.READY)

    def test_jira_inventory_persists_and_is_reused_after_restart(self):
        with (
            TemporaryDirectory() as directory,
            patch("tasks.tui.sync.utc_now_iso", return_value=T2),
        ):
            parent = issue(1, jira=True, children_complete=False)
            child = issue(2, jira=True, parent=parent.identity)
            backend = Backend([parent], [parent, child], jira=True)
            controller = TasksController(backend, cache_scope="jira:PROJ", cache_dir=directory)
            controller.load_list(controller.make_list_state())
            backend.calls.clear()
            restarted = TasksController(backend, cache_scope="jira:PROJ", cache_dir=directory)
            state = restarted.make_list_state()
            restarted.load_list(state)
            self.assertEqual(state.readiness.states[parent.identity.stable_id], WorkState.READY)
            self.assertEqual([call[0] for call in backend.calls], ["updates"])

    def test_child_lookup_budget_keeps_unresolved_rows_unknown(self):
        parent = issue(1, jira=True, children_complete=False)
        children = [
            issue(number, jira=True, parent=parent.identity, children_complete=False)
            for number in range(2, 100)
        ]
        backend = Backend([parent], [parent, *children], jira=True)
        controller = TasksController(backend)
        result = controller.resolve_readiness([parent], max_loads=4)
        self.assertEqual(controller.last_readiness_loads, 4)
        self.assertEqual(result.states[parent.identity.stable_id], WorkState.UNKNOWN)
        self.assertEqual(len(result.items), 4)


if __name__ == "__main__":
    unittest.main()
