import curses
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
    AppState,
    DetailFocus,
    DetailState,
    ListState,
    TasksTui,
    assignee_filter_for_key,
    assignee_filter_text,
    clamp_selection,
    clip,
    detail_content_lines,
    filter_tasks,
    go_back,
    move_list,
    move_relationship,
    push_screen,
    relationship_line,
    set_filter,
    toggle_detail_focus,
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


class FakeScreen:
    def __init__(self, keys, sizes=((24, 80),)):
        self.keys = iter(keys)
        self.sizes = iter(sizes)
        self.size = (24, 80)

    def getmaxyx(self):
        self.size = next(self.sizes, self.size)
        return self.size

    def get_wch(self):
        return next(self.keys)

    def addstr(self, *args):
        pass

    def clrtoeol(self):
        pass

    def refresh(self):
        pass


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
        self.assertIsNone(assignee_filter_for_key(curses.KEY_UP))

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

    def test_selection_clamps_and_scrolls(self):
        self.assertEqual(clamp_selection(7, 0, 10, 3), (7, 5))
        self.assertEqual(clamp_selection(-1, 5, 10, 3), (0, 0))
        self.assertEqual(clamp_selection(4, 8, 2, 3), (1, 0))
        self.assertEqual(clamp_selection(4, 8, 0, 3), (0, 0))

    def test_filter_and_move_reset_and_update_view(self):
        state = ListState([summary(i) for i in range(1, 7)], index=4, scroll=3)
        set_filter(state, "Task")
        self.assertEqual((state.index, state.scroll), (0, 0))
        move_list(state, 4, visible=2)
        self.assertEqual((state.index, state.scroll), (4, 3))

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

    def test_detail_focus_and_relationship_movement(self):
        target = BackendIdentity.github(2, "owner/repo")
        relations = (
            TaskRelationship(RelationshipKind.BLOCKS, target, "blocks"),
            TaskRelationship(RelationshipKind.RELATED, target, "relates to"),
        )
        state = DetailState(
            BackendIdentity.github(1, "owner/repo"),
            detail(1, relationships=relations),
        )
        toggle_detail_focus(state)
        move_relationship(state, 5)
        self.assertEqual(state.focus, DetailFocus.RELATIONSHIPS)
        self.assertEqual(state.relationship_index, 1)
        move_relationship(state, -5)
        self.assertEqual(state.relationship_index, 0)


class HistoryTests(unittest.TestCase):
    def test_history_restores_exact_list_state(self):
        original = ListState(
            [summary(1), summary(2)],
            query="mine",
            assignee_filter=AssigneeFilter.ME,
            filter_text="alpha",
            index=1,
            scroll=1,
        )
        state = AppState(original)
        push_screen(
            state,
            DetailState(
                BackendIdentity.github(2, "owner/repo"),
                focus=DetailFocus.RELATIONSHIPS,
                content_scroll=5,
                relationship_index=2,
            ),
        )
        original.filter_text = "changed after snapshot"
        self.assertTrue(go_back(state))
        self.assertEqual(state.screen.query, "mine")
        self.assertEqual(state.screen.assignee_filter, AssigneeFilter.ME)
        self.assertEqual(state.screen.filter_text, "alpha")
        self.assertEqual((state.screen.index, state.screen.scroll), (1, 1))

    def test_history_restores_exact_detail_state(self):
        first = DetailState(
            BackendIdentity.github(1, "owner/repo"),
            detail(1),
            focus=DetailFocus.RELATIONSHIPS,
            content_scroll=4,
            relationship_index=1,
            relationship_scroll=1,
        )
        state = AppState(first)
        push_screen(state, DetailState(BackendIdentity.github(2, "owner/repo")))
        self.assertTrue(go_back(state))
        self.assertEqual(state.screen.focus, DetailFocus.RELATIONSHIPS)
        self.assertEqual(state.screen.content_scroll, 4)
        self.assertEqual(state.screen.relationship_index, 1)
        self.assertEqual(state.screen.relationship_scroll, 1)

    def test_direct_detail_back_signals_exit(self):
        state = AppState(DetailState(BackendIdentity.github(1, "owner/repo")))
        self.assertFalse(go_back(state))


