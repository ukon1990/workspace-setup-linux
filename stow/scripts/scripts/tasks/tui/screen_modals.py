"""Keyboard-accessible filters, prompts, and help."""

from __future__ import annotations

from typing import Optional, Sequence

from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Input, Label, Markdown, OptionList, TextArea
from textual.widgets.option_list import Option

from ..filters import AssigneeFilter, WorkFilter
from ..pulls import suggestion_fence
from .logic import ASSIGNEE_FILTER_OPTIONS, assignee_filter_for_key

HELP_MARKDOWN = """\
# Tasks help

Issue-detail relationship icons: `✓` completed · `○` unfinished · `?` unknown.
Press `r` to sync changed issues and refresh linked statuses.

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
| `w` | Work filter: All / Available / Ready only (Issues) |
| `a` | Author filter (PRs; Space toggle, Enter confirm) |
| `c` | Clear filters |
| `s` | Backend search |
| `g` | Open issue/task by ID |
| `r` | Refresh (changed since last sync) |
| `R` | Full reload (reset selected issue scope cache) |
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

## Available work (Issues)

`w` chooses All, Available, or Ready only. Available keeps ready issues and
unfinished ancestors containing ready descendants; Ready only keeps ready
issues. Completed issues are hidden in both work modes. A ready issue has no
unfinished blockers on itself or any ancestor. Unknown dependency information
does not qualify as ready.

Work and Ready descendants columns are sortable. Tree labels show the same
information. Descendant counts cover matching loaded issues; the status bar
notes unknown dependencies and potentially partial counts. `r` refreshes
blocker statuses. `c` clears remembered assignee and work filters for this scope.

## Cached issues and changes

Loaded issues and relationships persist per project or repository, with the
200 most recently used issue details retained. Each scope syncs before cached
data is displayed. Startup and `r` fetch changed issues across all update pages
with a five-minute overlap; unchanged relationships reuse cached data. `R`
resets only the selected issue scope. A failed sync leaves cached data visible
with a warning.

The sortable Changed column and `*` beside tree issue keys mark changed versions
for this session. The first sync establishes a baseline without marking every
issue. Opening an issue in another scope syncs that target scope first.
"""


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


class WorkFilterModal(ModalScreen[Optional[WorkFilter]]):
    """Pick available work with keyboard or mouse."""

    BINDINGS = [Binding("escape", "cancel", "Cancel", show=True)]

    def __init__(self, selected: WorkFilter = WorkFilter.ALL) -> None:
        super().__init__()
        self._selected = selected

    def compose(self) -> ComposeResult:
        with Vertical(classes="modal-box"):
            yield Label("Work filter")
            yield OptionList(
                Option("All — all matching issues", id=WorkFilter.ALL.value),
                Option(
                    "Available — ready issues and their unfinished ancestors",
                    id=WorkFilter.AVAILABLE.value,
                ),
                Option("Ready only — issues ready to pick up", id=WorkFilter.READY_ONLY.value),
                id="work-options",
            )

    def on_mount(self) -> None:
        options = self.query_one("#work-options", OptionList)
        options.highlighted = list(WorkFilter).index(self._selected)
        options.focus()

    @on(OptionList.OptionSelected)
    def pick(self, event: OptionList.OptionSelected) -> None:
        if event.option_id is not None:
            self.dismiss(WorkFilter(event.option_id))

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
            yield Label("Space toggle · Enter confirm · empty = no author filter · Esc cancel")

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
