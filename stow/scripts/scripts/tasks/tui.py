"""Curses UI for browsing backend-neutral tasks."""

from __future__ import annotations

import copy
import curses
import textwrap
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Optional, Protocol, Sequence, Union

from .filters import AssigneeFilter
from .models import BackendIdentity, TaskDetail, TaskRelationship, TaskSummary

MIN_HEIGHT = 10
MIN_WIDTH = 44


class TaskBackend(Protocol):
    """Small interface implemented by Jira and GitHub integrations."""

    backend_label: str
    scope_label: str

    def list_tasks(
        self,
        query: Optional[str] = None,
        refresh: bool = False,
        assignee_filter: AssigneeFilter = AssigneeFilter.ALL,
    ) -> Sequence[TaskSummary]: ...

    def get_task(self, identity: BackendIdentity, refresh: bool = False) -> TaskDetail: ...


class DetailFocus(str, Enum):
    CONTENT = "content"
    RELATIONSHIPS = "relationships"


@dataclass
class ListState:
    tasks: list[TaskSummary] = field(default_factory=list)
    query: Optional[str] = None
    assignee_filter: AssigneeFilter = AssigneeFilter.ALL
    filter_text: str = ""
    index: int = 0
    scroll: int = 0
    error: Optional[str] = None


@dataclass
class DetailState:
    identity: BackendIdentity
    detail: Optional[TaskDetail] = None
    focus: DetailFocus = DetailFocus.CONTENT
    content_scroll: int = 0
    relationship_index: int = 0
    relationship_scroll: int = 0
    error: Optional[str] = None


ScreenState = Union[ListState, DetailState]


@dataclass
class AppState:
    screen: ScreenState
    history: list[ScreenState] = field(default_factory=list)
    detail_cache: dict[str, TaskDetail] = field(default_factory=dict)
    loading: Optional[str] = None


def clip(text: str, width: int) -> str:
    """Clip text to a terminal row without producing negative slices."""
    return text[: max(0, width)]


def wrap_text(text: str, width: int) -> list[str]:
    """Wrap arbitrary task text while preserving blank lines."""
    if width <= 0:
        return []
    lines: list[str] = []
    for source_line in (text or "").splitlines() or [""]:
        if not source_line:
            lines.append("")
            continue
        lines.extend(
            textwrap.wrap(
                source_line,
                width=width,
                replace_whitespace=False,
                drop_whitespace=True,
                break_long_words=True,
                break_on_hyphens=False,
            )
            or [""]
        )
    return lines


def filter_tasks(tasks: Sequence[TaskSummary], value: str) -> list[TaskSummary]:
    needle = value.casefold().strip()
    if not needle:
        return list(tasks)
    return [
        task
        for task in tasks
        if needle
        in " ".join(
            (
                task.display_key,
                task.title,
                task.status,
                task.task_type or "",
                task.priority or "",
                *task.assignees,
                *task.labels,
                *task.components,
            )
        ).casefold()
    ]


def assignee_filter_text(value: AssigneeFilter) -> str:
    return {
        AssigneeFilter.ALL: "all",
        AssigneeFilter.ME: "@me",
        AssigneeFilter.UNASSIGNED: "unassigned",
        AssigneeFilter.ME_OR_UNASSIGNED: "@me-or-unassigned",
        AssigneeFilter.ASSIGNED_ANYONE: "assigned",
    }[value]


def assignee_filter_for_key(key: object) -> Optional[AssigneeFilter]:
    if isinstance(key, str):
        return {
            "a": AssigneeFilter.ALL,
            "m": AssigneeFilter.ME,
            "u": AssigneeFilter.UNASSIGNED,
            "o": AssigneeFilter.ME_OR_UNASSIGNED,
            "d": AssigneeFilter.ASSIGNED_ANYONE,
        }.get(key.casefold())
    return None


