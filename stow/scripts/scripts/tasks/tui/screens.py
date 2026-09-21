"""Textual screens and modals for the tasks browser."""

from __future__ import annotations

import webbrowser
from typing import Optional, Sequence

from textual import on, work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen, Screen
from textual.widgets import (
    DataTable,
    Footer,
    Header,
    Input,
    Label,
    LoadingIndicator,
    Markdown,
    OptionList,
    Static,
    Tree,
)
from textual.widgets.option_list import Option
from textual.widgets.tree import TreeNode

from ..filters import AssigneeFilter
from ..models import BackendIdentity, TaskDetail
from .logic import (
    ASSIGNEE_FILTER_OPTIONS,
    HierarchyNode,
    ListState,
    TasksController,
    assignee_filter_for_key,
    assignee_filter_text,
    build_forest_from_summaries,
    build_relationship_hierarchy,
    detail_content_text,
    filter_tasks,
    selected_task,
    set_filter,
    task_url,
)

HELP_MARKDOWN = """\
# Tasks help

| Key | Action |
| --- | --- |
| `j` / `↓` | Move down |
| `k` / `↑` | Move up |
| `Enter` | Open task / relationship |
| `Space` | Expand / collapse tree node |
| `t` | Toggle table / tree |
| `/` | Local text filter |
| `f` | Assignee filter |
| `c` | Clear filters |
| `s` | Backend search |
| `r` | Refresh (changed since last sync) |
| `R` | Full reload (replace cache) |
| `Tab` | Toggle detail panes |
| `o` | Open task URL |
| `?` | This help |
| `h` / `Backspace` / `Esc` | Back |
| `q` | Quit |
"""


def _go_back(screen: Screen) -> None:
    if len(screen.app.screen_stack) > 1:
        screen.app.pop_screen()
    else:
        screen.app.exit()


def _mount_hierarchy(
    parent: TreeNode[BackendIdentity],
    nodes: Sequence[HierarchyNode],
    *,
    expand: bool = True,
) -> None:
    for node in nodes:
        tree_node = parent.add(node.progress_label, data=node.identity)
        if node.children:
            _mount_hierarchy(tree_node, node.children, expand=expand)
            if expand:
                tree_node.expand()


class InputModal(ModalScreen[Optional[str]]):
    """Prompt for a single line of text."""

    BINDINGS = [
        Binding("escape", "cancel", "Cancel", show=True),
    ]

    def __init__(self, title: str, *, initial: str = "", placeholder: str = "") -> None:
        super().__init__()
        self._title = title
        self._initial = initial
        self._placeholder = placeholder

    def compose(self) -> ComposeResult:
        with Vertical(classes="modal-box"):
            yield Label(self._title)
            yield Input(value=self._initial, placeholder=self._placeholder, id="modal-input")

    def on_mount(self) -> None:
        self.query_one("#modal-input", Input).focus()

    @on(Input.Submitted)
    def accept(self, event: Input.Submitted) -> None:
        self.dismiss(event.value.strip())

    def action_cancel(self) -> None:
        self.dismiss(None)


class AssigneeFilterModal(ModalScreen[Optional[AssigneeFilter]]):
    """Pick an assignee filter; letter shortcuts mirror the old menu."""

    BINDINGS = [
        Binding("escape", "cancel", "Cancel", show=True),
        Binding("a", "pick_a", show=False),
        Binding("m", "pick_m", show=False),
        Binding("u", "pick_u", show=False),
        Binding("o", "pick_o", show=False),
        Binding("d", "pick_d", show=False),
    ]

    def compose(self) -> ComposeResult:
        with Vertical(classes="modal-box"):
            yield Label("Assignee filter")
            options = [
                Option(f"[{key}] {label}", id=selection.value)
                for selection, key, label in ASSIGNEE_FILTER_OPTIONS
            ]
            yield OptionList(*options, id="assignee-options")

    def on_mount(self) -> None:
        self.query_one("#assignee-options", OptionList).focus()

    @on(OptionList.OptionSelected)
    def pick(self, event: OptionList.OptionSelected) -> None:
        if event.option_id is None:
            return
        self.dismiss(AssigneeFilter(event.option_id))

    def _pick_key(self, key: str) -> None:
        selection = assignee_filter_for_key(key)
        if selection is not None:
            self.dismiss(selection)

    def action_pick_a(self) -> None:
        self._pick_key("a")

    def action_pick_m(self) -> None:
        self._pick_key("m")

    def action_pick_u(self) -> None:
        self._pick_key("u")

    def action_pick_o(self) -> None:
        self._pick_key("o")

    def action_pick_d(self) -> None:
        self._pick_key("d")

    def action_cancel(self) -> None:
        self.dismiss(None)


