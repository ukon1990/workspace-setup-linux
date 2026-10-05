"""Detail relationship completion, loading and rendering regressions."""

import asyncio
import unittest
from dataclasses import replace

from tasks.models import (
    BackendIdentity,
    RelationshipKind,
    TaskDetail,
    TaskRelationship,
    TaskSummary,
)
from tasks.tui import TasksController, build_forest_from_summaries, build_relationship_hierarchy
from tasks.tui.app import TasksApp
from tasks.tui.pulls import PullsController
from tasks.tui.screens import DetailScreen
from textual.widgets import Tree


def issue(number, *, jira=False, **kwargs):
    identity = (
        BackendIdentity.jira(f"PROJ-{number}")
        if jira
        else BackendIdentity.github(number, "owner/repo")
    )
    return TaskSummary(identity, f"Title {number}", kwargs.pop("status", "Open"), **kwargs)


def relation(kind, task, label=None):
    return TaskRelationship(kind, task.identity, label or kind.value.replace("_", " "), task.title)


class Backend:
    def __init__(self, details):
        self.details = {detail.identity.stable_id: detail for detail in details}
        self.calls = []

    def get_task(self, identity, refresh=False):
        self.calls.append((identity.stable_id, refresh))
        return self.details[identity.stable_id]


def flatten(node):
    return [node] + [nested for child in node.children for nested in flatten(child)]


