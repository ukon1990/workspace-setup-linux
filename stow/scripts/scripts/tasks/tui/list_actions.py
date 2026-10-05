"""Keyboard actions and navigation for the list screen."""

from __future__ import annotations

import webbrowser
from typing import Optional

from textual import on
from textual.screen import Screen
from textual.widgets import DataTable, Static, Tree

from ..filters import AssigneeFilter, WorkFilter
from ..models import BackendIdentity
from .logic import resolve_goto_identity, selected_task, set_filter, task_url
from .pulls import authors_from_pulls, set_author_filter, set_pull_filter
from .screen_helpers import _go_back
from .screen_modals import (
    AssigneeFilterModal,
    AuthorFilterModal,
    HelpScreen,
    InputModal,
    WorkFilterModal,
)


class ListActions(Screen):
    def action_tab_issues(self) -> None:
        if self._active_tab == "issues":
            return
        self._active_tab = "issues"
        self._view_mode = "table"
        self._update_tab_bar()
        self._ensure_issue_columns()
        self._update_chrome()
        self._populate_view()

    def action_tab_pulls(self) -> None:
        if self._active_tab == "pulls":
            return
        self._active_tab = "pulls"
        self._view_mode = "table"
        self._update_tab_bar()
        self._ensure_pull_columns()
        self._update_chrome()
        if not self._pulls_loaded and not self.pulls_state.repo_error:
            self.reload_pulls(refresh=True, full=False)
        else:
            self._populate_view()

    def action_toggle_view(self) -> None:
        if self._active_tab == "pulls":
            return
        if self._view_mode == "table":
            self._view_mode = "tree"
            self._forest = self._build_forest()
            self._tree_loaded = True
            self._update_chrome()
            self._populate_tree()
        else:
            self._view_mode = "table"
            self._populate_table()
            self._update_chrome()

    def action_cursor_down(self) -> None:
        if self._active_tab == "issues" and self._view_mode == "tree":
            self.query_one("#task-tree", Tree).action_cursor_down()
        else:
            self.query_one("#task-table", DataTable).action_cursor_down()

    def action_cursor_up(self) -> None:
        if self._active_tab == "issues" and self._view_mode == "tree":
            self.query_one("#task-tree", Tree).action_cursor_up()
        else:
            self.query_one("#task-table", DataTable).action_cursor_up()

    @on(DataTable.RowHighlighted)
    def track_cursor(self, event: DataTable.RowHighlighted) -> None:
        if event.cursor_row is None or event.cursor_row < 0:
            return
        if self._active_tab == "pulls":
            self.pulls_state.index = event.cursor_row
        else:
            self.state.index = event.cursor_row

    @on(DataTable.RowSelected)
    def open_selected_row(self, event: DataTable.RowSelected) -> None:
        if event.cursor_row is not None and event.cursor_row >= 0:
            if self._active_tab == "pulls":
                self.pulls_state.index = event.cursor_row
            else:
                self.state.index = event.cursor_row
        self.action_open_task()

    @on(Tree.NodeSelected)
    def open_selected_tree_node(self, event: Tree.NodeSelected) -> None:
        from .screens import DetailScreen

        if self._active_tab != "issues" or self._view_mode != "tree":
            return
        if event.node.data is None or not isinstance(event.node.data, BackendIdentity):
            return
        self.app.push_screen(DetailScreen(self.controller, event.node.data))

    def _selected_identity(self) -> Optional[BackendIdentity]:
        if self._active_tab != "issues":
            return None
        if self._view_mode == "tree":
            node = self.query_one("#task-tree", Tree).cursor_node
            if node is not None and isinstance(node.data, BackendIdentity):
                return node.data
            return None
        task = selected_task(self.state)
        return task.identity if task else None

    def action_open_task(self) -> None:
        from .screens import DetailScreen, PullDetailScreen

        if self._active_tab == "pulls":
            pull = self._selected_pull()
            if pull is None:
                return
            self.app.push_screen(PullDetailScreen(self.pulls_controller, pull))
            return
        identity = self._selected_identity()
        if identity is None:
            return
        self.app.push_screen(DetailScreen(self.controller, identity))

    def action_local_filter(self) -> None:
        def apply(value: Optional[str]) -> None:
            if value is None:
                return
            if self._active_tab == "pulls":
                set_pull_filter(self.pulls_state, value)
                self._update_chrome()
                self._populate_pulls_table()
                return
            set_filter(self.state, value)
            self._tree_loaded = False
            self._update_chrome()
            if self._view_mode == "tree":
                self._forest = self._build_forest()
                self._tree_loaded = True
                self._populate_tree()
            else:
                self._populate_table()

        initial = (
            self.pulls_state.filter_text if self._active_tab == "pulls" else self.state.filter_text
        )
        self.app.push_screen(
            InputModal("Local filter", initial=initial, placeholder="text…"),
            apply,
        )

    def action_assignee_filter(self) -> None:
        def apply(selection: Optional[AssigneeFilter]) -> None:
            if selection is None:
                return
            self._pending_assignee = selection
            self._reload_if_unchanged = True
            self.apply_assignee_filter()

        self.app.push_screen(AssigneeFilterModal(), apply)

    def action_work_filter(self) -> None:
        if self._active_tab != "issues":
            return

        def apply(selection: Optional[WorkFilter]) -> None:
            if selection is None:
                return
            self.controller.change_work_filter(self.state, selection)
            self._tree_loaded = False
            if self._view_mode == "tree":
                self._forest = self._build_forest()
                self._tree_loaded = True
            self._populate_view()
            self._update_chrome()

        self.app.push_screen(WorkFilterModal(self.state.work_filter), apply)

    def action_author_filter(self) -> None:
        if self._active_tab != "pulls":
            return

        def apply(selection: Optional[frozenset[str]]) -> None:
            if selection is None:
                return
            set_author_filter(self.pulls_state, selection)
            self._populate_pulls_table()
            self._update_chrome()

        self.app.push_screen(
            AuthorFilterModal(
                authors_from_pulls(self.pulls_state.pulls),
                selected=self.pulls_state.author_filter,
            ),
            apply,
        )

    def action_clear_filters(self) -> None:
        self.clear_filters_worker()

    def action_goto(self) -> None:
        from .screens import DetailScreen

        def apply(value: Optional[str]) -> None:
            if value is None:
                return
            identity = resolve_goto_identity(self.controller.backend, value)
            if identity is None:
                status = self.query_one("#status-bar", Static)
                status.update(f"Invalid issue ID: {value.strip() or '(empty)'}")
                status.add_class("error")
                return
            self.app.push_screen(DetailScreen(self.controller, identity))

        self.app.push_screen(
            InputModal("Open by ID", placeholder="FORSC-8207 or #42…"),
            apply,
        )

    def action_search(self) -> None:
        from .screens import ListScreen

        def apply(value: Optional[str]) -> None:
            if value is None:
                return
            if self._active_tab == "pulls":
                self.pulls_state.query = value or None
                self.pulls_state.index = 0
                self.reload_pulls(refresh=True, full=bool(value))
                return
            new_state = self.controller.make_list_state(
                query=value or None,
                assignee_filter=self.state.assignee_filter,
                work_filter=self.state.work_filter,
            )
            self.app.push_screen(
                ListScreen(
                    self.controller,
                    new_state,
                    self.pulls_controller,
                    load_on_mount=True,
                    pulls_error=self.pulls_state.repo_error,
                )
            )

        self.app.push_screen(InputModal("Backend search", placeholder="search…"), apply)

    def action_refresh(self) -> None:
        if self._active_tab == "pulls":
            self.reload_pulls(refresh=True, full=False)
            return
        self._tree_loaded = False
        self.reload_list(refresh=True, full=False)

    def action_full_reload(self) -> None:
        if self._active_tab == "pulls":
            self.reload_pulls(refresh=True, full=True)
            return
        self._tree_loaded = False
        self.reload_list(refresh=True, full=True)

    def action_open_url(self) -> None:
        if self._active_tab == "pulls":
            pull = self._selected_pull()
            url = pull.url if pull else None
            if not url:
                self.notify("No URL for this pull request", severity="warning")
                return
            webbrowser.open(url)
            self.notify(f"Opened {url}")
            return
        identity = self._selected_identity()
        url = None
        if identity is not None:
            cached = self.controller.detail_cache.get(identity.stable_id)
            url = task_url(cached, identity)
            if url is None:
                task = selected_task(self.state)
                if task and task.identity.stable_id == identity.stable_id:
                    url = task.url
                else:
                    for item in self.state.tasks:
                        if item.identity.stable_id == identity.stable_id:
                            url = item.url
                            break
        if not url:
            self.notify("No URL for this task", severity="warning")
            return
        webbrowser.open(url)
        self.notify(f"Opened {url}")

    def action_help(self) -> None:
        self.app.push_screen(HelpScreen())

    def action_back(self) -> None:
        _go_back(self)

    def action_quit_app(self) -> None:
        self.app.exit()
