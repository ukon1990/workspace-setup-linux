"""Issue content and relationship detail screen."""

from __future__ import annotations

import webbrowser
from typing import Optional

from textual import on, work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import Footer, Header, LoadingIndicator, Static, Tree

from ..images import fetch_images, markdown_image_urls
from ..models import BackendIdentity, TaskDetail
from .content import populate_content_stack
from .logic import (
    HierarchyNode,
    TasksController,
    build_relationship_hierarchy,
    detail_content_text,
    format_sync_progress,
    resolve_goto_identity,
    task_url,
)
from .pulls import PullsController
from .screen_helpers import _go_back, _mount_hierarchy
from .screen_modals import HelpScreen, InputModal


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
        Binding("R", "full_reload", "Full", show=True),
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

    def _set_sync_progress(self, progress) -> None:
        self.query_one("#sync-progress", Static).update(format_sync_progress(progress))

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
    def reload_detail(self, refresh: bool = False, full: bool = False) -> None:
        self.app.call_from_thread(self._set_loading, True)
        detail = None
        error = None
        hierarchy = None
        markdown = "Task detail could not be loaded."
        images: dict = {}
        try:
            detail_refresh = refresh or full
            if getattr(self.controller, "persistent_sync", False):
                self.controller.sync_scope(
                    self.controller.scope_for_identity(self.identity),
                    refresh=refresh,
                    full=full,
                    on_progress=lambda progress: self.app.call_from_thread(
                        self._set_sync_progress, progress
                    ),
                )
                dependency_sync = getattr(self.controller, "sync_detail_dependencies", None)
                if dependency_sync:
                    dependency_sync(self.identity, refresh=refresh or full)
                detail_refresh = False
            detail, error = self.controller.load_detail(self.identity, refresh=detail_refresh)
            if detail is not None:
                hierarchy = build_relationship_hierarchy(
                    self.controller, detail, refresh=detail_refresh
                )
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
                f"{', '.join(summary.assignees) or 'unassigned'}{self._sync_status()}"
            )
            status.remove_class("error")
        self._set_content(markdown or detail_content_text(detail), images)
        self._populate_relations_tree(hierarchy)

    def _sync_status(self) -> str:
        changed = getattr(self.controller, "changed_ids", ())
        warning = getattr(self.controller, "sync_warning", None)
        suffix = (
            f" · {len(changed)} changed"
            if changed or getattr(self.controller, "persistent_sync", False)
            else ""
        )
        if warning:
            suffix += f" · {warning}"
        return suffix

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
        from .screens import ListScreen

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

    def action_full_reload(self) -> None:
        self.reload_detail(refresh=True, full=True)

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
