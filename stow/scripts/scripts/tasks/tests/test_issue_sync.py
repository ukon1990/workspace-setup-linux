"""Persistent dependency reuse and scope-wide incremental synchronization."""

import unittest
from dataclasses import replace
from tempfile import TemporaryDirectory
from unittest.mock import patch

from tasks.cache import CacheError, load_entry
from tasks.cli import main
from tasks.config import TasksConfig
from tasks.filters import AssigneeFilter
from tasks.github import GithubError
from tasks.issue_cache import DETAIL_LIMIT, IssueStore, load_store, save_store, store_path
from tasks.jira import JiraError
from tasks.models import (
    BackendIdentity,
    Comment,
    RelationshipKind,
    TaskDetail,
    TaskRelationship,
    TaskSummary,
    UpdateBatch,
)
from tasks.readiness import WorkState
from tasks.tui.controller import TasksController
from tasks.tui.hierarchy import build_relationship_hierarchy

T1 = "2026-10-01T10:00:00Z"
T2 = "2026-10-02T10:00:00Z"
T3 = "2026-10-03T10:00:00Z"


def issue(number, *, repo="acme/app", jira=False, **kwargs):
    identity = (
        BackendIdentity.jira(f"PROJ-{number}") if jira else BackendIdentity.github(number, repo)
    )
    return TaskSummary(identity, f"Issue {number}", "Open", updated_at=T1, **kwargs)


class Backend:
    backend_label = "GitHub"
    scope_label = "acme/app"

    def __init__(self, candidates, details):
        self.candidates = candidates
        self.details = {detail.identity.stable_id: detail for detail in details}
        self.updates = {}
        self.calls = []
        self.error = False

    def list_tasks(self, **kwargs):
        self.calls.append(("list", kwargs))
        if self.error:
            raise RuntimeError("offline")
        return self.candidates

    def get_task(self, identity, refresh=False):
        self.calls.append(("detail", identity.stable_id, refresh))
        if self.error:
            raise RuntimeError("offline")
        return self.details[identity.stable_id]

    def list_updates(self, scope, since):
        self.calls.append(("updates", scope, since))
        if self.error:
            raise RuntimeError("offline")
        return self.updates.get(scope, UpdateBatch())


