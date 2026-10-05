"""Table and tree rendering for the list screen."""

from __future__ import annotations

from typing import Optional, Sequence

from textual import on
from textual.screen import Screen
from textual.widgets import DataTable, Static, Tree

from ..pr_views import activity_label
from .logic import (
    TABLE_SORT_COLUMNS,
    HierarchyNode,
    assignee_filter_text,
    blocked_by_label,
    blocks_label,
    selected_task,
    visible_tasks,
)
from .pulls import PULL_SORT_COLUMNS, ci_label, format_pull_timestamp, visible_pulls
from .screen_helpers import _mount_hierarchy


class ListRendering(Screen):
    def _ensure_issue_columns(self) -> None:
        table = self.query_one("#task-table", DataTable)
        table.clear(columns=True)
        table.add_columns(
            ("Key", "key"),
            ("Status", "status"),
            ("Work", "work"),
            ("Ready descendants", "ready_descendants"),
            ("Changed", "changed"),
            ("Type", "type"),
            ("Priority", "priority"),
            ("Assignees", "assignees"),
            ("Title", "title"),
            ("Blocked by", "blocked_by"),
            ("Blocks", "blocks"),
        )
        self._issue_columns_ready = True

    def _ensure_pull_columns(self) -> None:
        table = self.query_one("#task-table", DataTable)
        table.clear(columns=True)
        table.add_columns(
            ("Key", "key"),
            ("CI", "ci"),
            ("State", "status"),
            ("Author", "author"),
            ("Updated", "updated"),
            ("Created", "created"),
            ("Seen", "activity"),
            ("Title", "title"),
        )
        self._issue_columns_ready = False

    def _update_tab_bar(self) -> None:
        issues = "Issues" if self._active_tab != "issues" else "[b]Issues[/b]"
        pulls = "Pull requests" if self._active_tab != "pulls" else "[b]Pull requests[/b]"
        self.query_one("#tab-bar", Static).update(f"{issues}  |  {pulls}   (1 / 2)")

    def _update_chrome(self) -> None:
        status = self.query_one("#status-bar", Static)
        if self._active_tab == "pulls":
            backend = self.pulls_controller.backend
            scope = backend.scope_label if backend else "unresolved"
            self.title = f"Pull requests · {scope}"
            query = self.pulls_state.query or "open"
            assignee = assignee_filter_text(self.pulls_state.assignee_filter)
            filter_label = (
                f" · filter: {self.pulls_state.filter_text}" if self.pulls_state.filter_text else ""
            )
            authors = self.pulls_state.author_filter
            author_label = (
                f" · authors: {', '.join(sorted(authors, key=str.casefold))}" if authors else ""
            )
            visible = len(self._visible_pulls())
            error = self.pulls_state.error or self.pulls_state.repo_error
            if error:
                status.update(f"Error: {error}")
                status.add_class("error")
            else:
                status.update(
                    f"Query: {query} · assignee: {assignee}{filter_label}{author_label} · "
                    f"{visible}/{len(self.pulls_state.pulls)}"
                )
                status.remove_class("error")
            return
        backend = self.controller.backend
        self.title = f"{backend.backend_label} · {backend.scope_label}"
        query = self.state.query or "open"
        assignee = assignee_filter_text(self.state.assignee_filter)
        filter_label = f" · filter: {self.state.filter_text}" if self.state.filter_text else ""
        visible = len(visible_tasks(self.state))
        view = "tree" if self._view_mode == "tree" else "table"
        tree_note = ""
        if self._view_mode == "tree" and self._forest:
            tree_note = f" · tree: {self._count_nodes(self._forest)} nodes"
        if self.state.error:
            status.update(f"Error: {self.state.error}")
            status.add_class("error")
        else:
            status.update(
                f"Query: {query} · assignee: {assignee}{filter_label} · "
                f"{visible}/{len(self.state.tasks)} · view: {view}{tree_note} · "
                f"{self.controller.work_status(self.state)}"
            )
            status.remove_class("error")

    @staticmethod
    def _count_nodes(nodes: Sequence[HierarchyNode]) -> int:
        from .screens import ListScreen

        return sum(1 + ListScreen._count_nodes(node.children) for node in nodes)

    def _populate_view(self) -> None:
        if self._active_tab == "pulls":
            self._populate_pulls_table()
            return
        if self._view_mode == "tree":
            self._populate_tree()
        else:
            self._populate_table()

    def _populate_pulls_table(self, keep_identity: Optional[str] = None) -> None:
        if self._issue_columns_ready:
            self._ensure_pull_columns()
        table = self.query_one("#task-table", DataTable)
        tree = self.query_one("#task-tree", Tree)
        empty = self.query_one("#empty-message", Static)
        tree.display = False
        table.clear()
        if keep_identity is None:
            current = self._selected_pull()
            if current is not None:
                keep_identity = current.stable_id
        views = self._pull_views()
        pulls = visible_pulls(self.pulls_state, viewed_times=views)
        error = self.pulls_state.error or self.pulls_state.repo_error
        if error:
            table.display = False
            empty.display = True
            empty.update(f"Error: {error}")
            return
        if not pulls:
            table.display = False
            empty.display = True
            empty.update(
                "No pull requests match the local filter."
                if self.pulls_state.pulls and self.pulls_state.filter_text
                else "No pull requests found."
            )
            return
        table.display = True
        empty.display = False
        for pull in pulls:
            table.add_row(
                pull.display_key,
                ci_label(pull.ci_state),
                pull.status,
                pull.author or "-",
                format_pull_timestamp(pull.updated_at),
                format_pull_timestamp(pull.created_at),
                activity_label(pull.updated_at, views.get(pull.stable_id)),
                pull.title,
                key=pull.stable_id,
            )
        index = 0
        if keep_identity is not None:
            for offset, pull in enumerate(pulls):
                if pull.stable_id == keep_identity:
                    index = offset
                    break
        else:
            index = min(max(self.pulls_state.index, 0), len(pulls) - 1)
        self.pulls_state.index = index
        table.move_cursor(row=index)
        table.focus()

    def _populate_table(self, keep_identity: Optional[str] = None) -> None:
        if not self._issue_columns_ready:
            self._ensure_issue_columns()
        table = self.query_one("#task-table", DataTable)
        tree = self.query_one("#task-tree", Tree)
        empty = self.query_one("#empty-message", Static)
        tree.display = False
        table.clear()
        if keep_identity is None:
            current = selected_task(self.state)
            if current is not None:
                keep_identity = current.identity.stable_id
        tasks = visible_tasks(self.state)
        if self.state.error:
            table.display = False
            empty.display = True
            empty.update(f"Error: {self.state.error}")
            return
        if not tasks:
            table.display = False
            empty.display = True
            empty.update(self._empty_issue_message())
            return
        table.display = True
        empty.display = False
        for task in tasks:
            table.add_row(
                task.display_key,
                task.status,
                self.controller.work_label(self.state, task),
                self.controller.ready_descendant_count(self.state, task),
                "*"
                if task.identity.stable_id in getattr(self.controller, "changed_ids", ())
                else "",
                task.task_type or "-",
                task.priority or "-",
                ", ".join(task.assignees) or "-",
                task.title,
                blocked_by_label(task),
                blocks_label(task),
                key=task.identity.stable_id,
            )
        index = 0
        if keep_identity is not None:
            for offset, task in enumerate(tasks):
                if task.identity.stable_id == keep_identity:
                    index = offset
                    break
        else:
            index = min(max(self.state.index, 0), len(tasks) - 1)
        self.state.index = index
        table.move_cursor(row=index)
        table.focus()

    @on(DataTable.HeaderSelected)
    def sort_by_header(self, event: DataTable.HeaderSelected) -> None:
        if self._active_tab == "pulls":
            column = event.column_key.value
            if not isinstance(column, str) or column not in PULL_SORT_COLUMNS:
                return
            current = self._selected_pull()
            keep_identity = current.stable_id if current else None
            if self.pulls_state.sort_column == column:
                self.pulls_state.sort_reverse = not self.pulls_state.sort_reverse
            else:
                self.pulls_state.sort_column = column
                self.pulls_state.sort_reverse = column in {"updated", "created"}
            self._populate_pulls_table(keep_identity=keep_identity)
            self._update_chrome()
            return
        if self._view_mode != "table":
            return
        column = event.column_key.value
        if not isinstance(column, str) or column not in TABLE_SORT_COLUMNS:
            return
        current = selected_task(self.state)
        keep_identity = current.identity.stable_id if current else None
        if self.state.sort_column == column:
            self.state.sort_reverse = not self.state.sort_reverse
        else:
            self.state.sort_column = column
            self.state.sort_reverse = False
        self._populate_table(keep_identity=keep_identity)
        self._update_chrome()

    def _populate_tree(self) -> None:
        table = self.query_one("#task-table", DataTable)
        tree = self.query_one("#task-tree", Tree)
        empty = self.query_one("#empty-message", Static)
        table.display = False
        tree.clear()
        if self.state.error:
            tree.display = False
            empty.display = True
            empty.update(f"Error: {self.state.error}")
            return
        if not self._forest:
            tree.display = False
            empty.display = True
            empty.update(self._empty_issue_message())
            return
        empty.display = False
        tree.display = True
        _mount_hierarchy(tree.root, self._forest)
        tree.root.expand()
        tree.focus()
        self._update_chrome()