class RelationshipIconTests(unittest.TestCase):
    def test_all_kinds_both_backends_preserve_labels_titles_and_progress(self):
        for jira in (False, True):
            with self.subTest(jira=jira):
                parent = issue(1, jira=jira, status="In Progress")
                current = issue(2, jira=jira)
                child = issue(3, jira=jira, status="Resolved")
                blocker = issue(4, jira=jira, status="Released", completed=True)
                blocked = issue(5, jira=jira, status="In Progress", completed=False)
                related = issue(6, jira=jira, status="Unknown")
                mentioned = issue(7, jira=jira, status="Closed")
                targets = [parent, child, blocker, blocked, related, mentioned]
                kinds = [
                    RelationshipKind.PARENT,
                    RelationshipKind.CHILD,
                    RelationshipKind.BLOCKED_BY,
                    RelationshipKind.BLOCKS,
                    RelationshipKind.RELATED,
                    RelationshipKind.MENTIONED,
                ]
                detail = TaskDetail(
                    current,
                    relationships=tuple(
                        relation(kind, target) for kind, target in zip(kinds, targets, strict=True)
                    ),
                )
                controller = TasksController(
                    Backend([detail, *(TaskDetail(target) for target in targets)])
                )
                tree = build_relationship_hierarchy(controller, detail)
                nodes = {node.identity.key: node for node in flatten(tree)}
                for target, icon in zip(
                    [parent, current, *targets[1:]],
                    ["○", "○", "✓", "✓", "○", "?", "✓"],
                    strict=True,
                ):
                    node = nodes[target.identity.key]
                    self.assertTrue(node.progress_label.startswith(icon + " "))
                    self.assertEqual(node.title, target.title)
                links = tree.children[0].children[1:]
                self.assertEqual(
                    [node.link_label for node in links],
                    ["blocked by", "blocks", "related", "mentioned"],
                )
                self.assertEqual((tree.done_leaves, tree.total_leaves), (1, 1))
                self.assertTrue(
                    all((node.done_leaves, node.total_leaves) == (0, 0) for node in links)
                )
                self.assertIn("blocked by: " + blocker.display_key, links[0].progress_label)

    def test_overview_labels_do_not_gain_icons(self):
        for status in ("Closed", "Open", "Unknown"):
            node = build_forest_from_summaries([issue(1, status=status)])[0]
            self.assertEqual(node.completion_icon, "")
            self.assertTrue(node.progress_label.startswith("["))

    def test_failure_targets_remain_visible_and_duplicate_fetches_are_deduplicated(self):
        current, missing = issue(1), issue(2)
        detail = TaskDetail(
            current,
            relationships=(
                relation(RelationshipKind.BLOCKED_BY, missing),
                relation(RelationshipKind.RELATED, missing),
            ),
        )
        backend = Backend([detail])
        tree = build_relationship_hierarchy(TasksController(backend), detail, refresh=True)
        self.assertEqual(len(tree.children), 2)
        self.assertEqual(backend.calls, [(missing.identity.stable_id, True)])
        self.assertTrue(all(node.progress_label.startswith("? ") for node in tree.children))
        self.assertTrue(all(node.identity == missing.identity for node in tree.children))

    def test_missing_parent_and_child_are_selectable_unknown_nodes(self):
        current, parent, child = issue(1), issue(2), issue(3)
        detail = TaskDetail(
            current,
            relationships=(
                relation(RelationshipKind.PARENT, parent),
                relation(RelationshipKind.CHILD, child),
            ),
        )
        tree = build_relationship_hierarchy(TasksController(Backend([detail])), detail)
        self.assertEqual(tree.identity, parent.identity)
        self.assertEqual(tree.completion_icon, "?")
        self.assertEqual(tree.children[0].children[0].identity, child.identity)
        self.assertEqual(tree.children[0].children[0].completion_icon, "?")

    def test_cached_summaries_details_and_current_issue_are_reused(self):
        current, blocker, related = issue(1), issue(2, completed=True), issue(3)
        detail = TaskDetail(
            current,
            relationships=(
                relation(RelationshipKind.BLOCKED_BY, blocker),
                relation(RelationshipKind.RELATED, related),
                relation(RelationshipKind.MENTIONED, current),
            ),
        )
        backend = Backend([detail])
        controller = TasksController(backend)
        controller.cached_items[blocker.identity.stable_id] = blocker
        controller.detail_cache[related.identity.stable_id] = TaskDetail(related)
        tree = build_relationship_hierarchy(controller, detail)
        self.assertEqual([node.completion_icon for node in tree.children], ["✓", "○", "○"])
        self.assertEqual(backend.calls, [])

    def test_refresh_replaces_cached_completion_once_per_identity(self):
        current, blocker = issue(1), issue(2)
        detail = TaskDetail(
            current,
            relationships=(
                relation(RelationshipKind.BLOCKED_BY, blocker),
                relation(RelationshipKind.MENTIONED, blocker),
            ),
        )
        backend = Backend([detail, TaskDetail(replace(blocker, completed=True))])
        controller = TasksController(backend)
        controller.detail_cache[blocker.identity.stable_id] = TaskDetail(blocker)
        controller.cached_items[blocker.identity.stable_id] = blocker
        self.assertEqual(
            build_relationship_hierarchy(controller, detail).children[0].completion_icon, "○"
        )
        tree = build_relationship_hierarchy(controller, detail, refresh=True)
        self.assertEqual([node.completion_icon for node in tree.children], ["✓", "✓"])
        self.assertEqual(backend.calls, [(blocker.identity.stable_id, True)])

    def test_additional_lookup_cap_preserves_all_targets_and_no_recursive_expansion(self):
        current = issue(1)
        targets = [issue(i, completed=True) for i in range(2, 84)]
        detail = TaskDetail(
            current,
            relationships=tuple(relation(RelationshipKind.MENTIONED, target) for target in targets),
        )
        backend = Backend(
            [
                detail,
                *(
                    TaskDetail(
                        target, relationships=(relation(RelationshipKind.CHILD, issue(999)),)
                    )
                    for target in targets
                ),
            ]
        )
        tree = build_relationship_hierarchy(TasksController(backend), detail)
        self.assertEqual(len(backend.calls), 80)
        self.assertEqual(len(tree.children), 82)
        self.assertEqual([node.completion_icon for node in tree.children], ["✓"] * 80 + ["?"] * 2)
        self.assertTrue(all(not node.children for node in tree.children))

    def test_rendered_icons_navigation_and_refresh(self):
        current, blocker = issue(1), issue(2)
        detail = TaskDetail(
            current, relationships=(relation(RelationshipKind.BLOCKED_BY, blocker),)
        )
        backend = Backend([detail, TaskDetail(blocker)])
        app = TasksApp(
            TasksController(backend), PullsController(None), initial_identity=current.identity
        )

        async def run():
            async with app.run_test(size=(140, 45)) as pilot:
                await app.workers.wait_for_complete()
                screen = app.screen
                tree = screen.query_one("#relations-tree", Tree)
                linked = tree.root.children[0].children[0]
                self.assertTrue(str(linked.label).startswith("○ blocked by:"))
                backend.details[blocker.identity.stable_id] = TaskDetail(
                    replace(blocker, completed=True)
                )
                await pilot.press("r")
                await app.workers.wait_for_complete()
                self.assertTrue(
                    str(tree.root.children[0].children[0].label).startswith("✓ blocked by:")
                )
                # The completed relationship remains navigable.
                tree.select_node(tree.root.children[0].children[0])
                await pilot.pause()
                await app.workers.wait_for_complete()
                self.assertIsInstance(app.screen, DetailScreen)
                self.assertEqual(app.screen.identity, blocker.identity)

        asyncio.run(run())