class HelpScreen(ModalScreen[None]):
    BINDINGS = [
        Binding("escape", "close", "Close", show=True),
        Binding("q", "close", "Close", show=False),
        Binding("question_mark", "close", show=False),
    ]

    def compose(self) -> ComposeResult:
        with Vertical(classes="modal-box"):
            yield Markdown(HELP_MARKDOWN, id="help-body")
            yield Label("Press Esc to close")

    def action_close(self) -> None:
        self.dismiss(None)


class ListScreen(Screen):
    """Browse and filter the task list."""

    BINDINGS = [
        Binding("j", "cursor_down", "Down", show=False),
        Binding("k", "cursor_up", "Up", show=False),
        Binding("enter", "open_task", "Open", show=True),
        Binding("t", "toggle_view", "Tree", show=True),
        Binding("slash", "local_filter", "Filter", show=True),
        Binding("f", "assignee_filter", "Assignee", show=True),
        Binding("c", "clear_filters", "Clear", show=True),
        Binding("s", "search", "Search", show=True),
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
        *,
        load_on_mount: bool = True,
    ) -> None:
        super().__init__()
        self.controller = controller
        self.state = state
        self._load_on_mount = load_on_mount
        self._pending_assignee: Optional[AssigneeFilter] = None
        self._reload_if_unchanged = False
        self._view_mode = "table"
        self._forest: list[HierarchyNode] = []
        self._tree_loaded = False

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        yield Static(id="status-bar")
        yield DataTable(id="task-table", cursor_type="row", zebra_stripes=True)
        yield Tree("Tasks", id="task-tree")
        yield Static("", id="empty-message")
        yield Footer()
        yield LoadingIndicator()

    def on_mount(self) -> None:
        self.query_one(LoadingIndicator).display = False
        table = self.query_one("#task-table", DataTable)
        table.add_columns("Key", "Status", "Type", "Priority", "Assignees", "Title")
        tree = self.query_one("#task-tree", Tree)
        tree.display = False
        tree.show_root = False
        table.focus()
        self._update_chrome()
        if self._load_on_mount and not self.state.tasks and self.state.error is None:
            self.reload_list(refresh=False)
        else:
            self._populate_view()

    def _update_chrome(self) -> None:
        backend = self.controller.backend
        self.title = f"{backend.backend_label} · {backend.scope_label}"
        query = self.state.query or "open"
        assignee = assignee_filter_text(self.state.assignee_filter)
        filter_label = f" · filter: {self.state.filter_text}" if self.state.filter_text else ""
        visible = len(filter_tasks(self.state.tasks, self.state.filter_text))
        view = "tree" if self._view_mode == "tree" else "table"
        tree_note = ""
        if self._view_mode == "tree" and self._forest:
            tree_note = f" · tree: {self._count_nodes(self._forest)} nodes"
        status = self.query_one("#status-bar", Static)
        if self.state.error:
            status.update(f"Error: {self.state.error}")
            status.add_class("error")
        else:
            status.update(
                f"Query: {query} · assignee: {assignee}{filter_label} · "
                f"{visible}/{len(self.state.tasks)} · view: {view}{tree_note}"
            )
            status.remove_class("error")

    @staticmethod
    def _count_nodes(nodes: Sequence[HierarchyNode]) -> int:
        return sum(1 + ListScreen._count_nodes(node.children) for node in nodes)

    def _populate_view(self) -> None:
        if self._view_mode == "tree":
            self._populate_tree()
        else:
            self._populate_table()

    def _populate_table(self) -> None:
        table = self.query_one("#task-table", DataTable)
        tree = self.query_one("#task-tree", Tree)
        empty = self.query_one("#empty-message", Static)
        tree.display = False
        table.clear()
        tasks = filter_tasks(self.state.tasks, self.state.filter_text)
        if self.state.error:
            table.display = False
            empty.display = True
            empty.update(f"Error: {self.state.error}")
            return
        if not tasks:
            table.display = False
            empty.display = True
            empty.update(
                "No tasks match the local filter."
                if self.state.tasks and self.state.filter_text
                else "No tasks found."
            )
            return
        table.display = True
        empty.display = False
        for task in tasks:
            table.add_row(
                task.display_key,
                task.status,
                task.task_type or "-",
                task.priority or "-",
                ", ".join(task.assignees) or "-",
                task.title,
                key=task.identity.stable_id,
            )
        index = min(max(self.state.index, 0), len(tasks) - 1)
        self.state.index = index
        table.move_cursor(row=index)
        table.focus()

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
        if not self._forest and not filter_tasks(self.state.tasks, self.state.filter_text):
            tree.display = False
            empty.display = True
            empty.update(
                "No tasks match the local filter."
                if self.state.tasks and self.state.filter_text
                else "No tasks found."
            )
            return
        empty.display = False
        tree.display = True
        _mount_hierarchy(tree.root, self._forest)
        tree.root.expand()
        tree.focus()
        self._update_chrome()

    def _set_loading(self, active: bool) -> None:
        self.query_one(LoadingIndicator).display = active

    def _build_forest(self) -> list[HierarchyNode]:
        items = list(self.controller.cached_items.values()) or list(self.state.tasks)
        if self.state.filter_text:
            items = filter_tasks(items, self.state.filter_text)
        return build_forest_from_summaries(items)

    @work(exclusive=True, thread=True)
    def reload_list(self, refresh: bool = False, full: bool = False) -> None:
        self.app.call_from_thread(self._set_loading, True)
        forest: list[HierarchyNode] = []
        try:
            self.controller.load_list(self.state, refresh=refresh, full=full)
            if self._view_mode == "tree":
                forest = self._build_forest()
        finally:
            self.app.call_from_thread(self._after_reload, forest)

    def _after_reload(self, forest: Optional[list[HierarchyNode]] = None) -> None:
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
            self.controller.change_assignee_filter(
                self.state,
                selection,
                reload_if_unchanged=reload_if_unchanged,
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
            self.controller.clear_filters(self.state)
            if self._view_mode == "tree":
                forest = self._build_forest()
        finally:
            self.app.call_from_thread(self._after_reload, forest)

    def action_toggle_view(self) -> None:
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
        if self._view_mode == "tree":
            self.query_one("#task-tree", Tree).action_cursor_down()
        else:
            self.query_one("#task-table", DataTable).action_cursor_down()

    def action_cursor_up(self) -> None:
        if self._view_mode == "tree":
            self.query_one("#task-tree", Tree).action_cursor_up()
        else:
            self.query_one("#task-table", DataTable).action_cursor_up()

    @on(DataTable.RowHighlighted)
    def track_cursor(self, event: DataTable.RowHighlighted) -> None:
        if event.cursor_row is not None and event.cursor_row >= 0:
            self.state.index = event.cursor_row

    @on(DataTable.RowSelected)
    def open_selected_row(self, event: DataTable.RowSelected) -> None:
        if event.cursor_row is not None and event.cursor_row >= 0:
            self.state.index = event.cursor_row
        self.action_open_task()

    def _selected_identity(self) -> Optional[BackendIdentity]:
        if self._view_mode == "tree":
            node = self.query_one("#task-tree", Tree).cursor_node
            if node is not None and isinstance(node.data, BackendIdentity):
                return node.data
            return None
        task = selected_task(self.state)
        return task.identity if task else None

    def action_open_task(self) -> None:
        identity = self._selected_identity()
        if identity is None:
            return
        self.app.push_screen(DetailScreen(self.controller, identity))

    def action_local_filter(self) -> None:
        def apply(value: Optional[str]) -> None:
            if value is None:
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

        self.app.push_screen(
            InputModal("Local filter", initial=self.state.filter_text, placeholder="text…"),
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

    def action_clear_filters(self) -> None:
        self.clear_filters_worker()

    def action_search(self) -> None:
        def apply(value: Optional[str]) -> None:
            if value is None:
                return
            new_state = self.controller.make_list_state(
                query=value or None,
                assignee_filter=self.state.assignee_filter,
            )
            self.app.push_screen(ListScreen(self.controller, new_state, load_on_mount=True))

        self.app.push_screen(InputModal("Backend search", placeholder="search…"), apply)

    def action_refresh(self) -> None:
        self._tree_loaded = False
        self.reload_list(refresh=True, full=False)

    def action_full_reload(self) -> None:
        self._tree_loaded = False
        self.reload_list(refresh=True, full=True)

    def action_open_url(self) -> None:
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


class DetailScreen(Screen):
    """Task detail with content + relationships panes."""

    BINDINGS = [
        Binding("j", "move_down", "Down", show=False),
        Binding("k", "move_up", "Up", show=False),
        Binding("enter", "open_relationship", "Open", show=True),
        Binding("tab", "toggle_focus", "Focus", show=True),
        Binding("s", "search", "Search", show=True),
        Binding("r", "refresh", "Refresh", show=True),
        Binding("o", "open_url", "Open URL", show=True),
        Binding("question_mark", "help", "Help", show=True),
        Binding("h", "back", "Back", show=True),
        Binding("backspace", "back", show=False),
        Binding("escape", "back", show=False),
        Binding("q", "quit_app", "Quit", show=True),
    ]

    def __init__(self, controller: TasksController, identity: BackendIdentity) -> None:
        super().__init__()
        self.controller = controller
        self.identity = identity
        self.detail: Optional[TaskDetail] = None
        self.error: Optional[str] = None
        self._focus_relations = False
        self._pending_target: Optional[BackendIdentity] = None
        self._hierarchy: Optional[HierarchyNode] = None

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        yield Static(id="status-bar")
        with Horizontal(id="detail-body"):
            with VerticalScroll(id="content-pane"):
                yield Markdown("", id="content-body")
            with Vertical(id="relations-pane"):
                yield Tree("Relationships", id="relations-tree")
        yield Footer()
        yield LoadingIndicator()

    def on_mount(self) -> None:
        self.query_one(LoadingIndicator).display = False
        self.query_one("#content-pane").border_title = "Content"
        self.query_one("#relations-pane").border_title = "Relationships"
        tree = self.query_one("#relations-tree", Tree)
        tree.show_root = False
        self._set_pane_focus(False)
        self.reload_detail(refresh=False)

    def _set_loading(self, active: bool) -> None:
        self.query_one(LoadingIndicator).display = active

    def _set_pane_focus(self, relations: bool) -> None:
        self._focus_relations = relations
        content = self.query_one("#content-pane")
        relations_pane = self.query_one("#relations-pane")
        content.set_class(not relations, "focused-pane")
        relations_pane.set_class(relations, "focused-pane")
        if relations:
            self.query_one("#relations-tree", Tree).focus()
        else:
            self.query_one("#content-pane", VerticalScroll).focus()

    @work(exclusive=True, thread=True)
    def reload_detail(self, refresh: bool = False) -> None:
        self.app.call_from_thread(self._set_loading, True)
        detail = None
        error = None
        hierarchy = None
        try:
            detail, error = self.controller.load_detail(self.identity, refresh=refresh)
            if detail is not None:
                hierarchy = build_relationship_hierarchy(self.controller, detail)
        finally:
            self.app.call_from_thread(self._after_reload, detail, error, hierarchy)

    def _after_reload(
        self,
        detail: Optional[TaskDetail],
        error: Optional[str],
        hierarchy: Optional[HierarchyNode] = None,
    ) -> None:
        self._set_loading(False)
        self.detail = detail
        self.error = error
        self._hierarchy = hierarchy
        status = self.query_one("#status-bar", Static)
        if detail is None:
            key = self.identity.display_key
            self.title = f"{key} · Unavailable"
            status.update(f"Error: {error}" if error else "Task detail could not be loaded.")
            status.add_class("error")
            self.query_one("#content-body", Markdown).update(
                "Task detail could not be loaded."
            )
            self._populate_relations_tree(None)
            return
        summary = detail.summary
        self.title = f"{summary.display_key} · {summary.title}"
        if error:
            status.update(f"Error: {error}")
            status.add_class("error")
        else:
            status.update(
                f"{summary.status} · {summary.task_type or '-'} · "
                f"{', '.join(summary.assignees) or 'unassigned'}"
            )
            status.remove_class("error")
        self.query_one("#content-body", Markdown).update(detail_content_text(detail))
        self._populate_relations_tree(hierarchy)

    def _populate_relations_tree(self, hierarchy: Optional[HierarchyNode]) -> None:
        tree = self.query_one("#relations-tree", Tree)
        tree.clear()
        if hierarchy is None:
            tree.root.add("None")
            return
        _mount_hierarchy(tree.root, [hierarchy])
        tree.root.expand()

    @on(Tree.NodeSelected)
    def open_selected_relation(self, event: Tree.NodeSelected) -> None:
        if event.node.data is None or not isinstance(event.node.data, BackendIdentity):
            return
        self._pending_target = event.node.data
        self.open_related_worker()

    @work(exclusive=True, thread=True)
    def open_related_worker(self) -> None:
        target = self._pending_target
        if target is None:
            return
        self.app.call_from_thread(self._set_loading, True)
        detail, error = self.controller.load_detail(target)
        self.app.call_from_thread(self._open_related, target, detail, error)

    def _open_related(
        self,
        target: BackendIdentity,
        detail: Optional[TaskDetail],
        error: Optional[str],
    ) -> None:
        self._set_loading(False)
        if detail is None:
            self.error = error
            status = self.query_one("#status-bar", Static)
            status.update(f"Error: {error}")
            status.add_class("error")
            return
        self.app.push_screen(DetailScreen(self.controller, target))

    def action_toggle_focus(self) -> None:
        self._set_pane_focus(not self._focus_relations)

    def action_move_down(self) -> None:
        if self._focus_relations:
            self.query_one("#relations-tree", Tree).action_cursor_down()
        else:
            self.query_one("#content-pane", VerticalScroll).scroll_down()

    def action_move_up(self) -> None:
        if self._focus_relations:
            self.query_one("#relations-tree", Tree).action_cursor_up()
        else:
            self.query_one("#content-pane", VerticalScroll).scroll_up()

    def action_open_relationship(self) -> None:
        if not self._focus_relations:
            return
        node = self.query_one("#relations-tree", Tree).cursor_node
        if node is None or not isinstance(node.data, BackendIdentity):
            return
        self._pending_target = node.data
        self.open_related_worker()

    def action_search(self) -> None:
        def apply(value: Optional[str]) -> None:
            if value is None:
                return
            new_state = self.controller.make_list_state(query=value or None)
            self.app.push_screen(ListScreen(self.controller, new_state, load_on_mount=True))

        self.app.push_screen(InputModal("Backend search", placeholder="search…"), apply)

    def action_refresh(self) -> None:
        self.reload_detail(refresh=True)

    def action_open_url(self) -> None:
        url = task_url(self.detail, self.identity)
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
