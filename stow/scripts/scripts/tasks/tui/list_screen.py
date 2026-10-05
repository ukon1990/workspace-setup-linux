"""Issue and pull-request list screen and background loading."""

from __future__ import annotations

from typing import Optional

from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Header, LoadingIndicator, Static, Tree

from ..filters import AssigneeFilter, WorkFilter
from .list_actions import ListActions
from .list_rendering import ListRendering
from .logic import (
    HierarchyNode,
    ListState,
    SyncProgress,
    TasksController,
    format_sync_progress,
)
from .pulls import (
    PullsController,
    selected_pull,
    set_author_filter,
    set_pull_filter,
    visible_pulls,
)


class ListScreen(ListRendering, ListActions, Screen):
    """Browse and filter the task list."""

    BINDINGS = [
        Binding("j", "cursor_down", "Down", show=False),
        Binding("k", "cursor_up", "Up", show=False),
        Binding("enter", "open_task", "Open", show=True),
        Binding("1", "tab_issues", "Issues", show=True),
        Binding("2", "tab_pulls", "PRs", show=True),
        Binding("left_square_bracket", "tab_issues", "Issues", show=False),
        Binding("right_square_bracket", "tab_pulls", "PRs", show=False),
        Binding("t", "toggle_view", "Tree", show=True),
        Binding("slash", "local_filter", "Filter", show=True),
        Binding("f", "assignee_filter", "Assignee", show=True),
        Binding("w", "work_filter", "Work", show=True),
        Binding("a", "author_filter", "Author", show=True),
        Binding("c", "clear_filters", "Clear", show=True),
        Binding("s", "search", "Search", show=True),
        Binding("g", "goto", "Goto", show=True),
        Binding("r", "refresh", "Refresh", show=True),
        Binding("R", "full_reload", "Full", show=True),
        Binding("o", "open_url", "Open URL", show=True),
        Binding("question_mark", "help", "Help", show=True),
        Binding("h", "back", "Back", show=True),
        Binding("backspace", "back", show=False),
        Binding("escape", "back", show=False),
        Binding("q", "quit_app", "Quit", show=True),
    ]

    def __init__(
        self,
        controller: TasksController,
        state: ListState,
        pulls_controller: Optional[PullsController] = None,
        *,
        load_on_mount: bool = True,
        pulls_error: Optional[str] = None,
    ) -> None:
        super().__init__()
        self.controller = controller
        self.state = state
        self.pulls_controller = pulls_controller or PullsController(None)
        self.pulls_state = self.pulls_controller.make_list_state(
            assignee_filter=AssigneeFilter.ALL,
            repo_error=pulls_error,
        )
        self._load_on_mount = load_on_mount
        self._pending_assignee: Optional[AssigneeFilter] = None
        self._reload_if_unchanged = False
        self._view_mode = "table"
        self._forest: list[HierarchyNode] = []
        self._tree_loaded = False
        self._active_tab = "issues"
        self._pulls_loaded = False
        self._issue_columns_ready = False
        self._sync_revision = None

    def _pull_views(self) -> dict[str, Optional[str]]:
        return self.pulls_controller.viewed_times_for(self.pulls_state.pulls)

    def _visible_pulls(self):
        return visible_pulls(self.pulls_state, viewed_times=self._pull_views())

    def _selected_pull(self):
        return selected_pull(self.pulls_state, viewed_times=self._pull_views())

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        yield Static("Issues | Pull requests", id="tab-bar")
        yield Static(id="status-bar")
        yield DataTable(id="task-table", cursor_type="row", zebra_stripes=True)
        yield Tree("Tasks", id="task-tree")
        yield Static("", id="empty-message")
        yield Footer()
        with Vertical(id="loading-overlay"):
            yield LoadingIndicator()
            yield Static("", id="sync-progress")

    def on_mount(self) -> None:
        self.query_one("#loading-overlay").display = False
        self._ensure_issue_columns()
        tree = self.query_one("#task-tree", Tree)
        tree.display = False
        tree.show_root = False
        tree.auto_expand = False
        self._update_tab_bar()
        self.query_one("#task-table", DataTable).focus()
        self._update_chrome()
        if self.state.error is None and (
            getattr(self.controller, "persistent_sync", False)
            or (self._load_on_mount and not self.state.tasks)
        ):
            self.reload_list(refresh=False)
        else:
            self._populate_view()

    def on_screen_resume(self) -> None:
        if self._active_tab == "issues":
            revision = getattr(self.controller, "sync_revision", None)
            if self._sync_revision is not None and revision != self._sync_revision:
                self.reload_list()
                return
            self.state.changed_ids = getattr(self.controller, "changed_ids", set())
            if self._view_mode == "tree":
                self._forest = self._build_forest()
            self._populate_view()
            self._update_chrome()
        elif self._pulls_loaded:
            self._populate_pulls_table()
            self._update_chrome()

    def _set_loading(self, active: bool) -> None:
        overlay = self.query_one("#loading-overlay")
        overlay.display = active
        if not active:
            self.query_one("#sync-progress", Static).update("")

    def _set_sync_progress(self, progress: SyncProgress) -> None:
        self.query_one("#sync-progress", Static).update(format_sync_progress(progress))

    def _progress_callback(self):
        return lambda progress: self.app.call_from_thread(self._set_sync_progress, progress)

    def _empty_issue_message(self) -> str:
        if self.state.work_filter != WorkFilter.ALL:
            return "No available work matches the current filters."
        if self.state.tasks and self.state.filter_text:
            return "No tasks match the local filter."
        return "No tasks found."

    def _build_forest(self) -> list[HierarchyNode]:
        return self.controller.build_work_forest(self.state)

    @work(exclusive=True, thread=True)
    def reload_list(self, refresh: bool = False, full: bool = False) -> None:
        self.app.call_from_thread(self._set_loading, True)
        forest: list[HierarchyNode] = []
        try:
            self.controller.load_list(
                self.state,
                refresh=refresh,
                full=full,
                on_progress=self._progress_callback(),
            )
            if self._view_mode == "tree":
                forest = self._build_forest()
        finally:
            self.app.call_from_thread(self._after_reload, forest)

    def _after_reload(self, forest: Optional[list[HierarchyNode]] = None) -> None:
        self._sync_revision = getattr(self.controller, "sync_revision", None)
        self._set_loading(False)
        if forest is not None and self._view_mode == "tree":
            self._forest = forest
            self._tree_loaded = True
        elif self._view_mode == "table":
            self._tree_loaded = False
        self._update_chrome()
        self._populate_view()

    @work(exclusive=True, thread=True)
    def apply_assignee_filter(self) -> None:
        selection = self._pending_assignee
        if selection is None:
            return
        reload_if_unchanged = self._reload_if_unchanged
        self.app.call_from_thread(self._set_loading, True)
        forest: list[HierarchyNode] = []
        try:
            if self._active_tab == "pulls":
                self.pulls_controller.change_assignee_filter(
                    self.pulls_state,
                    selection,
                    reload_if_unchanged=reload_if_unchanged,
                )
            else:
                self.controller.change_assignee_filter(
                    self.state,
                    selection,
                    reload_if_unchanged=reload_if_unchanged,
                    on_progress=self._progress_callback(),
                )
                if self._view_mode == "tree":
                    forest = self._build_forest()
        finally:
            self.app.call_from_thread(self._after_reload, forest)

    @work(exclusive=True, thread=True)
    def clear_filters_worker(self) -> None:
        self.app.call_from_thread(self._set_loading, True)
        forest: list[HierarchyNode] = []
        try:
            if self._active_tab == "pulls":
                set_pull_filter(self.pulls_state, "")
                set_author_filter(self.pulls_state, frozenset())
                self.pulls_controller.change_assignee_filter(
                    self.pulls_state,
                    AssigneeFilter.ALL,
                    reload_if_unchanged=True,
                )
            else:
                self.controller.clear_filters(self.state, on_progress=self._progress_callback())
                if self._view_mode == "tree":
                    forest = self._build_forest()
        finally:
            self.app.call_from_thread(self._after_reload, forest)

    @work(exclusive=True, thread=True)
    def reload_pulls(self, refresh: bool = False, full: bool = False) -> None:
        self.app.call_from_thread(self._set_loading, True)
        try:
            self.pulls_controller.load_list(self.pulls_state, refresh=refresh, full=full)
            self._pulls_loaded = True
        finally:
            self.app.call_from_thread(self._after_reload, None)
