"""Keyboard-driven unified diff viewer with visual line selection."""

from __future__ import annotations

from typing import Callable, Optional, Sequence, Tuple

from rich.text import Text
from textual.binding import Binding
from textual.message import Message
from textual.widgets import Static

from ..pulls import (
    DiffRow,
    parse_diff_rows,
    render_diff_rows,
    selection_github_anchor,
)
from ..review_drafts import DraftComment


def merge_draft_rows(
    rows: Sequence[DiffRow], drafts: Sequence[DraftComment]
) -> list[DiffRow]:
    """Insert local draft previews under matching end-line anchors."""
    by_anchor: dict[tuple[str, int], list[DraftComment]] = {}
    for draft in drafts:
        side = (draft.side or "RIGHT").upper()
        if side not in {"LEFT", "RIGHT"}:
            side = "RIGHT"
        if draft.line <= 0:
            continue
        by_anchor.setdefault((side, draft.line), []).append(draft)

    out: list[DiffRow] = []
    for row in rows:
        out.append(row)
        if not row.selectable or row.side is None:
            continue
        number = row.new_line if row.side == "RIGHT" else row.old_line
        if number is None:
            continue
        for draft in by_anchor.pop((row.side, number), ()):
            loc = _draft_location(draft)
            out.append(DiffRow(kind="draft", raw=f"◇ draft · {loc}"))
            body = (draft.body or "(empty)").splitlines() or ["(empty)"]
            for line in body:
                out.append(DiffRow(kind="draft", raw=line))
            out.append(DiffRow(kind="draft", raw="╰──"))
    return out


def _draft_location(draft: DraftComment) -> str:
    side = (draft.side or "RIGHT").upper()
    if draft.start_line and draft.start_line != draft.line:
        lo, hi = sorted((draft.start_line, draft.line))
        return f"{side}:{lo}–{hi}"
    return f"{side}:{draft.line}"


class DiffView(Static):
    """Focused diff with cursor, visual selection, and comment anchors."""

    can_focus = True
    BINDINGS = [
        Binding("j", "cursor_down", "Down", show=False),
        Binding("down", "cursor_down", show=False),
        Binding("k", "cursor_up", "Up", show=False),
        Binding("up", "cursor_up", show=False),
        Binding("v", "toggle_visual", "Visual", show=True),
        Binding("J", "extend_down", "Sel↓", show=False),
        Binding("shift+down", "extend_down", show=False),
        Binding("K", "extend_up", "Sel↑", show=False),
        Binding("shift+up", "extend_up", show=False),
        Binding("c", "compose_comment", "Comment", show=True),
    ]

    class CommentRequested(Message):
        """User pressed ``c`` with a valid selection/cursor anchor."""

        def __init__(
            self,
            path: str,
            side: str,
            start_line: int,
            line: int,
            suggestion_lines: Tuple[str, ...],
        ) -> None:
            self.path = path
            self.side = side
            self.start_line = start_line
            self.line = line
            self.suggestion_lines = suggestion_lines
            super().__init__()

    def __init__(self, **kwargs) -> None:
        super().__init__("", **kwargs)
        self._rows: list[DiffRow] = []
        self._path = ""
        self._markers: dict = {}
        self.cursor_row = 0
        self.visual_mode = False
        self.sel_anchor: Optional[int] = None
        self.on_changed: Optional[Callable[[], None]] = None

    @property
    def selection(self) -> Optional[Tuple[int, int]]:
        if self.visual_mode and self.sel_anchor is not None:
            return self.sel_anchor, self.cursor_row
        return None

    def set_diff(
        self,
        hunk: str,
        *,
        path: str = "",
        line_markers=None,
        comments_by_anchor=None,
        drafts: Sequence[DraftComment] = (),
    ) -> None:
        self._path = path
        self._markers = line_markers or {}
        base = parse_diff_rows(hunk, comments_by_anchor=comments_by_anchor)
        self._rows = merge_draft_rows(base, drafts)
        if not self._rows:
            self.cursor_row = 0
            self.visual_mode = False
            self.sel_anchor = None
            empty = "(empty diff)" if not (hunk and hunk.strip()) else "(no hunks)"
            self.update(Text(empty, style="dim"))
            return
        self.cursor_row = min(max(self.cursor_row, 0), len(self._rows) - 1)
        if self.sel_anchor is not None:
            self.sel_anchor = min(max(self.sel_anchor, 0), len(self._rows) - 1)
        self._refresh()

    def show_message(self, message: str) -> None:
        self._rows = []
        self.cursor_row = 0
        self.visual_mode = False
        self.sel_anchor = None
        self.update(message)

    def current_anchor(
        self,
    ) -> Optional[Tuple[str, int, int, Tuple[str, ...]]]:
        if not self._rows:
            return None
        if self.selection is not None:
            start, end = self.selection
        else:
            start = end = self.cursor_row
        return selection_github_anchor(self._rows, start, end)

    def action_cursor_down(self) -> None:
        self._move(1, extend=False)

    def action_cursor_up(self) -> None:
        self._move(-1, extend=False)

    def action_extend_down(self) -> None:
        self._ensure_visual()
        self._move(1, extend=True)

    def action_extend_up(self) -> None:
        self._ensure_visual()
        self._move(-1, extend=True)

    def action_toggle_visual(self) -> None:
        if self.visual_mode:
            self.visual_mode = False
            self.sel_anchor = None
        else:
            self.visual_mode = True
            self.sel_anchor = self.cursor_row
        self._refresh()

    def action_clear_visual(self) -> None:
        if not self.visual_mode:
            return
        self.visual_mode = False
        self.sel_anchor = None
        self._refresh()

    def action_compose_comment(self) -> None:
        anchor = self.current_anchor()
        if anchor is None:
            self.app.notify("Select a diff line first (j/k, v to extend)", severity="warning")
            return
        side, start_line, line, texts = anchor
        self.post_message(
            self.CommentRequested(self._path, side, start_line, line, texts)
        )

    def _ensure_visual(self) -> None:
        if not self.visual_mode:
            self.visual_mode = True
            self.sel_anchor = self.cursor_row

    def _move(self, delta: int, *, extend: bool) -> None:
        if not self._rows:
            return
        if extend:
            self._ensure_visual()
        elif self.visual_mode:
            # Plain j/k (no shift) leaves multi-select and moves as a single cursor.
            self.visual_mode = False
            self.sel_anchor = None
        self.cursor_row = min(max(self.cursor_row + delta, 0), len(self._rows) - 1)
        self._refresh()
        self._scroll_cursor()

    def _scroll_cursor(self) -> None:
        parent = self.parent
        scroll_y = getattr(parent, "scroll_to", None)
        if callable(scroll_y):
            try:
                parent.scroll_to(y=max(self.cursor_row - 2, 0), animate=False)  # type: ignore[call-arg]
            except TypeError:
                pass

    def _refresh(self) -> None:
        if not self._rows:
            return
        self.update(
            render_diff_rows(
                self._rows,
                line_markers=self._markers,
                cursor=self.cursor_row,
                selection=self.selection,
            )
        )
        if self.on_changed:
            self.on_changed()
