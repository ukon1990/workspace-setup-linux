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
    TextArea,
    Tree,
)
from textual.widgets.option_list import Option
from textual.widgets.tree import TreeNode

from ..filters import AssigneeFilter
from ..images import fetch_images, markdown_image_urls
from ..models import BackendIdentity, PullSummary, TaskDetail
from .content import populate_content_stack
from .logic import (
    ASSIGNEE_FILTER_OPTIONS,
    TABLE_SORT_COLUMNS,
    HierarchyNode,
    ListState,
    SyncProgress,
    TasksController,
    assignee_filter_for_key,
    assignee_filter_text,
    blocked_by_label,
    blocks_label,
    build_forest_from_summaries,
    build_relationship_hierarchy,
    detail_content_text,
    filter_tasks,
    format_sync_progress,
    resolve_goto_identity,
    selected_task,
    set_filter,
    task_url,
    visible_tasks,
)
from .pulls import (
    PULL_SORT_COLUMNS,
    PullsController,
    authors_from_pulls,
    ci_label,
    format_pull_timestamp,
    pull_detail_markdown,
    selected_pull,
    set_author_filter,
    set_pull_filter,
    visible_pulls,
)
from ..pr_views import activity_label
from ..pulls import (
    DiffFile,
    comments_for_path,
    format_line_counts,
    format_review_comments,
    review_comment_markers,
    review_comments_by_anchor,
    split_diff_by_file,
    summarize_diff_files,
    suggestion_fence,
)
from ..review_drafts import (
    DraftComment,
    add_draft_comment,
    clear_draft,
    get_draft,
)
from ..review_views import file_view_status, hunk_fingerprint, mark_file_viewed
from .diff_view import DiffView