class IssueSyncTests(unittest.TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.clock = patch("tasks.tui.sync.utc_now_iso", return_value=T2)
        self.clock.start()
        self.addCleanup(self.clock.stop)

    def controller(self, backend, scope="github:acme/app"):
        return TasksController(backend, cache_scope=scope, cache_dir=self.directory.name)

    def load(self, controller, **kwargs):
        state = controller.make_list_state()
        controller.load_list(state, **kwargs)
        self.assertIsNone(state.error)
        return state

    def test_restart_reuses_details_and_support_without_filtered_membership_leak(self):
        blocker = issue(2)
        dependent = issue(1, blocked_by=(blocker.identity,))
        details = [
            TaskDetail(
                dependent,
                "Body",
                (Comment("author", "comment", T1),),
                (TaskRelationship(RelationshipKind.BLOCKED_BY, blocker.identity, "blocked by"),),
            ),
            TaskDetail(blocker),
        ]
        backend = Backend([dependent], details)
        first = self.controller(backend)
        self.load(first)
        first.load_detail(dependent.identity)
        backend.calls.clear()
        second = self.controller(backend)
        state = self.load(second)
        detail, error = second.load_detail(dependent.identity)
        self.assertIsNone(error)
        self.assertEqual(detail, details[0])
        self.assertEqual([call[0] for call in backend.calls], ["updates"])
        self.assertEqual(state.tasks, [dependent])
        self.assertIn(blocker.identity.stable_id, second.cached_items)
        self.assertEqual(second.changed_ids, set())
        self.assertEqual(
            load_entry(
                second.cache_scope, None, AssigneeFilter.ALL, cache_dir=self.directory.name
            ).items.keys(),
            {dependent.identity.stable_id},
        )

    def test_changed_blocker_recomputes_readiness_and_icons_for_both_backends(self):
        for jira in (False, True):
            with self.subTest(jira=jira):
                blocker = issue(2, jira=jira)
                dependent = issue(1, jira=jira, blocked_by=(blocker.identity,))
                relation = TaskRelationship(
                    RelationshipKind.BLOCKED_BY, blocker.identity, "blocked by"
                )
                backend = Backend(
                    [dependent],
                    [TaskDetail(dependent, relationships=(relation,)), TaskDetail(blocker)],
                )
                scope = "jira:PROJ" if jira else "github:acme/app"
                first = self.controller(backend, scope)
                state = self.load(first)
                self.assertEqual(
                    state.readiness.states[dependent.identity.stable_id], WorkState.BLOCKED
                )
                first.load_detail(dependent.identity)
                done = replace(blocker, status="Custom complete", completed=True, updated_at=T3)
                backend.updates[scope] = UpdateBatch((done,))
                backend.details[done.identity.stable_id] = TaskDetail(done)
                backend.calls.clear()
                second = self.controller(backend, scope)
                state = self.load(second)
                self.assertEqual(
                    state.readiness.states[dependent.identity.stable_id], WorkState.READY
                )
                detail, _ = second.load_detail(dependent.identity)
                tree = build_relationship_hierarchy(second, detail)
                linked = tree.children[0]
                self.assertTrue(linked.progress_label.startswith("✓ blocked by:"))
                self.assertTrue(linked.changed)
                detail_calls = [call[1] for call in backend.calls if call[0] == "detail"]
                self.assertEqual(detail_calls, [])
                self.assertEqual(second.load_detail(blocker.identity)[0].summary, done)
                self.assertEqual(
                    [call[1] for call in backend.calls if call[0] == "detail"],
                    [blocker.identity.stable_id],
                )
                self.assertEqual(second.changed_ids, {blocker.identity.stable_id})

    def test_external_scope_is_checked_without_becoming_a_candidate(self):
        blocker = issue(2, repo="other/repo")
        dependent = issue(1, blocked_by=(blocker.identity,))
        backend = Backend([dependent], [TaskDetail(dependent), TaskDetail(blocker)])
        first = self.controller(backend)
        self.load(first)
        done = replace(blocker, status="Closed", completed=True, updated_at=T3)
        backend.updates["github:other/repo"] = UpdateBatch((done,))
        backend.calls.clear()
        second = self.controller(backend)
        state = self.load(second)
        self.assertEqual(state.readiness.states[dependent.identity.stable_id], WorkState.READY)
        self.assertEqual(state.tasks, [dependent])
        self.assertEqual(
            [call[1] for call in backend.calls if call[0] == "updates"],
            ["github:acme/app", "github:other/repo"],
        )
        self.assertFalse(any(call[0] in {"detail", "list"} for call in backend.calls))
        self.assertEqual(
            load_store("github:other/repo", self.directory.name).items[done.identity.stable_id],
            done,
        )

    def test_membership_reruns_after_changes_and_session_markers_survive_opening(self):
        old = issue(1)
        backend = Backend([old], [TaskDetail(old)])
        controller = self.controller(backend)
        state = self.load(controller)
        controller.load_detail(old.identity)
        changed = replace(old, updated_at=T3)
        new = replace(issue(3), updated_at=T3)
        backend.updates[controller.cache_scope] = UpdateBatch((changed, new))
        backend.candidates = [new]  # old no longer matches the active backend query/assignee.
        backend.details[new.identity.stable_id] = TaskDetail(new, "New body")
        backend.calls.clear()
        controller.load_list(state, refresh=True)
        self.assertEqual(state.tasks, [new])
        self.assertEqual(controller.changed_ids, {old.identity.stable_id, new.identity.stable_id})
        self.assertNotIn(old.identity.stable_id, controller.detail_cache)
        controller.load_detail(new.identity)
        self.assertIn(new.identity.stable_id, controller.changed_ids)
        self.assertEqual(len([call for call in backend.calls if call[0] == "list"]), 1)
        backend.calls.clear()
        controller.load_list(state, refresh=True)  # overlapping search returns unchanged versions.
        self.assertFalse(any(call[0] in {"list", "detail"} for call in backend.calls))

    def test_partial_sync_and_offline_fallback_do_not_advance_checkpoint(self):
        old = issue(1)
        backend = Backend([old], [TaskDetail(old)])
        first = self.controller(backend)
        self.load(first)
        first.load_detail(old.identity)
        backend.error = True
        second = self.controller(backend)
        state = self.load(second)
        self.assertEqual(second.load_detail(old.identity)[0].summary, old)
        self.assertIn("using saved data", second.work_status(state))
        self.assertEqual(load_store(first.cache_scope, self.directory.name).synced_at, T2)
        backend.error = False
        changed = replace(old, updated_at=T3)
        backend.updates[first.cache_scope] = UpdateBatch((changed,), complete=False)
        backend.candidates = [changed]
        with patch("tasks.tui.sync.utc_now_iso", return_value=T3):
            second.load_list(state, refresh=True)
        self.assertIn("Incomplete", second.sync_warning)
        self.assertEqual(load_store(first.cache_scope, self.directory.name).synced_at, T2)
        backend.updates[first.cache_scope] = UpdateBatch((changed,))
        with patch("tasks.tui.sync.utc_now_iso", return_value=T3):
            second.load_list(state, refresh=True)
        self.assertIsNone(second.sync_warning)
        self.assertEqual(load_store(first.cache_scope, self.directory.name).synced_at, T3)

    def test_direct_startup_sync_and_full_rebuild_with_offline_fallback(self):
        old = issue(1)
        backend = Backend([old], [TaskDetail(old, "old")])
        first = self.controller(backend)
        self.assertEqual(first.load_detail(old.identity)[0].description, "old")
        backend.calls.clear()
        second = self.controller(backend)
        self.assertEqual(second.load_detail(old.identity)[0].description, "old")
        self.assertEqual([call[0] for call in backend.calls], ["updates"])
        backend.details[old.identity.stable_id] = TaskDetail(old, "rebuilt")
        second.sync_scope(full=True)
        self.assertEqual(second.load_detail(old.identity)[0].description, "rebuilt")
        backend.error = True
        second.sync_scope(full=True)
        self.assertEqual(second.load_detail(old.identity)[0].description, "rebuilt")
        self.assertIn("Rebuild failed", second.sync_warning)

    def test_full_detail_refresh_checks_external_scope_and_retires_backup(self):
        blocker = issue(2, repo="other/repo")
        current = issue(1, blocked_by=(blocker.identity,))
        relation = TaskRelationship(RelationshipKind.BLOCKED_BY, blocker.identity, "blocked by")
        backend = Backend(
            [current], [TaskDetail(current, relationships=(relation,)), TaskDetail(blocker)]
        )
        controller = self.controller(backend)
        self.load(controller)
        controller.load_detail(current.identity)
        done = replace(blocker, updated_at=T3, status="Closed", completed=True)
        backend.updates["github:other/repo"] = UpdateBatch((done,))
        controller.sync_scope(full=True)
        controller.sync_detail_dependencies(current.identity, refresh=True)
        detail, _ = controller.load_detail(current.identity)
        self.assertTrue(
            build_relationship_hierarchy(controller, detail)
            .children[0]
            .progress_label.startswith("✓")
        )
        revision = controller._issue_store(controller.cache_scope).revision
        self.assertNotIn(controller.cache_scope, controller.rebuild_backups)
        backend.error = True
        missing = issue(99)
        self.assertIsNone(controller.load_detail(missing.identity)[0])
        self.assertEqual(controller._issue_store(controller.cache_scope).revision, revision)
        self.assertIn(
            current.identity.stable_id, controller._issue_store(controller.cache_scope).details
        )

    def test_overlap_and_older_index_versions_do_not_invalidate_details(self):
        current = issue(1)
        backend = Backend([current], [TaskDetail(current)])
        controller = self.controller(backend)
        state = self.load(controller)
        controller.load_detail(current.identity)
        for timestamp in ("2026-10-01T12:00:00+02:00", "2026-09-30T10:00:00Z"):
            backend.updates[controller.cache_scope] = UpdateBatch(
                (replace(current, updated_at=timestamp),)
            )
            backend.calls.clear()
            controller.load_list(state, refresh=True)
            self.assertEqual(controller.changed_ids, set())
            self.assertEqual(controller.load_detail(current.identity)[0].summary, current)
            self.assertEqual([call[0] for call in backend.calls], ["updates"])

    def test_changed_body_comments_and_hierarchy_are_loaded_on_demand(self):
        current = issue(1)
        backend = Backend([current], [TaskDetail(current, "old")])
        self.controller(backend).load_detail(current.identity)
        child = issue(2)
        changed = replace(current, updated_at=T3, dependencies_complete=False)
        details = TaskDetail(
            changed,
            "changed body",
            (Comment("author", "new comment", T3),),
            (TaskRelationship(RelationshipKind.CHILD, child.identity, "child"),),
        )
        backend.updates["github:acme/app"] = UpdateBatch((changed,))
        backend.details[current.identity.stable_id] = details
        backend.calls.clear()
        second = self.controller(backend)
        with patch("tasks.tui.sync.utc_now_iso", side_effect=[T3]):
            second.sync_scope()
        self.assertEqual([call[0] for call in backend.calls], ["updates"])
        self.assertEqual(second.load_detail(current.identity)[0], details)
        self.assertEqual(load_store(second.cache_scope, self.directory.name).synced_at, T3)
        self.assertEqual(
            load_store(second.cache_scope, self.directory.name).details[current.identity.stable_id],
            details,
        )

    def test_detail_discovered_version_invalidates_filtered_membership(self):
        old = issue(1, assignees=("me",))
        backend = Backend([old], [TaskDetail(old)])
        first = self.controller(backend)
        self.load(first)  # only summary is cached.
        changed = replace(old, updated_at=T3, assignees=("other",))
        backend.details[old.identity.stable_id] = TaskDetail(changed)
        second = self.controller(backend)
        state = self.load(second)
        second.load_detail(old.identity)  # detail sees a newer version before search indexes it.
        self.assertIn(old.identity.stable_id, second.changed_ids)
        backend.updates[second.cache_scope] = UpdateBatch((changed,))
        backend.candidates = []
        backend.calls.clear()
        second.load_list(state, refresh=True)
        self.assertEqual(state.tasks, [])
        self.assertEqual([call[0] for call in backend.calls], ["updates", "list"])

    def test_controller_detail_eviction_applies_to_memory_and_disk(self):
        summaries = [issue(number) for number in range(4)]
        backend = Backend([], [TaskDetail(summary) for summary in summaries])
        controller = self.controller(backend)
        with patch("tasks.issue_cache.DETAIL_LIMIT", 3):
            for summary in summaries:
                controller.load_detail(summary.identity)
        self.assertEqual(len(controller.detail_cache), 3)
        self.assertNotIn(summaries[0].identity.stable_id, controller.detail_cache)
        self.assertEqual(len(load_store(controller.cache_scope, self.directory.name).details), 3)

    def test_failed_save_keeps_checkpoint_and_allows_browsing(self):
        old = issue(1)
        backend = Backend([old], [TaskDetail(old)])
        first = self.controller(backend)
        self.load(first)
        second = self.controller(backend)
        with patch("tasks.tui.sync.save_store", side_effect=CacheError("disk full")):
            state = self.load(second)
        self.assertIn("disk full", second.work_status(state))
        self.assertEqual(load_store(first.cache_scope, self.directory.name).synced_at, T2)


class OfflineLaunchTests(unittest.TestCase):
    def test_offline_origin_resolution_supports_github_remote_formats(self):
        from tasks.cli import _local_github_repository

        for remote in (
            "git@github.com:Acme/App.git",
            "https://github.com/Acme/App.git",
            "ssh://git@github.com/Acme/App",
        ):
            with self.subTest(remote=remote), patch("tasks.process.run_text", return_value=remote):
                self.assertEqual(_local_github_repository(), "acme/app")
        with patch("tasks.process.run_text", return_value="https://gitlab.com/acme/app"):
            self.assertIsNone(_local_github_repository())

    @patch("tasks.cli._run_tui")
    @patch("tasks.cli._make_pulls_backend", return_value=(None, None))
    @patch("tasks.cli.load_config", return_value=TasksConfig())
    @patch("tasks.cli.GithubBackend")
    def test_github_saved_scope_opens_when_validation_is_offline(self, backend, config, pulls, run):
        backend.return_value.validate.side_effect = GithubError("offline")
        with TemporaryDirectory() as directory, patch("tasks.cache.DEFAULT_CACHE_DIR", directory):
            summary = issue(1)
            save_store(
                "github:acme/app",
                IssueStore(T2, items={summary.identity.stable_id: summary}),
                directory,
            )
            self.assertEqual(main(["--gh", "--repo", "acme/app"]), 0)
            self.assertEqual(run.call_args.args[1], "github:acme/app")

    @patch("tasks.cli._run_tui")
    @patch("tasks.cli._make_pulls_backend", return_value=(None, None))
    @patch("tasks.cli.load_config", return_value=TasksConfig())
    @patch("tasks.cli.JiraBackend")
    def test_jira_saved_scope_opens_when_validation_is_offline(self, backend, config, pulls, run):
        backend.return_value.validate.side_effect = JiraError("offline")
        with TemporaryDirectory() as directory, patch("tasks.cache.DEFAULT_CACHE_DIR", directory):
            summary = issue(1, jira=True)
            save_store(
                "jira:PROJ", IssueStore(T2, items={summary.identity.stable_id: summary}), directory
            )
            self.assertEqual(main(["--jira", "--project", "PROJ"]), 0)
            self.assertEqual(run.call_args.args[1], "jira:PROJ")


class IssueStoreTests(unittest.TestCase):
    def test_detail_roundtrip_version_invalidation_and_lru_bound(self):
        with TemporaryDirectory() as directory:
            store = IssueStore(T2)
            for number in range(DETAIL_LIMIT + 1):
                store.put_detail(TaskDetail(issue(number), "Body"))
            self.assertEqual(len(store.details), 200)
            self.assertNotIn(issue(0).identity.stable_id, store.details)
            scope = "github:acme/app"
            save_store(scope, store, directory)
            loaded = load_store(scope, directory)
            self.assertEqual(store, loaded)
            key = issue(1).identity.stable_id
            loaded.items[key] = replace(loaded.items[key], updated_at=T3)
            save_store(scope, loaded, directory)
            self.assertNotIn(key, load_store(scope, directory).details)
            path = store_path(scope, directory)
            path.write_text(path.read_text().replace("format: 2", "format: 1"))
            self.assertEqual(load_store(scope, directory), IssueStore())

    def test_corrupt_store_is_reported(self):
        with TemporaryDirectory() as directory:
            store_path("github:acme/app", directory).write_text("[broken")
            with self.assertRaises(CacheError):
                load_store("github:acme/app", directory)