class ControllerTests(unittest.TestCase):
    def test_filter_menu_selects_and_cancel_preserves_state(self):
        tui = TasksTui(FakeBackend(), initial_assignee_filter=AssigneeFilter.ME)
        screen = FakeScreen(["?", "u"])
        self.assertEqual(tui._filter_menu(screen), AssigneeFilter.UNASSIGNED)

        screen = FakeScreen(["\x1b"])
        self.assertIsNone(tui._filter_menu(screen))
        self.assertEqual(tui.state.screen.assignee_filter, AssigneeFilter.ME)

    def test_prompt_accepts_printable_unicode(self):
        tui = TasksTui(FakeBackend())
        screen = FakeScreen(["æ", "ø", "å", "\n"])

        with patch("tasks.tui.curses.curs_set"):
            self.assertEqual(tui._prompt(screen, "Filter: "), "æøå")

    def test_prompt_handles_resize_backspace_and_special_integer_keys(self):
        tui = TasksTui(FakeBackend())
        screen = FakeScreen(
            [curses.KEY_RESIZE, curses.KEY_LEFT, curses.KEY_BACKSPACE, "å", "\r"],
            sizes=((24, 80), (30, 100)),
        )

        with patch("tasks.tui.curses.curs_set"):
            self.assertEqual(tui._prompt(screen, "Filter: ", "ab"), "aå")

    def test_prompt_escape_cancels(self):
        tui = TasksTui(FakeBackend())
        screen = FakeScreen(["æ", "\x1b"])

        with patch("tasks.tui.curses.curs_set"):
            self.assertIsNone(tui._prompt(screen, "Filter: "))

    def test_initial_list_and_refresh_use_protocol_flags(self):
        backend = FakeBackend()
        tui = TasksTui(
            backend,
            query="ready",
            initial_assignee_filter=AssigneeFilter.ME_OR_UNASSIGNED,
        )
        tui.load_initial()
        tui.refresh()
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
        tui = TasksTui(
            backend,
            query="ready",
            on_assignee_filter_change=changes.append,
        )
        tui.load_initial()

        self.assertTrue(tui.change_assignee_filter(AssigneeFilter.ME))
        self.assertEqual(
            backend.list_calls[-1],
            ("ready", False, AssigneeFilter.ME),
        )
        self.assertEqual(changes, [AssigneeFilter.ME])

        self.assertFalse(
            tui.change_assignee_filter(
                AssigneeFilter.ME,
                reload_if_unchanged=True,
            )
        )
        self.assertEqual(backend.list_calls[-1], ("ready", False, AssigneeFilter.ME))
        self.assertEqual(changes, [AssigneeFilter.ME])

    def test_clear_resets_both_filters_and_only_reloads_structured_change(self):
        backend = FakeBackend()
        changes = []
        tui = TasksTui(
            backend,
            initial_tasks=backend.tasks,
            initial_assignee_filter=AssigneeFilter.UNASSIGNED,
            on_assignee_filter_change=changes.append,
        )
        tui.state.screen.filter_text = "alpha"

        self.assertTrue(tui.clear_filters())
        self.assertEqual(tui.state.screen.filter_text, "")
        self.assertEqual(tui.state.screen.assignee_filter, AssigneeFilter.ALL)
        self.assertEqual(
            backend.list_calls,
            [(None, False, AssigneeFilter.ALL)],
        )
        self.assertEqual(changes, [AssigneeFilter.ALL])

        tui.state.screen.filter_text = "beta"
        self.assertFalse(tui.clear_filters())
        self.assertEqual(tui.state.screen.filter_text, "")
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

        tui = TasksTui(
            backend,
            initial_tasks=backend.tasks,
            on_assignee_filter_change=fail_to_persist,
        )
        self.assertTrue(tui.change_assignee_filter(AssigneeFilter.ME))
        self.assertEqual(tui.state.screen.assignee_filter, AssigneeFilter.ME)
        self.assertEqual(tui.state.screen.tasks, backend.tasks)
        self.assertEqual(tui.state.screen.error, "offline; cannot persist")

    def test_details_are_loaded_lazily_and_cached(self):
        backend = FakeBackend()
        tui = TasksTui(backend, initial_tasks=backend.tasks)
        self.assertTrue(tui.open_selected_task())
        self.assertEqual(backend.detail_calls, [("github:owner/repo:1", False)])
        self.assertTrue(go_back(tui.state))
        self.assertTrue(tui.open_selected_task())
        self.assertEqual(backend.detail_calls, [("github:owner/repo:1", False)])

    def test_refresh_replaces_cached_detail(self):
        backend = FakeBackend()
        tui = TasksTui(backend, initial_identity=backend.tasks[0].identity)
        tui.load_initial()
        tui.refresh()
        self.assertEqual(
            backend.detail_calls,
            [("github:owner/repo:1", False), ("github:owner/repo:1", True)],
        )

    def test_failed_relationship_fetch_is_retryable_without_history_damage(self):
        target = BackendIdentity.github(2, "owner/repo")
        relation = TaskRelationship(RelationshipKind.BLOCKS, target, "blocks")
        backend = FakeBackend()
        backend.details["github:owner/repo:1"] = detail(1, relationships=(relation,))
        backend.failures.add(target.stable_id)
        tui = TasksTui(backend, initial_identity=BackendIdentity.github(1, "owner/repo"))
        tui.load_initial()

        self.assertFalse(tui.open_selected_relationship())
        self.assertEqual(tui.state.screen.relationship_index, 0)
        self.assertEqual(tui.state.screen.error, "not available")
        self.assertEqual(tui.state.history, [])

        backend.failures.clear()
        self.assertTrue(tui.open_selected_relationship())
        self.assertEqual(tui.state.screen.identity, target)
        self.assertEqual(len(tui.state.history), 1)
        self.assertEqual(
            backend.detail_calls[-2:],
            [("github:owner/repo:2", False), ("github:owner/repo:2", False)],
        )
        self.assertTrue(go_back(tui.state))
        self.assertIsNone(tui.state.screen.error)

    def test_opening_relationship_preserves_detail_scroll_in_history(self):
        target = BackendIdentity.github(2, "owner/repo")
        relations = (
            TaskRelationship(RelationshipKind.BLOCKS, target, "blocks"),
            TaskRelationship(RelationshipKind.RELATED, target, "relates to"),
        )
        backend = FakeBackend()
        backend.details["github:owner/repo:1"] = detail(1, relationships=relations)
        tui = TasksTui(backend, initial_identity=BackendIdentity.github(1, "owner/repo"))
        tui.load_initial()
        tui.state.screen.relationship_index = 1
        tui.state.screen.relationship_scroll = 0
        self.assertTrue(tui.open_selected_relationship())
        self.assertTrue(go_back(tui.state))
        self.assertEqual(
            (tui.state.screen.relationship_index, tui.state.screen.relationship_scroll),
            (1, 0),
        )

    def test_search_pushes_current_screen_and_restores_it(self):
        backend = FakeBackend()
        original = ListState(
            backend.tasks,
            assignee_filter=AssigneeFilter.ME,
            filter_text="alpha",
            index=1,
            scroll=1,
        )
        tui = TasksTui(backend, initial_tasks=backend.tasks)
        tui.state.screen = original
        tui.search("backend query")
        self.assertEqual(tui.state.screen.query, "backend query")
        self.assertEqual(tui.state.screen.assignee_filter, AssigneeFilter.ME)
        self.assertEqual(
            backend.list_calls[-1],
            ("backend query", False, AssigneeFilter.ME),
        )
        self.assertTrue(go_back(tui.state))
        self.assertEqual(tui.state.screen.assignee_filter, AssigneeFilter.ME)
        self.assertEqual(tui.state.screen.filter_text, "alpha")
        self.assertEqual((tui.state.screen.index, tui.state.screen.scroll), (1, 1))

    def test_search_from_direct_detail_restores_detail_then_exits(self):
        backend = FakeBackend()
        tui = TasksTui(
            backend,
            initial_identity=backend.tasks[0].identity,
            initial_assignee_filter=AssigneeFilter.ASSIGNED_ANYONE,
        )
        tui.load_initial()
        tui.state.screen.focus = DetailFocus.RELATIONSHIPS
        tui.state.screen.content_scroll = 3
        tui.search("next")
        self.assertEqual(tui.state.screen.assignee_filter, AssigneeFilter.ASSIGNED_ANYONE)
        self.assertTrue(go_back(tui.state))
        self.assertEqual(tui.state.screen.focus, DetailFocus.RELATIONSHIPS)
        self.assertEqual(tui.state.screen.content_scroll, 3)
        self.assertFalse(go_back(tui.state))

    def test_opening_task_preserves_list_scroll_in_history(self):
        backend = FakeBackend()
        tui = TasksTui(backend, initial_tasks=backend.tasks)
        tui.state.screen.index = 1
        tui.state.screen.scroll = 0
        self.assertTrue(tui.open_selected_task())
        self.assertTrue(go_back(tui.state))
        self.assertEqual((tui.state.screen.index, tui.state.screen.scroll), (1, 0))

    def test_list_error_and_empty_results_remain_refreshable(self):
        class FailingBackend(FakeBackend):
            def list_tasks(
                self,
                query=None,
                refresh=False,
                assignee_filter=AssigneeFilter.ALL,
            ):
                raise RuntimeError("offline")

        tui = TasksTui(FailingBackend())
        tui.load_initial()
        self.assertEqual(tui.state.screen.error, "offline")
        self.assertEqual(tui.state.screen.tasks, [])


if __name__ == "__main__":
    unittest.main()