HELP_MARKDOWN = """\
# Tasks help

| Key | Action |
| --- | --- |
| `1` / `2` | Issues / PRs (list) or Description / Files (PR detail) |
| `j` / `↓` | Move down (lists / scroll) |
| `k` / `↑` | Move up (lists / scroll) |
| `Enter` | Open task / PR / relationship |
| `Space` | Expand / collapse tree node |
| `t` | Toggle table / tree (Issues) |
| `/` | Local text filter |
| `f` | Assignee filter |
| `a` | Author filter (PRs; Space toggle, Enter confirm) |
| `c` | Clear filters |
| `s` | Backend search |
| `g` | Open issue/task by ID |
| `r` | Refresh (changed since last sync) |
| `R` | Full reload (replace cache) |
| `Tab` | Cycle focus within current PR tab |
| `x` | Toggle hiding generated/excluded files |
| `l` | Mark current file as looked at |
| `Seen` column | `·` never opened · `*` updated since last open · `-` caught up |
| `m` | Open all review comments for current file |
| `c` | Compose inline comment (Files / Diff) |
| `v` | Toggle visual line selection (Diff) |
| `A` / `R` / `S` | Approve / Request changes / Submit comment review |
| `o` | Open URL |
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
        tree_node = parent.add(
            node.progress_label,
            data=node.identity,
            allow_expand=bool(node.children),
        )
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


class AuthorFilterModal(ModalScreen[Optional[frozenset[str]]]):
    """Multi-select authors from the loaded PR list; Space toggles, Enter confirms."""

    ALL_ID = "__all__"

    BINDINGS = [
        Binding("escape", "cancel", "Cancel", show=True),
        Binding("enter", "confirm", "Confirm", show=True, priority=True),
        Binding("space", "toggle", "Toggle", show=True, priority=True),
    ]

    def __init__(
        self,
        authors: Sequence[str],
        *,
        selected: frozenset[str] = frozenset(),
    ) -> None:
        super().__init__()
        self._authors = list(authors)
        self._selected = set(selected)
        self._needle = ""

    def compose(self) -> ComposeResult:
        with Vertical(classes="modal-box", id="author-filter-modal"):
            yield Label("Author filter")
            yield Input(placeholder="search authors…", id="author-search")
            yield Label("", id="author-empty-hint")
            yield OptionList(id="author-options")
            yield Label(
                "Space toggle · Enter confirm · empty = no author filter · Esc cancel"
            )

    def on_mount(self) -> None:
        self._rebuild_options()
        self.query_one("#author-search", Input).focus()

    def _visible_authors(self) -> list[str]:
        needle = self._needle.casefold().strip()
        if not needle:
            return list(self._authors)
        return [name for name in self._authors if needle in name.casefold()]

    def _all_prompt(self) -> str:
        mark = "x" if not self._selected else " "
        return f"[{mark}] All authors"

    def _option_prompt(self, name: str) -> str:
        mark = "x" if name in self._selected else " "
        return f"[{mark}] {name}"

    def _rebuild_options(self, *, keep: Optional[str] = None) -> None:
        options_list = self.query_one("#author-options", OptionList)
        hint = self.query_one("#author-empty-hint", Label)
        if not self._authors:
            hint.update(
                "No authors yet — load PRs first (check assignee filter with f, or refresh)"
            )
            hint.display = True
        else:
            hint.update("")
            hint.display = False

        highlighted = keep
        if highlighted is None and options_list.highlighted is not None:
            try:
                option = options_list.get_option_at_index(options_list.highlighted)
                if option.id is not None:
                    highlighted = str(option.id)
            except Exception:
                highlighted = None

        visible = self._visible_authors()
        options_list.clear_options()
        rows = [Option(self._all_prompt(), id=self.ALL_ID)]
        rows.extend(Option(self._option_prompt(name), id=name) for name in visible)
        options_list.add_options(rows)
        ids = [self.ALL_ID, *visible]
        if highlighted in ids:
            options_list.highlighted = ids.index(highlighted)
        else:
            options_list.highlighted = 0

    @on(Input.Changed, "#author-search")
    def on_search_changed(self, event: Input.Changed) -> None:
        self._needle = event.value
        self._rebuild_options()

    @on(Input.Submitted, "#author-search")
    def on_search_submitted(self, event: Input.Submitted) -> None:
        self.action_confirm()

    def _highlighted_id(self) -> Optional[str]:
        options_list = self.query_one("#author-options", OptionList)
        if not options_list.option_count or options_list.highlighted is None:
            return None
        option = options_list.get_option_at_index(options_list.highlighted)
        if option.id is None:
            return None
        return str(option.id)

    def action_toggle(self) -> None:
        focused = self.focused
        if isinstance(focused, Input):
            focused.insert_text_at_cursor(" ")
            return
        option_id = self._highlighted_id()
        if option_id is None:
            return
        if option_id == self.ALL_ID:
            self._selected.clear()
            self._rebuild_options(keep=self.ALL_ID)
            return
        if option_id in self._selected:
            self._selected.discard(option_id)
        else:
            self._selected.add(option_id)
        self._rebuild_options(keep=option_id)

    def action_confirm(self) -> None:
        self.dismiss(frozenset(self._selected))

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


class ReviewCommentsModal(ModalScreen[None]):
    """Read-only review comments for one file."""

    BINDINGS = [
        Binding("escape", "close", "Close", show=True),
        Binding("q", "close", "Close", show=False),
    ]

    def __init__(self, title: str, body: str) -> None:
        super().__init__()
        self._title = title
        self._body = body

    def compose(self) -> ComposeResult:
        with Vertical(classes="modal-box", id="review-comments-modal"):
            yield Label(self._title)
            with VerticalScroll(id="review-comments-body"):
                yield Markdown(self._body)
            yield Label("Press Esc to close")

    def action_close(self) -> None:
        self.dismiss(None)


class CommentModal(ModalScreen[Optional[str]]):
    """Compose an inline review comment (saved locally until submit)."""

    BINDINGS = [
        Binding("escape", "cancel", "Cancel", show=True),
        Binding("ctrl+s", "insert_suggestion", "Suggest", show=True),
        Binding("ctrl+enter", "save", "Save", show=True),
    ]

    def __init__(
        self,
        title: str,
        *,
        suggestion_lines: tuple[str, ...] = (),
        initial: str = "",
    ) -> None:
        super().__init__()
        self._title = title
        self._suggestion_lines = suggestion_lines
        self._initial = initial

    def compose(self) -> ComposeResult:
        with Vertical(classes="modal-box", id="comment-modal"):
            yield Label(self._title)
            yield TextArea(self._initial, id="comment-body")
            yield Label("ctrl+enter save · ctrl+s suggestion · Esc cancel")

    def on_mount(self) -> None:
        self.query_one("#comment-body", TextArea).focus()

    def action_insert_suggestion(self) -> None:
        area = self.query_one("#comment-body", TextArea)
        fence = suggestion_fence(self._suggestion_lines)
        current = area.text
        if current and not current.endswith("\n"):
            current += "\n"
        area.load_text(current + fence + "\n")

    def action_save(self) -> None:
        self.dismiss(self.query_one("#comment-body", TextArea).text)

    def action_cancel(self) -> None:
        self.dismiss(None)


class ListScreen(Screen):
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
        if self._load_on_mount and not self.state.tasks and self.state.error is None:
            self.reload_list(refresh=False)
        else:
            self._populate_view()

    def on_screen_resume(self) -> None:
        if self._active_tab == "pulls" and self._pulls_loaded:
            self._populate_pulls_table()
            self._update_chrome()

    def _ensure_issue_columns(self) -> None:
        table = self.query_one("#task-table", DataTable)
        table.clear(columns=True)
        table.add_columns(
            ("Key", "key"),
            ("Status", "status"),
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
                f" · filter: {self.pulls_state.filter_text}"
                if self.pulls_state.filter_text
                else ""
            )
            authors = self.pulls_state.author_filter
            author_label = (
                f" · authors: {', '.join(sorted(authors, key=str.casefold))}"
                if authors
                else ""
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
        visible = len(filter_tasks(self.state.tasks, self.state.filter_text))
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
                f"{visible}/{len(self.state.tasks)} · view: {view}{tree_note}"
            )
            status.remove_class("error")

    @staticmethod
    def _count_nodes(nodes: Sequence[HierarchyNode]) -> int:
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
        overlay = self.query_one("#loading-overlay")
        overlay.display = active
        if not active:
            self.query_one("#sync-progress", Static).update("")

    def _set_sync_progress(self, progress: SyncProgress) -> None:
        self.query_one("#sync-progress", Static).update(format_sync_progress(progress))

    def _progress_callback(self):
        return lambda progress: self.app.call_from_thread(self._set_sync_progress, progress)

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
                self.controller.clear_filters(
                    self.state, on_progress=self._progress_callback()
                )
                if self._view_mode == "tree":
                    forest = self._build_forest()
        finally:
            self.app.call_from_thread(self._after_reload, forest)

    @work(exclusive=True, thread=True)
    def reload_pulls(self, refresh: bool = False, full: bool = False) -> None:
        self.app.call_from_thread(self._set_loading, True)
        try:
            self.pulls_controller.load_list(
                self.pulls_state, refresh=refresh, full=full
            )
            self._pulls_loaded = True
        finally:
            self.app.call_from_thread(self._after_reload, None)

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
            self.pulls_state.filter_text
            if self._active_tab == "pulls"
            else self.state.filter_text
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


class DetailScreen(Screen):
    """Task detail with content + relationships panes."""

    BINDINGS = [
        Binding("j", "move_down", "Down", show=False),
        Binding("k", "move_up", "Up", show=False),
        Binding("enter", "open_relationship", "Open", show=True),
        Binding("tab", "toggle_focus", "Focus", show=True),
        Binding("s", "search", "Search", show=True),
        Binding("g", "goto", "Goto", show=True),
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
                yield Vertical(id="content-stack")
            with Vertical(id="relations-pane"):
                yield Tree("Relationships", id="relations-tree")
        yield Footer()
        with Vertical(id="loading-overlay"):
            yield LoadingIndicator()
            yield Static("", id="sync-progress")

    def on_mount(self) -> None:
        self.query_one("#loading-overlay").display = False
        self.query_one("#content-pane").border_title = "Content"
        self.query_one("#relations-pane").border_title = "Relationships"
        tree = self.query_one("#relations-tree", Tree)
        tree.show_root = False
        tree.auto_expand = False
        self._set_pane_focus(False)
        self.reload_detail(refresh=False)

    def _set_loading(self, active: bool) -> None:
        overlay = self.query_one("#loading-overlay")
        overlay.display = active
        if not active:
            self.query_one("#sync-progress", Static).update("")

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

    def _set_content(self, markdown: str, images: Optional[dict] = None) -> None:
        populate_content_stack(self.query_one("#content-stack", Vertical), markdown, images)

    @work(exclusive=True, thread=True)
    def reload_detail(self, refresh: bool = False) -> None:
        self.app.call_from_thread(self._set_loading, True)
        detail = None
        error = None
        hierarchy = None
        markdown = "Task detail could not be loaded."
        images: dict = {}
        try:
            detail, error = self.controller.load_detail(self.identity, refresh=refresh)
            if detail is not None:
                hierarchy = build_relationship_hierarchy(self.controller, detail)
                markdown = detail_content_text(detail)
                images = fetch_images(markdown_image_urls(markdown))
        finally:
            self.app.call_from_thread(
                self._after_reload, detail, error, hierarchy, markdown, images
            )

    def _after_reload(
        self,
        detail: Optional[TaskDetail],
        error: Optional[str],
        hierarchy: Optional[HierarchyNode] = None,
        markdown: str = "",
        images: Optional[dict] = None,
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
            self._set_content(markdown or "Task detail could not be loaded.")
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
        self._set_content(markdown or detail_content_text(detail), images)
        self._populate_relations_tree(hierarchy)

    def _populate_relations_tree(self, hierarchy: Optional[HierarchyNode]) -> None:
        tree = self.query_one("#relations-tree", Tree)
        tree.clear()
        if hierarchy is None:
            tree.root.add("None", allow_expand=False)
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
            pulls = getattr(self.app, "pulls_controller", None)
            self.app.push_screen(
                ListScreen(
                    self.controller,
                    new_state,
                    pulls if isinstance(pulls, PullsController) else None,
                    load_on_mount=True,
                )
            )

        self.app.push_screen(InputModal("Backend search", placeholder="search…"), apply)

    def action_goto(self) -> None:
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



class PullDetailScreen(Screen):
    """PR detail with Description and Files tabs."""

    BINDINGS = [
        Binding("1", "tab_description", "Desc", show=True),
        Binding("2", "tab_files", "Files", show=True),
        Binding("j", "move_down", "Down", show=False),
        Binding("k", "move_up", "Up", show=False),
        Binding("tab", "toggle_focus", "Focus", show=True),
        Binding("x", "toggle_excluded", "Excl", show=True),
        Binding("l", "mark_looked", "Looked", show=True),
        Binding("m", "show_comments", "Comments", show=True),
        Binding("c", "compose_comment", "Comment", show=True),
        Binding("A", "approve_review", "Approve", show=True),
        Binding("R", "request_changes", "Request", show=True),
        Binding("S", "submit_comment_review", "Submit", show=True),
        Binding("r", "refresh", "Refresh", show=True),
        Binding("o", "open_url", "Open URL", show=True),
        Binding("question_mark", "help", "Help", show=True),
        Binding("h", "back", "Back", show=True),
        Binding("backspace", "back", show=False),
        Binding("escape", "back", show=False),
        Binding("q", "quit_app", "Quit", show=True),
    ]

    def __init__(self, controller: PullsController, pull: PullSummary) -> None:
        super().__init__()
        self.controller = controller
        self.pull = pull
        self.detail = None
        self.error: Optional[str] = None
        self._viewed_at_baseline: Optional[str] = controller.viewed_at(pull.stable_id)
        self._active_tab = "description"
        self._focus_pane = 0  # files tab: 0 files, 1 diff
        self._diff_text: Optional[str] = None
        self._diff_error: Optional[str] = None
        self._diff_loaded = False
        self._diff_loading = False
        self._updating_files = False
        self._file_diffs: list[DiffFile] = []
        self._file_index = 0
        self._hide_excluded = False

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        yield Static("", id="pr-tab-bar")
        yield Static(id="status-bar")
        with VerticalScroll(id="content-pane"):
            yield Vertical(id="content-stack")
        with Horizontal(id="diff-side"):
            yield OptionList(id="file-list")
            with VerticalScroll(id="diff-pane"):
                yield DiffView(id="diff-body")
        yield Footer()
        with Vertical(id="loading-overlay"):
            yield LoadingIndicator()
            yield Static("", id="sync-progress")

    def on_mount(self) -> None:
        self.query_one("#loading-overlay").display = False
        self.query_one("#content-pane").border_title = "Description + CI"
        self.query_one("#file-list").border_title = "Files"
        self.query_one("#diff-pane").border_title = "Diff"
        self._show_tab("description")
        self.reload_detail(refresh=False)

    def _set_loading(self, active: bool) -> None:
        overlay = self.query_one("#loading-overlay")
        overlay.display = active
        if not active:
            self.query_one("#sync-progress", Static).update("")

    def _set_content(self, markdown: str, images: Optional[dict] = None) -> None:
        populate_content_stack(self.query_one("#content-stack", Vertical), markdown, images)

    def _update_tab_bar(self) -> None:
        desc = "[b]Description[/b]" if self._active_tab == "description" else "Description"
        files = "[b]Files[/b]" if self._active_tab == "files" else "Files"
        self.query_one("#pr-tab-bar", Static).update(f"{desc}  |  {files}   (1 / 2)")

    def _show_tab(self, tab: str) -> None:
        self._active_tab = tab
        self._update_tab_bar()
        content = self.query_one("#content-pane")
        diff_side = self.query_one("#diff-side")
        content.display = tab == "description"
        diff_side.display = tab == "files"
        if tab == "description":
            content.set_class(True, "focused-pane")
            self.query_one("#file-list").set_class(False, "focused-pane")
            self.query_one("#diff-pane").set_class(False, "focused-pane")
            content.focus()
        else:
            content.set_class(False, "focused-pane")
            self._set_files_focus(self._focus_pane)
            if not self._diff_loaded and not self._diff_loading:
                self.load_diff()
        self._update_status()

    def _set_files_focus(self, pane: int) -> None:
        self._focus_pane = pane % 2
        files = self.query_one("#file-list")
        diff = self.query_one("#diff-pane")
        files.set_class(self._focus_pane == 0, "focused-pane")
        diff.set_class(self._focus_pane == 1, "focused-pane")
        if self._focus_pane == 0:
            files.focus()
        else:
            self.query_one("#diff-body", DiffView).focus()

    def _update_status(self) -> None:
        status = self.query_one("#status-bar", Static)
        if self.error and self.detail is None:
            status.update(f"Error: {self.error}")
            status.add_class("error")
            return
        if self._active_tab == "description":
            if self.detail is None:
                status.update("Loading…")
                status.remove_class("error")
                return
            summary = self.detail.summary
            if self.error:
                status.update(f"Error: {self.error}")
                status.add_class("error")
            else:
                status.update(
                    f"{summary.status} · CI {ci_label(summary.ci_state)} · "
                    f"{summary.author or '-'}"
                )
                status.remove_class("error")
            return
        if self._diff_loading:
            status.update("Loading diff…")
            status.remove_class("error")
            return
        if self._diff_error:
            status.update(f"Error: {self._diff_error}")
            status.add_class("error")
            return
        if not self._diff_loaded:
            status.update("Open Files tab to load diffs")
            status.remove_class("error")
            return
        added, deleted, added_excl, deleted_excl = summarize_diff_files(self._file_diffs)
        visible = [
            item
            for item in self._file_diffs
            if not (self._hide_excluded and item.excluded)
        ]
        excluded_n = sum(1 for item in self._file_diffs if item.excluded)
        hide_note = f" · hide gen on" if self._hide_excluded else ""
        status.update(
            f"{format_line_counts(added, deleted)} all · "
            f"{format_line_counts(added_excl, deleted_excl)} excl gen · "
            f"{len(visible)}/{len(self._file_diffs)} files"
            f" ({excluded_n} gen){hide_note}"
        )
        status.remove_class("error")

    @work(exclusive=True, group="pull-detail", thread=True)
    def reload_detail(self, refresh: bool = False) -> None:
        self.app.call_from_thread(self._set_loading, True)
        detail = None
        error = None
        markdown = "Pull request could not be loaded."
        images: dict = {}
        try:
            detail, error = self.controller.load_detail(self.pull, refresh=refresh)
            if detail is not None:
                markdown = pull_detail_markdown(
                    detail,
                    checks_text=self._format_checks(detail.checks),
                    viewed_at=self._viewed_at_baseline,
                )
                images = fetch_images(markdown_image_urls(markdown))
        finally:
            self.app.call_from_thread(
                self._after_reload, detail, error, refresh, markdown, images
            )

    def _after_reload(
        self,
        detail,
        error: Optional[str],
        refresh: bool = False,
        markdown: str = "",
        images: Optional[dict] = None,
    ) -> None:
        self._set_loading(False)
        self.detail = detail
        self.error = error
        if refresh:
            self._diff_loaded = False
            self._diff_loading = False
            self._diff_text = None
            self._diff_error = None
            self._file_diffs = []
            self._file_index = 0
        if detail is None:
            self.title = f"{self.pull.display_key} · Unavailable"
            self._set_content(markdown or "Pull request could not be loaded.")
            self._update_status()
            return
        summary = detail.summary
        self.pull = summary
        self.title = f"{summary.display_key} · {summary.title}"
        self._set_content(markdown, images)
        self.controller.mark_viewed(summary.stable_id)
        if self._diff_loaded:
            self._apply_file_diffs()
        elif self._active_tab == "files" and not self._diff_loading:
            self.load_diff()
        self._update_status()

    @staticmethod
    def _format_checks(checks) -> str:
        if not checks:
            return "No CI checks."
        lines = []
        for check in checks:
            bucket = check.bucket or ci_label(check.state)
            line = f"`{ci_label(check.state)}` {check.name}"
            if bucket and bucket != ci_label(check.state):
                line += f" ({bucket})"
            if check.link:
                line += f"  \n{check.link}"
            lines.append(f"- {line}")
        return "\n".join(lines)

    @work(exclusive=True, group="pull-diff", thread=True)
    def load_diff(self, refresh: bool = False) -> None:
        self.app.call_from_thread(self._mark_diff_loading, True)
        text = ""
        error = None
        try:
            text, error = self.controller.load_diff(self.pull, refresh=refresh)
        finally:
            self.app.call_from_thread(self._after_diff, text, error)

    def _mark_diff_loading(self, active: bool) -> None:
        self._diff_loading = active
        if active:
            self._set_loading(True)
            self.query_one("#diff-body", DiffView).show_message("Loading diff…")
            self._update_status()

    def _after_diff(self, text: str, error: Optional[str]) -> None:
        self._diff_loading = False
        self._set_loading(False)
        self._diff_loaded = True
        self._diff_text = text
        self._diff_error = error
        if error:
            self._file_diffs = []
            self.query_one("#file-list", OptionList).clear_options()
            self.query_one("#diff-body", DiffView).show_message(f"Error: {error}")
            self._update_status()
            return
        self._file_diffs = split_diff_by_file(
            text, exclude_patterns=self.controller.exclude_patterns
        )
        self._file_index = 0
        self._apply_file_diffs()
        self._update_status()

    def _visible_files(self) -> list[DiffFile]:
        if not self._hide_excluded:
            return list(self._file_diffs)
        return [item for item in self._file_diffs if not item.excluded]

    def _review_comments(self) -> tuple:
        if self.detail is None:
            return ()
        return self.detail.review_comments

    def _file_option_label(self, item: DiffFile) -> str:
        counts = format_line_counts(item.added, item.deleted)
        parts = [counts]
        status = file_view_status(
            self.pull.stable_id, item.path, hunk_fingerprint(item.hunk)
        )
        if status == "viewed":
            parts.append("✓")
        elif status == "stale":
            parts.append("↻")
        comment_n = len(comments_for_path(self._review_comments(), item.path))
        if comment_n:
            parts.append(f"●{comment_n}")
        draft_n = get_draft(self.pull.stable_id).count_for_path(item.path)
        if draft_n:
            parts.append(f"+{draft_n} draft")
        marker = " [gen]" if item.excluded else ""
        return f"{' '.join(parts)}  {item.label}{marker}"

    def _apply_file_diffs(self) -> None:
        files = self.query_one("#file-list", OptionList)
        visible = self._visible_files()
        self._updating_files = True
        try:
            if not visible:
                empty_label = (
                    "(all files excluded — press x to show)"
                    if self._file_diffs and self._hide_excluded
                    else "(no changed files)"
                )
                files.set_options([Option(empty_label, id="empty")])
                self.query_one("#diff-body", DiffView).show_message(
                    self._diff_text or "(empty diff)"
                )
                self.query_one("#diff-pane").border_title = "Diff"
                return
            options = [
                Option(self._file_option_label(item), id=f"file-{index}")
                for index, item in enumerate(visible)
            ]
            files.set_options(options)
            self._file_index = min(max(self._file_index, 0), len(visible) - 1)
            files.highlighted = self._file_index
        finally:
            self._updating_files = False
        self._show_selected_diff()

    def _show_selected_diff(self) -> None:
        visible = self._visible_files()
        if not visible:
            return
        index = min(max(self._file_index, 0), len(visible) - 1)
        self._file_index = index
        item = visible[index]
        comment_n = len(comments_for_path(self._review_comments(), item.path))
        draft_n = get_draft(self.pull.stable_id).count_for_path(item.path)
        status = file_view_status(
            self.pull.stable_id, item.path, hunk_fingerprint(item.hunk)
        )
        status_note = {"viewed": " · looked", "stale": " · stale", "new": ""}.get(
            status, ""
        )
        comment_note = f" · ●{comment_n}" if comment_n else ""
        draft_note = f" · +{draft_n} draft" if draft_n else ""
        self.query_one("#diff-pane").border_title = (
            f"Diff · {item.label} · {format_line_counts(item.added, item.deleted)}"
            f"{comment_note}{draft_note}{status_note}"
        )
        markers = review_comment_markers(self._review_comments(), item.path)
        anchored = review_comments_by_anchor(self._review_comments(), item.path)
        drafts = get_draft(self.pull.stable_id).comments_for_path(item.path)
        view = self.query_one("#diff-body", DiffView)
        view.set_diff(
            item.hunk,
            path=item.path,
            line_markers=markers,
            comments_by_anchor=anchored,
            drafts=drafts,
        )

    @staticmethod
    def _event_option_index(event) -> Optional[int]:
        value = getattr(event, "option_index", None)
        if value is None:
            value = getattr(event, "index", None)
        if isinstance(value, int):
            return value
        option_id = getattr(event, "option_id", None)
        if isinstance(option_id, str) and option_id.startswith("file-"):
            try:
                return int(option_id.removeprefix("file-"))
            except ValueError:
                return None
        return None

    @on(OptionList.OptionHighlighted)
    def on_file_highlighted(self, event: OptionList.OptionHighlighted) -> None:
        if self._updating_files or self._active_tab != "files":
            return
        if event.option_list.id != "file-list":
            return
        index = self._event_option_index(event)
        visible = self._visible_files()
        if index is None or index < 0 or index >= len(visible):
            return
        self._file_index = index
        self._show_selected_diff()

    @on(OptionList.OptionSelected)
    def on_file_selected(self, event: OptionList.OptionSelected) -> None:
        if self._active_tab != "files" or event.option_list.id != "file-list":
            return
        index = self._event_option_index(event)
        visible = self._visible_files()
        if index is None or index < 0 or index >= len(visible):
            return
        self._file_index = index
        self._show_selected_diff()
        self._set_files_focus(1)

    def action_tab_description(self) -> None:
        self._show_tab("description")

    def action_tab_files(self) -> None:
        self._show_tab("files")

    def action_toggle_focus(self) -> None:
        if self._active_tab != "files":
            return
        self._set_files_focus(self._focus_pane + 1)

    def action_toggle_excluded(self) -> None:
        self._hide_excluded = not self._hide_excluded
        self._file_index = 0
        if self._diff_loaded:
            self._apply_file_diffs()
        self._update_status()

    def action_mark_looked(self) -> None:
        if self._active_tab != "files" or not self._diff_loaded:
            self.notify("Open the Files tab first", severity="warning")
            return
        visible = self._visible_files()
        if not visible:
            return
        item = visible[min(max(self._file_index, 0), len(visible) - 1)]
        mark_file_viewed(
            self.pull.stable_id, item.path, hunk_fingerprint(item.hunk)
        )
        self._apply_file_diffs()
        self.notify(f"Marked looked: {item.label}")

    def action_show_comments(self) -> None:
        if self._active_tab != "files" or not self._diff_loaded:
            self.notify("Open the Files tab first", severity="warning")
            return
        visible = self._visible_files()
        if not visible:
            return
        item = visible[min(max(self._file_index, 0), len(visible) - 1)]
        comments = comments_for_path(self._review_comments(), item.path)
        self.app.push_screen(
            ReviewCommentsModal(
                f"Review comments · {item.label}",
                format_review_comments(comments, viewed_at=self._viewed_at_baseline),
            )
        )

    def action_compose_comment(self) -> None:
        if self._active_tab != "files" or not self._diff_loaded:
            self.notify("Open the Files tab first", severity="warning")
            return
        if self._focus_pane != 1:
            self._set_files_focus(1)
        self.query_one("#diff-body", DiffView).action_compose_comment()

    @on(DiffView.CommentRequested)
    def on_comment_requested(self, event: DiffView.CommentRequested) -> None:
        loc = (
            f"{event.side}:{event.start_line}–{event.line}"
            if event.start_line != event.line
            else f"{event.side}:{event.line}"
        )
        title = f"Comment on {event.path} · {loc}"

        def _saved(body: Optional[str]) -> None:
            if body is None:
                return
            text = body.strip()
            if not text:
                self.notify("Comment is empty", severity="warning")
                return
            start = event.start_line if event.start_line != event.line else None
            add_draft_comment(
                self.pull.stable_id,
                DraftComment(
                    path=event.path,
                    side=event.side,
                    line=event.line,
                    body=text,
                    start_line=start,
                ),
            )
            self._apply_file_diffs()
            self.notify("Draft saved locally")

        self.app.push_screen(
            CommentModal(title, suggestion_lines=event.suggestion_lines),
            _saved,
        )

    def action_approve_review(self) -> None:
        self._submit_review("APPROVE")

    def action_request_changes(self) -> None:
        self._submit_review("REQUEST_CHANGES")

    def action_submit_comment_review(self) -> None:
        self._submit_review("COMMENT")

    def _submit_review(self, event: str) -> None:
        if self._active_tab != "files":
            self.notify("Switch to Files tab to submit a review", severity="warning")
            return
        draft = get_draft(self.pull.stable_id)
        label = {
            "APPROVE": "Approve",
            "REQUEST_CHANGES": "Request changes",
            "COMMENT": "Comment",
        }.get(event, event)

        def _with_body(body: Optional[str]) -> None:
            if body is None:
                return
            review_body = body.strip() if body.strip() else draft.body
            comments = [
                {
                    "path": item.path,
                    "side": item.side,
                    "line": item.line,
                    "start_line": item.start_line,
                    "body": item.body,
                }
                for item in draft.comments
            ]
            self._run_submit(event, review_body, comments, label)

        initial = draft.body
        self.app.push_screen(
            CommentModal(
                f"{label} review · {len(draft.comments)} draft comment(s)",
                initial=initial,
            ),
            _with_body,
        )

    @work(exclusive=True, group="pull-submit", thread=True)
    def _run_submit(
        self,
        event: str,
        body: str,
        comments: list,
        label: str,
    ) -> None:
        self.app.call_from_thread(self._set_loading, True)
        error = self.controller.submit_review(
            self.pull, event, body=body, comments=comments
        )
        self.app.call_from_thread(self._after_submit, error, label)

    def _after_submit(self, error: Optional[str], label: str) -> None:
        self._set_loading(False)
        if error:
            self.notify(f"Submit failed (draft kept): {error}", severity="error")
            return
        clear_draft(self.pull.stable_id)
        self.notify(f"{label} submitted")
        self.reload_detail(refresh=True)
        if self._active_tab == "files":
            self.load_diff(refresh=True)

    def action_move_down(self) -> None:
        if self._active_tab == "description":
            self.query_one("#content-pane", VerticalScroll).scroll_down()
            return
        if self._focus_pane == 0:
            self.query_one("#file-list", OptionList).action_cursor_down()
        else:
            self.query_one("#diff-body", DiffView).action_cursor_down()

    def action_move_up(self) -> None:
        if self._active_tab == "description":
            self.query_one("#content-pane", VerticalScroll).scroll_up()
            return
        if self._focus_pane == 0:
            self.query_one("#file-list", OptionList).action_cursor_up()
        else:
            self.query_one("#diff-body", DiffView).action_cursor_up()

    def action_refresh(self) -> None:
        self.reload_detail(refresh=True)
        if self._active_tab == "files":
            self.load_diff(refresh=True)

    def action_open_url(self) -> None:
        url = self.pull.url
        if self.detail is not None and getattr(self.detail, "summary", None):
            url = self.detail.summary.url or url
        if not url:
            self.notify("No URL for this pull request", severity="warning")
            return
        webbrowser.open(url)
        self.notify(f"Opened {url}")

    def action_help(self) -> None:
        self.app.push_screen(HelpScreen())

    def action_back(self) -> None:
        if self._active_tab == "files" and self._focus_pane == 1:
            view = self.query_one("#diff-body", DiffView)
            if view.visual_mode:
                view.action_clear_visual()
                return
        _go_back(self)

    def action_quit_app(self) -> None:
        self.app.exit()
