"""Pull-request file selection, markers, and diff rendering."""

from __future__ import annotations

from typing import Optional

from textual import on
from textual.screen import Screen
from textual.widgets import OptionList
from textual.widgets.option_list import Option

from ..pulls import (
    DiffFile,
    comments_for_path,
    format_line_counts,
    review_comment_markers,
    review_comments_by_anchor,
)
from ..review_drafts import get_draft
from ..review_views import file_view_status, hunk_fingerprint
from .diff_view import DiffView


class PullFileView(Screen):
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
        status = file_view_status(self.pull.stable_id, item.path, hunk_fingerprint(item.hunk))
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
        status = file_view_status(self.pull.stable_id, item.path, hunk_fingerprint(item.hunk))
        status_note = {"viewed": " · looked", "stale": " · stale", "new": ""}.get(status, "")
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