def clamp_selection(index: int, scroll: int, count: int, visible: int) -> tuple[int, int]:
    if count <= 0:
        return 0, 0
    index = min(max(index, 0), count - 1)
    visible = max(1, visible)
    max_scroll = max(0, count - visible)
    scroll = min(max(scroll, 0), max_scroll)
    if index < scroll:
        scroll = index
    elif index >= scroll + visible:
        scroll = index - visible + 1
    return index, scroll


def move_list(state: ListState, delta: int, visible: int) -> None:
    count = len(filter_tasks(state.tasks, state.filter_text))
    state.index, state.scroll = clamp_selection(state.index + delta, state.scroll, count, visible)


def set_filter(state: ListState, value: str) -> None:
    state.filter_text = value
    state.index = 0
    state.scroll = 0


def toggle_detail_focus(state: DetailState) -> None:
    state.focus = (
        DetailFocus.RELATIONSHIPS if state.focus is DetailFocus.CONTENT else DetailFocus.CONTENT
    )


def move_relationship(state: DetailState, delta: int) -> None:
    count = len(state.detail.relationships) if state.detail else 0
    state.relationship_index = min(max(state.relationship_index + delta, 0), max(0, count - 1))


def selected_task(state: ListState) -> Optional[TaskSummary]:
    tasks = filter_tasks(state.tasks, state.filter_text)
    if not tasks:
        return None
    state.index = min(max(state.index, 0), len(tasks) - 1)
    return tasks[state.index]


def push_screen(state: AppState, screen: ScreenState) -> None:
    state.history.append(copy.deepcopy(state.screen))
    state.screen = screen


def go_back(state: AppState) -> bool:
    """Restore the exact prior screen, or signal that the application should exit."""
    if not state.history:
        return False
    state.screen = state.history.pop()
    return True


def detail_content_lines(detail: TaskDetail, width: int) -> list[str]:
    summary = detail.summary
    metadata = [
        f"Status: {summary.status}",
        f"Type: {summary.task_type or '-'}  Priority: {summary.priority or '-'}",
        f"Assignees: {', '.join(summary.assignees) or '-'}",
        f"Labels: {', '.join(summary.labels) or '-'}",
        f"Components: {', '.join(summary.components) or '-'}",
    ]
    lines = metadata + ["", "Description"]
    lines.extend(wrap_text(detail.description or "(no description)", width))
    if detail.comments:
        lines.extend(("", "Comments"))
        for comment in detail.comments:
            heading = comment.author
            if comment.created_at:
                heading += f" · {comment.created_at}"
            lines.extend((heading, *wrap_text(comment.body or "(empty comment)", width), ""))
    return lines


def relationship_line(relationship: TaskRelationship) -> str:
    suffix = f" — {relationship.summary}" if relationship.summary else ""
    return f"{relationship.label}: {relationship.target.display_key}{suffix}"


