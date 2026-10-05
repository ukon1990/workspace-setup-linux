"""Pull-request description and diff loading screen."""

from __future__ import annotations

from typing import Optional

from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import Footer, Header, LoadingIndicator, OptionList, Static

from ..images import fetch_images, markdown_image_urls
from ..models import PullSummary
from ..pulls import (
    DiffFile,
    format_line_counts,
    split_diff_by_file,
    summarize_diff_files,
)
from .content import populate_content_stack
from .diff_view import DiffView
from .pull_detail_actions import PullDetailActions
from .pull_file_view import PullFileView
from .pulls import PullsController, ci_label, pull_detail_markdown


class PullDetailScreen(PullFileView, PullDetailActions, Screen):
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
                    f"{summary.status} · CI {ci_label(summary.ci_state)} · {summary.author or '-'}"
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
        visible = [item for item in self._file_diffs if not (self._hide_excluded and item.excluded)]
        excluded_n = sum(1 for item in self._file_diffs if item.excluded)
        hide_note = " · hide gen on" if self._hide_excluded else ""
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
            self.app.call_from_thread(self._after_reload, detail, error, refresh, markdown, images)

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
