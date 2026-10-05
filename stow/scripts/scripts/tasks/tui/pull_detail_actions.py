"""Pull-request navigation and review actions."""

from __future__ import annotations

import webbrowser
from typing import Optional

from textual import on, work
from textual.containers import VerticalScroll
from textual.screen import Screen
from textual.widgets import OptionList

from ..pulls import comments_for_path, format_review_comments
from ..review_drafts import DraftComment, add_draft_comment, clear_draft, get_draft
from ..review_views import hunk_fingerprint, mark_file_viewed
from .diff_view import DiffView
from .screen_helpers import _go_back
from .screen_modals import CommentModal, HelpScreen, ReviewCommentsModal


class PullDetailActions(Screen):
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
        mark_file_viewed(self.pull.stable_id, item.path, hunk_fingerprint(item.hunk))
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
        error = self.controller.submit_review(self.pull, event, body=body, comments=comments)
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