class TasksTui:
    def __init__(
        self,
        backend: TaskBackend,
        *,
        initial_tasks: Optional[Sequence[TaskSummary]] = None,
        initial_identity: Optional[BackendIdentity] = None,
        query: Optional[str] = None,
        initial_assignee_filter: AssigneeFilter = AssigneeFilter.ALL,
        on_assignee_filter_change: Optional[Callable[[AssigneeFilter], None]] = None,
    ) -> None:
        self.backend = backend
        self._initial_assignee_filter = initial_assignee_filter
        self._on_assignee_filter_change = on_assignee_filter_change
        if initial_identity is not None:
            screen: ScreenState = DetailState(initial_identity)
        else:
            screen = ListState(
                list(initial_tasks or ()),
                query=query,
                assignee_filter=initial_assignee_filter,
            )
        self.state = AppState(screen)
        self._initial_tasks_supplied = initial_tasks is not None

    def load_initial(self) -> None:
        if isinstance(self.state.screen, DetailState):
            self._load_detail(self.state.screen)
        elif not self._initial_tasks_supplied:
            self._load_list(self.state.screen)

    def _load_list(self, screen: ListState, *, refresh: bool = False) -> None:
        screen.error = None
        try:
            screen.tasks = list(
                self.backend.list_tasks(
                    query=screen.query,
                    refresh=refresh,
                    assignee_filter=screen.assignee_filter,
                )
            )
            count = len(filter_tasks(screen.tasks, screen.filter_text))
            screen.index = min(max(screen.index, 0), max(0, count - 1))
            screen.scroll = min(max(screen.scroll, 0), max(0, count - 1))
        except Exception as error:  # Backends expose user-ready errors.
            screen.error = str(error) or type(error).__name__

    def _load_detail(self, screen: DetailState, *, refresh: bool = False) -> bool:
        screen.error = None
        stable_id = screen.identity.stable_id
        if not refresh and stable_id in self.state.detail_cache:
            screen.detail = self.state.detail_cache[stable_id]
            return True
        try:
            detail = self.backend.get_task(screen.identity, refresh=refresh)
        except Exception as error:  # A failed relationship must remain selectable.
            screen.error = str(error) or type(error).__name__
            return False
        self.state.detail_cache[stable_id] = detail
        screen.detail = detail
        return True

    def open_selected_task(self) -> bool:
        if not isinstance(self.state.screen, ListState):
            return False
        task = selected_task(self.state.screen)
        if task is None:
            return False
        detail = DetailState(task.identity)
        if not self._load_detail(detail):
            self.state.screen.error = detail.error
            return False
        self.state.screen.error = None
        push_screen(self.state, detail)
        return True

    def open_selected_relationship(self) -> bool:
        screen = self.state.screen
        if not isinstance(screen, DetailState) or screen.detail is None:
            return False
        relationships = screen.detail.relationships
        if not relationships:
            return False
        screen.relationship_index = min(max(screen.relationship_index, 0), len(relationships) - 1)
        detail = DetailState(relationships[screen.relationship_index].target)
        if not self._load_detail(detail):
            screen.error = detail.error
            return False
        screen.error = None
        push_screen(self.state, detail)
        return True

    def search(self, query: str) -> None:
        new_screen = ListState(
            query=query or None,
            assignee_filter=self._current_assignee_filter(),
        )
        self._load_list(new_screen)
        push_screen(self.state, new_screen)

    def _current_assignee_filter(self) -> AssigneeFilter:
        if isinstance(self.state.screen, ListState):
            return self.state.screen.assignee_filter
        for screen in reversed(self.state.history):
            if isinstance(screen, ListState):
                return screen.assignee_filter
        return self._initial_assignee_filter

    def change_assignee_filter(
        self,
        selection: AssigneeFilter,
        *,
        notify_if_unchanged: bool = False,
        reload_if_unchanged: bool = False,
    ) -> bool:
        screen = self.state.screen
        if not isinstance(screen, ListState):
            return False
        changed = screen.assignee_filter is not selection
        if changed:
            screen.assignee_filter = selection
            screen.index = 0
            screen.scroll = 0
        if changed or reload_if_unchanged:
            self._load_list(screen)
        if (changed or notify_if_unchanged) and self._on_assignee_filter_change:
            try:
                self._on_assignee_filter_change(selection)
            except Exception as error:
                message = str(error) or type(error).__name__
                screen.error = f"{screen.error}; {message}" if screen.error else message
        return changed

    def clear_filters(self) -> bool:
        screen = self.state.screen
        if not isinstance(screen, ListState):
            return False
        set_filter(screen, "")
        return self.change_assignee_filter(
            AssigneeFilter.ALL,
            notify_if_unchanged=True,
        )

    def refresh(self) -> None:
        screen = self.state.screen
        if isinstance(screen, ListState):
            self._load_list(screen, refresh=True)
        else:
            self._load_detail(screen, refresh=True)

    def run(self) -> None:
        curses.wrapper(self._main)

    def _main(self, stdscr: curses.window) -> None:
        try:
            curses.curs_set(0)
        except curses.error:
            pass
        stdscr.keypad(True)
        self.state.loading = "Loading…"
        self._draw(stdscr)
        self.load_initial()
        self.state.loading = None

        while True:
            self._draw(stdscr)
            key = stdscr.getch()
            if key == curses.KEY_RESIZE:
                continue
            if key in (ord("q"), ord("Q")):
                return
            if key in (curses.KEY_BACKSPACE, 127, 8, ord("h")):
                if not go_back(self.state):
                    return
                continue
            if key == ord("s"):
                query = self._prompt(stdscr, "Backend search: ")
                if query is not None:
                    self.state.loading = "Searching…"
                    self._draw(stdscr)
                    self.search(query)
                    self.state.loading = None
                continue
            if key in (ord("r"), ord("R")):
                self.state.loading = "Refreshing…"
                self._draw(stdscr)
                self.refresh()
                self.state.loading = None
                continue

            height, _ = stdscr.getmaxyx()
            visible = max(1, height - 5)
            screen = self.state.screen
            if isinstance(screen, ListState):
                if key in (curses.KEY_UP, ord("k")):
                    move_list(screen, -1, visible)
                elif key in (curses.KEY_DOWN, ord("j")):
                    move_list(screen, 1, visible)
                elif key == ord("/"):
                    value = self._prompt(stdscr, "Filter: ", screen.filter_text)
                    if value is not None:
                        set_filter(screen, value)
                elif key == ord("f"):
                    selection = self._filter_menu(stdscr)
                    if selection is not None:
                        self.state.loading = "Filtering…"
                        self._draw(stdscr)
                        self.change_assignee_filter(selection, reload_if_unchanged=True)
                        self.state.loading = None
                elif key == ord("c"):
                    changed = screen.assignee_filter is not AssigneeFilter.ALL
                    if changed:
                        self.state.loading = "Clearing filters…"
                        self._draw(stdscr)
                    self.clear_filters()
                    self.state.loading = None
                elif key in (curses.KEY_ENTER, 10, 13):
                    self.state.loading = "Loading task…"
                    self._draw(stdscr)
                    self.open_selected_task()
                    self.state.loading = None
            else:
                self._handle_detail_key(screen, key, stdscr)

    def _handle_detail_key(self, screen: DetailState, key: int, stdscr: curses.window) -> None:
        if key == ord("\t"):
            toggle_detail_focus(screen)
        elif key in (curses.KEY_UP, ord("k")):
            if screen.focus is DetailFocus.CONTENT:
                screen.content_scroll = max(0, screen.content_scroll - 1)
            else:
                move_relationship(screen, -1)
        elif key in (curses.KEY_DOWN, ord("j")):
            if screen.focus is DetailFocus.CONTENT:
                height, width = stdscr.getmaxyx()
                relationship_width = min(40, max(18, width // 3))
                content_width = max(1, width - relationship_width - 3)
                line_count = (
                    len(detail_content_lines(screen.detail, content_width)) if screen.detail else 0
                )
                body_height = max(1, height - 4)
                screen.content_scroll = min(
                    max(0, line_count - body_height), screen.content_scroll + 1
                )
            else:
                move_relationship(screen, 1)
        elif key in (curses.KEY_ENTER, 10, 13) and screen.focus is DetailFocus.RELATIONSHIPS:
            self.state.loading = "Loading related task…"
            self._draw(stdscr)
            self.open_selected_relationship()
            self.state.loading = None

    def _draw(self, stdscr: curses.window) -> None:
        stdscr.erase()
        height, width = stdscr.getmaxyx()
        if height < MIN_HEIGHT or width < MIN_WIDTH:
            self._safe_addstr(
                stdscr,
                0,
                0,
                f"Terminal too small ({width}x{height}); need {MIN_WIDTH}x{MIN_HEIGHT}.",
            )
            stdscr.refresh()
            return
        if self.state.loading:
            self._safe_addstr(stdscr, 0, 0, self.state.loading)
        elif isinstance(self.state.screen, ListState):
            self._draw_list(stdscr, self.state.screen)
        else:
            self._draw_detail(stdscr, self.state.screen)
        stdscr.refresh()

    def _draw_list(self, stdscr: curses.window, screen: ListState) -> None:
        height, width = stdscr.getmaxyx()
        title = f"{self.backend.backend_label} tasks · {self.backend.scope_label}"
        query = screen.query or "open"
        filter_label = f" · filter: {screen.filter_text}" if screen.filter_text else ""
        self._safe_addstr(stdscr, 0, 0, title)
        assignee = assignee_filter_text(screen.assignee_filter)
        self._safe_addstr(
            stdscr,
            1,
            0,
            f"Query: {query} · assignee: {assignee}{filter_label}",
        )
        tasks = filter_tasks(screen.tasks, screen.filter_text)
        visible = height - 4
        screen.index, screen.scroll = clamp_selection(
            screen.index, screen.scroll, len(tasks), visible
        )
        if screen.error:
            self._safe_addstr(stdscr, 3, 0, f"Error: {screen.error}")
        elif not tasks:
            message = (
                "No tasks match the local filter."
                if screen.tasks and screen.filter_text
                else "No tasks found."
            )
            self._safe_addstr(stdscr, 3, 0, message)
        else:
            for row, task in enumerate(tasks[screen.scroll : screen.scroll + visible], start=2):
                marker = ">" if screen.scroll + row - 2 == screen.index else " "
                metadata = f"[{task.status}]"
                self._safe_addstr(
                    stdscr,
                    row,
                    0,
                    f"{marker} {task.display_key} {metadata} {task.title}",
                    curses.A_REVERSE if marker == ">" else 0,
                )
        back = "back" if self.state.history else "exit"
        movement = "↑/k ↓/j move  Enter open  " if tasks else ""
        footer = (
            f"{movement}/ text  f assignee ({assignee})  c clear  s search  r refresh  "
            f"h/Backspace {back}  q quit"
        )
        self._safe_addstr(stdscr, height - 1, 0, footer)

    def _draw_detail(self, stdscr: curses.window, screen: DetailState) -> None:
        height, width = stdscr.getmaxyx()
        detail = screen.detail
        key = detail.summary.display_key if detail else screen.identity.display_key
        title = detail.summary.title if detail else "Unavailable"
        self._safe_addstr(stdscr, 0, 0, f"{key} · {title}")
        if screen.error:
            self._safe_addstr(stdscr, 1, 0, f"Error: {screen.error}")
        if detail is None:
            self._safe_addstr(stdscr, 3, 0, "Task detail could not be loaded.")
        else:
            body_height = height - 4
            relationship_width = min(40, max(18, width // 3))
            content_width = max(1, width - relationship_width - 3)
            content = detail_content_lines(detail, content_width)
            screen.content_scroll = min(screen.content_scroll, max(0, len(content) - body_height))
            content_attr = curses.A_BOLD if screen.focus is DetailFocus.CONTENT else 0
            relation_attr = curses.A_BOLD if screen.focus is DetailFocus.RELATIONSHIPS else 0
            self._safe_addstr(stdscr, 2, 0, "Content", content_attr)
            relation_x = content_width + 2
            self._safe_addstr(stdscr, 2, relation_x, "Relationships", relation_attr)
            for row, line in enumerate(
                content[screen.content_scroll : screen.content_scroll + body_height],
                start=3,
            ):
                self._safe_addstr(stdscr, row, 0, line, max_width=content_width)
            relationships = detail.relationships
            screen.relationship_index, screen.relationship_scroll = clamp_selection(
                screen.relationship_index,
                screen.relationship_scroll,
                len(relationships),
                body_height,
            )
            if not relationships:
                self._safe_addstr(stdscr, 3, relation_x, "None")
            else:
                for row, relationship in enumerate(
                    relationships[
                        screen.relationship_scroll : screen.relationship_scroll + body_height
                    ],
                    start=3,
                ):
                    selected = screen.relationship_scroll + row - 3 == screen.relationship_index
                    marker = ">" if selected else " "
                    attr = (
                        curses.A_REVERSE
                        if selected and screen.focus is DetailFocus.RELATIONSHIPS
                        else 0
                    )
                    self._safe_addstr(
                        stdscr,
                        row,
                        relation_x,
                        f"{marker} {relationship_line(relationship)}",
                        attr,
                        max_width=relationship_width,
                    )
        back = "back" if self.state.history else "exit"
        if detail is None:
            context_keys = ""
        elif screen.focus is DetailFocus.CONTENT:
            context_keys = "Tab relationships  ↑/k ↓/j scroll  "
        else:
            context_keys = "Tab content  ↑/k ↓/j select  Enter open  "
        footer = f"{context_keys}s search  r refresh  h/Backspace {back}  q quit"
        self._safe_addstr(stdscr, height - 1, 0, footer)

    def _prompt(self, stdscr: curses.window, label: str, initial: str = "") -> Optional[str]:
        height, width = stdscr.getmaxyx()
        value = initial
        try:
            curses.curs_set(1)
        except curses.error:
            pass
        while True:
            self._safe_addstr(stdscr, height - 1, 0, f"{label}{value}")
            stdscr.clrtoeol()
            stdscr.refresh()
            key = stdscr.get_wch()
            if key == curses.KEY_RESIZE:
                height, width = stdscr.getmaxyx()
            elif key in (27, "\x1b"):
                result = None
                break
            elif key in (curses.KEY_ENTER, 10, 13, "\n", "\r"):
                result = value.strip()
                break
            elif key in (curses.KEY_BACKSPACE, 127, 8, "\x7f", "\b"):
                value = value[:-1]
            elif (
                isinstance(key, str)
                and len(key) == 1
                and key.isprintable()
                and len(label) + len(value) < max(1, width - 1)
            ):
                value += key
        try:
            curses.curs_set(0)
        except curses.error:
            pass
        return result

    def _filter_menu(self, stdscr: curses.window) -> Optional[AssigneeFilter]:
        height, _ = stdscr.getmaxyx()
        label = "Assignee: [a]ll [m]@me [u]nassigned [o]@me-or-unassigned [d]assigned"
        while True:
            self._safe_addstr(stdscr, height - 1, 0, label)
            stdscr.clrtoeol()
            stdscr.refresh()
            try:
                key = stdscr.get_wch()
            except curses.error:
                return None
            if key == curses.KEY_RESIZE:
                height, _ = stdscr.getmaxyx()
                continue
            if key in (27, "\x1b"):
                return None
            selection = assignee_filter_for_key(key)
            if selection is not None:
                return selection

    @staticmethod
    def _safe_addstr(
        stdscr: curses.window,
        row: int,
        column: int,
        text: str,
        attr: int = 0,
        *,
        max_width: Optional[int] = None,
    ) -> None:
        height, width = stdscr.getmaxyx()
        if row < 0 or row >= height or column < 0 or column >= width:
            return
        available = width - column - 1
        if max_width is not None:
            available = min(available, max_width)
        try:
            stdscr.addstr(row, column, clip(text, available), attr)
        except curses.error:
            pass


def run(
    backend: TaskBackend,
    *,
    initial_tasks: Optional[Sequence[TaskSummary]] = None,
    initial_identity: Optional[BackendIdentity] = None,
    query: Optional[str] = None,
    initial_assignee_filter: AssigneeFilter = AssigneeFilter.ALL,
    on_assignee_filter_change: Optional[Callable[[AssigneeFilter], None]] = None,
) -> None:
    """Launch the task browser."""
    TasksTui(
        backend,
        initial_tasks=initial_tasks,
        initial_identity=initial_identity,
        query=query,
        initial_assignee_filter=initial_assignee_filter,
        on_assignee_filter_change=on_assignee_filter_change,
    ).run()
